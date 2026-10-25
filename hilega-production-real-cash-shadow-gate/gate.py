"""Pinned real-cash input, isolated shadow reservations. Never execution permission."""
import hashlib,hmac,json,os,sqlite3
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal,InvalidOperation,ROUND_DOWN,ROUND_UP
from pathlib import Path
from zoneinfo import ZoneInfo
IST=ZoneInfo('Asia/Kolkata')
class Blocked(ValueError):pass

def encode(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def stamp(value):
    try:t=datetime.fromisoformat(value)
    except (ValueError,TypeError):raise Blocked('INVALID_TIME') from None
    if t.tzinfo is None:raise Blocked('AWARE_TIME_REQUIRED')
    return t.astimezone(IST)
def decimal(value):
    if isinstance(value,bool) or not isinstance(value,(int,float,str,Decimal)):raise Blocked('INVALID_AMOUNT')
    try:d=Decimal(str(value))
    except InvalidOperation:raise Blocked('INVALID_AMOUNT') from None
    if not d.is_finite() or d<0:raise Blocked('INVALID_AMOUNT')
    return d

def cents(value,up=False):return int((decimal(value)*100).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN))
def amount(value):return str((Decimal(value)/100).quantize(Decimal('.01')))
def identity(v):
    if not isinstance(v,str) or not 1<=len(v)<=200 or any(ord(c)<32 for c in v):raise Blocked('INVALID_ID')
    return v

def verify_capture(record,pin,*,as_of):
    from market_lab.hilega_production_account_adapter_v1 import sign
    if not isinstance(record,dict):raise Blocked('CAPTURE_REQUIRED')
    data=dict(record);signature=data.pop('signature',None)
    if not isinstance(signature,str) or not hmac.compare_digest(sign(data,pin),signature):raise Blocked('CAPTURE_SIGNATURE_INVALID')
    if data.get('model')!='HILEGA_READ_ONLY_CASH_OBSERVATION_V1' or data.get('evidence_mode')!='LIVE_READ_ONLY_ACCOUNT_PINNED':raise Blocked('PINNED_CASH_CAPTURE_REQUIRED')
    if data.get('account_scope')!=pin['scope'] or data.get('account_identity_verified') is not True:raise Blocked('ACCOUNT_SCOPE_UNVERIFIED')
    if data.get('status')!='READ_ONLY_CAPTURED':raise Blocked('CASH_CAPTURE_FAILED')
    if data.get('account_position_rows_complete') is not True:raise Blocked('INCOMPLETE_ACCOUNT_EVIDENCE')
    if any(data.get(k) is not False for k in ('production_execution_enabled','orders_sent','entry_permission')):raise Blocked('READ_ONLY_FLAGS_REQUIRED')
    now=stamp(as_of);start=stamp(data.get('started_at'));end=stamp(data.get('completed_at'))
    if not 0<=(end-start).total_seconds()<=30 or not 0<=(now-end).total_seconds()<=30:raise Blocked('CAPTURE_STALE_FUTURE_OR_SLOW')
    if start.date()!=now.date() or end.date()!=now.date() or data.get('session_date')!=now.date().isoformat():raise Blocked('WRONG_SESSION')
    identity(data.get('snapshot_id'))
    before=data.get('funds_before');after=data.get('funds_after')
    if not isinstance(before,dict) or not isinstance(after,dict):raise Blocked('FUNDS_REQUIRED')
    field='data.available_to_trade.cash_available_to_trade.total'
    if before.get('field')!=field or after.get('field')!=field:raise Blocked('NET_CASH_FIELD_REQUIRED')
    cash=cents(after.get('cash_available_to_trade'))
    # Capture coherence does not establish order-level debit attribution.
    drift=before!=after or data.get('funds_changed_during_capture') is not False
    reasons=[]
    if drift:reasons.append('FUNDS_CHANGED_DURING_CAPTURE')
    for key in ('orders','trades','positions'):
        if not isinstance(data.get(key),list):raise Blocked('ACCOUNT_EVIDENCE_REQUIRED')
    if data['orders'] or data['trades']:reasons.append('ACCOUNT_ORDER_OR_FILL_ACTIVITY_OWNERSHIP_UNVERIFIED')
    for p in data['positions']:
        if not isinstance(p,dict) or type(p.get('quantity'))is not int:raise Blocked('POSITION_SCHEMA_INVALID')
        if p['quantity']!=0:reasons.append('ACCOUNT_EXPOSURE_OWNERSHIP_UNVERIFIED')
    diagnostics=data.get('diagnostics')
    if not isinstance(diagnostics,dict) or not isinstance(diagnostics.get('issues'),list):raise Blocked('DIAGNOSTICS_REQUIRED')
    if diagnostics['issues']:reasons.append('ACCOUNT_EVIDENCE_DIAGNOSTICS_REQUIRE_REVIEW')
    return dict(snapshot_id=data['snapshot_id'],observed_at=end.isoformat(),session_date=data['session_date'],cash_cents=cash,
        half_cash_cap_cents=cash//2,reasons=sorted(set(reasons)),capture_verified=True,
        debit_attribution='NOT_VALIDATED',production_execution_enabled=False,entry_permission=False)

