"""Durable SQLite loss-latch rehearsal. FIXTURE accounts only; no entry authority."""
from contextlib import closing, contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from hilega_daily_loss_review_v1 import review, aware, integer, require, POLICY, IST

MODEL='HILEGA_ISOLATED_LOSS_LATCH_V1'
TABLES={'meta','sessions','active','audit','sqlite_sequence'}

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def fingerprint(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def fixture_scope(scope):require(isinstance(scope,str) and scope.startswith('FIXTURE:') and len(scope)>8,'FIXTURE_SCOPE_REQUIRED')

def validate_config(config,at):
    fixture_scope(config.get('account_scope'))
    require(config.get('session_date')==at.astimezone(IST).date().isoformat(),'CONFIG_SESSION_MISMATCH')
    require(config.get('policy_approved') is True and config.get('loss_accounting_policy')==POLICY,'FIXTURE_POLICY_APPROVAL_REQUIRED')
    integer(config.get('daily_loss_limit_paise'),'DAILY_LOSS_LIMIT',positive=True)
    integer(config.get('max_entry_cost_paise'),'MAX_ENTRY_COST',positive=True)
    age=integer(config.get('max_pnl_age_seconds'),'PNL_AGE_LIMIT',positive=True)
    require(age<=30,'PNL_AGE_LIMIT_EXCEEDS_REVIEW_SCOPE')
    canonical(config)

class FixtureLatch:
    def __init__(self,path,*,checkpoint=None):
        self.path=Path(path).absolute();self.checkpoint=checkpoint
        require(self.path.is_file() and not self.path.is_symlink(),'EXISTING_FIXTURE_DATABASE_REQUIRED')
        for parent in self.path.parents:require(not parent.is_symlink(),'SYMLINK_PARENT_FORBIDDEN')
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as db:
            self._marker(db)
    @classmethod
    def create(cls,path):
        p=Path(path).absolute()
        require(p.parent.is_dir(),'EXISTING_PARENT_REQUIRED')
        for parent in p.parents:require(not parent.is_symlink(),'SYMLINK_PARENT_FORBIDDEN')
        fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        with closing(sqlite3.connect(p.as_uri()+'?mode=rw',uri=True,isolation_level=None)) as db:
            db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            try:
                for sql in (
                    'CREATE TABLE meta(model TEXT NOT NULL)',
                    'CREATE TABLE sessions(scope TEXT NOT NULL,session TEXT NOT NULL,config TEXT NOT NULL,latched INTEGER NOT NULL CHECK(latched IN(0,1)),highwater INTEGER NOT NULL CHECK(highwater>=0),PRIMARY KEY(scope,session))',
                    'CREATE TABLE active(scope TEXT PRIMARY KEY,session TEXT NOT NULL,FOREIGN KEY(scope,session) REFERENCES sessions(scope,session))',
                    'CREATE TABLE audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT NOT NULL,session TEXT NOT NULL,kind TEXT NOT NULL,request_id TEXT,fingerprint TEXT,data TEXT NOT NULL,UNIQUE(scope,request_id),FOREIGN KEY(scope,session) REFERENCES sessions(scope,session))',
                ):db.execute(sql)
                db.execute('INSERT INTO meta VALUES(?)',(MODEL,));db.execute('COMMIT')
            except BaseException:db.execute('ROLLBACK');raise
        return cls(p)
    @staticmethod
    def _marker(db):
        names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        require(names==TABLES,'NOT_A_FIXTURE_LATCH_DATABASE')
        require(db.execute('SELECT model FROM meta').fetchall()==[(MODEL,)],'FIXTURE_MODEL_MISMATCH')
        require(db.execute('PRAGMA journal_mode').fetchone()[0].lower()=='delete','FIXTURE_DELETE_JOURNAL_REQUIRED')
    @contextmanager
    def transaction(self):
        # Revalidate read-only before opening a write transaction; never migrate
        # or attach an unrelated database.
        self.__class__(self.path)
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=10,isolation_level=None)) as db:
            db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            try:
                self._marker(db);yield db
                if self.checkpoint:self.checkpoint()
                db.execute('COMMIT')
            except BaseException:db.execute('ROLLBACK');raise
    def initialize(self,config,*,as_of):
        at=aware(as_of,'AS_OF');validate_config(config,at)
        scope,session=config['account_scope'],config['session_date']
        with self.transaction() as db:
            require(db.execute('SELECT 1 FROM active WHERE scope=?',(scope,)).fetchone() is None,'ACCOUNT_ALREADY_INITIALIZED')
            db.execute('INSERT INTO sessions VALUES(?,?,?,0,0)',(scope,session,canonical(config)))
            db.execute('INSERT INTO active VALUES(?,?)',(scope,session))
            db.execute('INSERT INTO audit(scope,session,kind,data) VALUES(?,?,?,?)',(scope,session,'INITIALIZE',canonical({'at':at.isoformat()})))
        return self.state(scope)
    @staticmethod
    def _state(db,scope):
        row=db.execute('SELECT s.session,s.config,s.latched,s.highwater FROM sessions s JOIN active a ON s.scope=a.scope AND s.session=a.session WHERE a.scope=?',(scope,)).fetchone()
        require(row is not None,'ACCOUNT_NOT_INITIALIZED')
        return dict(scope=scope,session_date=row[0],config=json.loads(row[1]),latched=bool(row[2]),highwater=row[3])
    def state(self,scope):
        fixture_scope(scope)
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as db,db:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN');self._marker(db)
            result=self._state(db,scope)
            result['audit_count']=db.execute('SELECT COUNT(*) FROM audit WHERE scope=?',(scope,)).fetchone()[0]
        result.update(model=MODEL,fixture_only=True,entry_permission=False,production_execution_enabled=False)
        return result
    def record(self,config,evidence,candidate,*,as_of,request_id):
        at=aware(as_of,'AS_OF');validate_config(config,at)
        require(isinstance(request_id,str) and 0<len(request_id)<=100,'REQUEST_ID_REQUIRED')
        scope,session=config['account_scope'],config['session_date']
        fp=fingerprint(dict(config=config,evidence=evidence,candidate=candidate,as_of=at.isoformat()))
        with self.transaction() as db:
            state=self._state(db,scope)
            require(state['session_date']==session,'EXPLICIT_SESSION_ROLLOVER_REQUIRED')
            require(canonical(state['config'])==canonical(config),'SESSION_POLICY_IMMUTABLE')
            prior=db.execute('SELECT fingerprint,data FROM audit WHERE scope=? AND request_id=?',(scope,request_id)).fetchone()
            if prior:
                require(prior[0]==fp,'REQUEST_ID_CONFLICT')
                result=json.loads(prior[1]);result['idempotent_replay']=True
                result['current_durable_stop_latched']=state['latched']
                if state['latched']:
                    result['status']='BLOCKED';result['reasons']=sorted(set(result['reasons']+['DAILY_STOP_ALREADY_LATCHED']))
                return result
            effective=deepcopy(evidence)
            # Persisted fixture state is authoritative; a caller cannot clear it.
            reported_stop=(evidence.get('daily_stop_latched') is True and evidence.get('account_scope')==scope and evidence.get('session_date')==session)
            effective['daily_stop_latched']=state['latched'] or reported_stop
            result=review(config,effective,candidate,as_of=at,expected_account_scope=scope)
            bad_prefixes=('EVIDENCE_','CONFIG_','PNL_','REALIZED_PNL_','OPEN_PNL_',
                          'FEES_','POSITIONS_UNRECONCILED','REQUESTS_UNRECONCILED',
                          'OPEN_POSITION_COUNT_UNKNOWN','PENDING_REQUEST_COUNT_UNKNOWN',
                          'EXECUTION_OUTCOME_STATE_UNKNOWN','UNRESOLVED_EXECUTION_OUTCOME')
            acceptable=not any(r.startswith(bad_prefixes) for r in result['reasons'])
            measured=result['conservative_loss_used_paise']
            highwater=max(state['highwater'],measured) if acceptable and measured is not None else state['highwater']
            latched=state['latched'] or reported_stop or highwater>=config['daily_loss_limit_paise']
            reasons=set(result['reasons'])
            if latched:reasons.add('DAILY_STOP_ALREADY_LATCHED')
            if highwater>=config['daily_loss_limit_paise']:reasons.add('DAILY_LOSS_LIMIT_REACHED')
            remaining=max(0,config['daily_loss_limit_paise']-highwater)
            cost=result['candidate_max_loss_cost_paise']
            if cost is not None and cost>remaining:reasons.add('REMAINING_LOSS_BUDGET_EXCEEDED')
            result.update(status='BLOCKED' if reasons else 'REVIEWED_ONLY',reasons=sorted(reasons),
                fixture_model=MODEL,fixture_only=True,persisted_loss_highwater_paise=highwater,
                remaining_loss_budget_paise=remaining,current_durable_stop_latched=latched,
                durable_daily_stop_latch_persisted=latched,daily_stop_latch_required=latched,
                evidence_authenticated_by_this_module=False,entry_permission=False,
                production_ready=False,production_execution_enabled=False)
            db.execute('UPDATE sessions SET latched=?,highwater=? WHERE scope=? AND session=?',(int(latched),highwater,scope,session))
            db.execute('INSERT INTO audit(scope,session,kind,request_id,fingerprint,data) VALUES(?,?,?,?,?,?)',(scope,session,'REVIEW',request_id,fp,canonical(result)))
        return result
    def rollover(self,new_config,closure,*,as_of):
        at=aware(as_of,'AS_OF');validate_config(new_config,at)
        scope,session=new_config['account_scope'],new_config['session_date']
        with self.transaction() as db:
            state=self._state(db,scope)
            require(session>state['session_date'],'SAME_OR_PRIOR_SESSION_RESET_FORBIDDEN')
            require(closure.get('account_scope')==scope and closure.get('previous_session_date')==state['session_date'],'CLOSURE_SCOPE_OR_SESSION_MISMATCH')
            require(all(closure.get(k) is True for k in ('previous_session_reconciled','positions_reconciled','requests_reconciled','fees_complete')),'CLOSURE_RECONCILIATION_REQUIRED')
            require(type(closure.get('open_position_count')) is int and closure['open_position_count']==0,'CLOSURE_NOT_FLAT')
            require(type(closure.get('pending_request_count')) is int and closure['pending_request_count']==0,'CLOSURE_PENDING_REQUEST')
            require(closure.get('unresolved_outcome') is False,'CLOSURE_OUTCOME_UNRESOLVED')
            observed=aware(closure.get('observed_at'),'CLOSURE')
            age=(at-observed).total_seconds()
            require(observed.astimezone(IST).date().isoformat()==session and 0<=age<=new_config['max_pnl_age_seconds'],'CLOSURE_NOT_FRESH_NEW_SESSION')
            db.execute('INSERT INTO sessions VALUES(?,?,?,0,0)',(scope,session,canonical(new_config)))
            db.execute('UPDATE active SET session=? WHERE scope=?',(session,scope))
            db.execute('INSERT INTO audit(scope,session,kind,data) VALUES(?,?,?,?)',(scope,session,'EXPLICIT_ROLLOVER',canonical({'previous_session':state['session_date'],'caller_closure':closure,'at':at.isoformat()})))
        return self.state(scope)