class ShadowBook:
    """Separate book; cannot read or mutate the application simulator/order ledger."""
    def __init__(self,path,scope):
        self.path=Path(path);self.scope=identity(scope)
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600);os.close(fd);self.path.chmod(0o600)
        with self.tx() as d:
            d.executescript('''CREATE TABLE IF NOT EXISTS scope(id INTEGER PRIMARY KEY,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS captures(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS holds(id TEXT PRIMARY KEY,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL);''')
            old=d.execute('SELECT data FROM scope WHERE id=1').fetchone()
            expected=encode(dict(scope=scope,mode='READ_ONLY_CASH_SHADOW_ONLY'))
            if old and old[0]!=expected:raise Blocked('BOOK_ACCOUNT_SCOPE_MISMATCH')
            d.execute('INSERT OR IGNORE INTO scope VALUES(1,?)',(expected,))
    @contextmanager
    def tx(self):
        d=sqlite3.connect(self.path,timeout=15);d.execute('PRAGMA synchronous=FULL');d.execute('BEGIN IMMEDIATE')
        try:yield d;d.commit()
        except BaseException:d.rollback();raise
        finally:d.close()
    def _holds(self,d):return [json.loads(x[0]) for x in d.execute('SELECT data FROM holds ORDER BY rowid')]
    def record(self,record,pin,*,as_of):
        evidence=verify_capture(record,pin,as_of=as_of)
        if pin['scope']!=self.scope:raise Blocked('BOOK_ACCOUNT_SCOPE_MISMATCH')
        fp=hashlib.sha256(encode(record).encode()).hexdigest();sid=evidence['snapshot_id']
        with self.tx() as d:
            old=d.execute('SELECT fingerprint FROM captures WHERE id=?',(sid,)).fetchone()
            if old and old[0]!=fp:raise Blocked('CAPTURE_ID_REUSED_WITH_DIFFERENT_EVIDENCE')
            latest=d.execute('SELECT data FROM captures ORDER BY rowid DESC LIMIT 1').fetchone()
            if latest and stamp(evidence['observed_at'])<stamp(json.loads(latest[0])['observed_at']):raise Blocked('CAPTURE_TIME_REGRESSION')
            if not old:d.execute('INSERT INTO captures VALUES(?,?,?)',(sid,fp,encode(evidence)))
        return evidence
    def preview(self,record,pin,*,as_of,proposed_cost=None):
        evidence=self.record(record,pin,as_of=as_of)
        with self.tx() as d:return self._preview(d,evidence,proposed_cost)
    def _preview(self,d,evidence,cost=None):
        holds=self._holds(d);held=sum(h['held_cents'] for h in holds);reasons=list(evidence['reasons'])
        if any(h['state']=='UNKNOWN' for h in holds):reasons.append('UNKNOWN_LOCAL_OUTCOME_HOLD_RETAINED')
        if any(h['held_cents'] and h['session_date']!=evidence['session_date'] for h in holds):reasons.append('PRIOR_SESSION_HOLD_REVIEW_REQUIRED')
        capacity=max(0,evidence['half_cash_cap_cents']-held)
        requested=cents(cost,True) if cost is not None else None
        if evidence['half_cash_cap_cents']==0:reasons.append('NO_CASH_CAPACITY')
        if requested is not None:
            if requested<=0:raise Blocked('POSITIVE_PROPOSAL_REQUIRED')
            if requested>capacity:reasons.append('HALF_CASH_CAP_EXCEEDED')
        return dict(model='HILEGA_REAL_CASH_SHADOW_GATE_V1',status='REVIEW_REQUIRED' if reasons else 'READ_ONLY_SHADOW_CAPACITY_AVAILABLE',
            capture_verified=True,available_cash=amount(evidence['cash_cents']),half_cash_cap=amount(evidence['half_cash_cap_cents']),
            full_local_holds=amount(held),assumed_reflected_overlap='0.00',broker_cash_addback='0.00',conservative_capacity=amount(capacity),
            proposed_cost=amount(requested) if requested is not None else None,reasons=sorted(set(reasons)),
            shadow_plan_within_cap=requested is not None and not reasons,holds=holds,
            conservative_full_hold_deduction=True,potential_double_count_not_resolved=bool(held),
            debit_attribution='NOT_VALIDATED',production_execution_enabled=False,entry_permission=False,orders_sent=False,
            application_ledger_updated=False,real_reservation_integration='NOT_WIRED')
    def reserve_shadow(self,plan_id,cost,record,pin,*,as_of):
        identity(plan_id);e=self.record(record,pin,as_of=as_of);requested=cents(cost,True)
        if requested<=0:raise Blocked('POSITIVE_PROPOSAL_REQUIRED')
        with self.tx() as d:
            old=d.execute('SELECT data FROM holds WHERE id=?',(plan_id,)).fetchone()
            if old:
                row=json.loads(old[0])
                if row['amount_cents']!=requested:raise Blocked('PLAN_ID_CONFLICT')
                return dict(row,idempotent_replay=True)
            latest=d.execute('SELECT id FROM captures ORDER BY rowid DESC LIMIT 1').fetchone()
            if not latest or latest[0]!=e['snapshot_id']:raise Blocked('LATEST_CAPTURE_REQUIRED')
            assessment=self._preview(d,e,cost)
            if not assessment['shadow_plan_within_cap']:raise Blocked('SHADOW_PLAN_BLOCKED_'+assessment['reasons'][0])
            row=dict(id=plan_id,amount_cents=requested,held_cents=requested,state='PREPARED_UNSUBMITTED_SHADOW',session_date=e['session_date'],capture_id=e['snapshot_id'],created_at=as_of,submitted=False)
            d.execute('INSERT INTO holds VALUES(?,?)',(plan_id,encode(row)))
            d.execute('INSERT INTO events(data) VALUES(?)',(encode(dict(type='SHADOW_HOLD_CREATED',plan_id=plan_id,at=as_of)),))
            return row
    def mark_unknown(self,plan_id):
        with self.tx() as d:
            found=d.execute('SELECT data FROM holds WHERE id=?',(identity(plan_id),)).fetchone()
            if not found:raise Blocked('PLAN_NOT_FOUND')
            row=json.loads(found[0])
            if row['state']=='CANCELLED_UNSUBMITTED_SHADOW':raise Blocked('TERMINAL_PLAN')
            row['state']='UNKNOWN';d.execute('UPDATE holds SET data=? WHERE id=?',(encode(row),plan_id))
    def cancel_unsubmitted_shadow(self,plan_id):
        with self.tx() as d:
            found=d.execute('SELECT data FROM holds WHERE id=?',(identity(plan_id),)).fetchone()
            if not found:raise Blocked('PLAN_NOT_FOUND')
            row=json.loads(found[0])
            if row['state']=='CANCELLED_UNSUBMITTED_SHADOW':return row
            if row['state']!='PREPARED_UNSUBMITTED_SHADOW' or row.get('submitted') is not False:raise Blocked('UNKNOWN_OR_SUBMITTED_HOLD_CANNOT_RELEASE')
            row.update(state='CANCELLED_UNSUBMITTED_SHADOW',held_cents=0)
            d.execute('UPDATE holds SET data=? WHERE id=?',(encode(row),plan_id));return row
