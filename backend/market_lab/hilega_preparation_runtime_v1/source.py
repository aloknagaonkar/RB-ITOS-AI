"""Verified live strategy journal -> application-owned unsent preparation plans."""
import json
import fcntl
import os
from pathlib import Path
from dotenv import dotenv_values
from . import route,ensure_route,pending
from .pricing_preview import preview as pricing_preview
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE
from .evidence import FLAGS,Blocked,need,evaluate,validate,digest,day,aware,readonly
from market_lab.hilega_production_foundation.core import Service,encode
from market_lab.hilega_production_simulator_bridge_v1 import verified_records,accepted,POLICY,VERSION
from market_lab.hilega_production_bridge_health_v1 import source_timestamp


def configured_evidence():
    """No credentials or network reads unless this explicit route is opted in."""
    from market_lab.hilega_production_account_adapter_v1 import read_pin
    need(route()=='PREPARATION_ONLY','PREPARATION_ROUTE_REQUIRED')
    pin=read_pin(Path(os.getenv('HILEGA_PREPARATION_PIN_FILE',str(Path.home()/'hilega-private/upstox-account-pin.json'))))
    file=os.getenv('HILEGA_PREPARATION_EVIDENCE_FILE')
    if file:
        path=Path(file)
        need(path.is_file() and not path.is_symlink() and path.stat().st_size<=2_000_000,
             'PRIVATE_EVIDENCE_FILE_REQUIRED')
        need(path.stat().st_mode & 0o077 == 0,'EVIDENCE_FILE_MUST_BE_PRIVATE')
        return json.loads(path.read_text()),pin
    need(os.getenv('HILEGA_PREPARATION_CAPTURE_ON_SIGNAL','0')=='1','FRESH_EVIDENCE_PROVIDER_NOT_CONFIGURED')
    config=dotenv_values(Path(os.getenv('HILEGA_PREPARATION_ENV_FILE','.env')))
    def setting(name):
        shell=os.getenv(name);file=config.get(name)
        need(not(shell and file and shell!=file),'SHELL_ENV_FILE_TOKEN_CONFLICT')
        return shell or file
    primary=setting('HILEGA_PRODUCTION_BROKER_READ_TOKEN');secondary=setting('UPSTOX_ACCESS_TOKEN')
    token=(primary or secondary or '').strip()
    need(bool(token),'READ_TOKEN_MISSING')
    from .collect import capture
    return capture(token,pin),pin


def event_digest(event):
    return digest({k:v for k,v in event.items() if k not in {'source_sequence','source_record_hash'}})


class Source:
    """Consumes confirmed ENTRY only; no simulator or real order calls exist here."""
    def __init__(self,service,*,run_id,provider=None):
        need(type(service) is Service,'INSTALLED_CONTROLLER_SERVICE_REQUIRED')
        self.s=service;self.run_id=run_id;self.provider=provider or configured_evidence
        self.checkpoint=lambda stage:None
        with self.s.store.lock():
            need(route()=='PREPARATION_ONLY','PREPARATION_ROUTE_REQUIRED')
            ensure_route(self.s.store)
            with self.s.store.db() as db:
                db.executescript('''
                CREATE TABLE IF NOT EXISTS preparation_source(id INTEGER PRIMARY KEY,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preparation_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preparation_consumed(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preparation_evidence(digest TEXT PRIMARY KEY,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preparation_plans(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preparation_shadow_holds(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preparation_outbox(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                ''')

    def _cursor(self,db,cursor):
        db.execute('INSERT OR REPLACE INTO preparation_source VALUES(1,?)',(encode(cursor),))

    def _audit(self,db,status,reasons):
        db.execute('INSERT INTO preparation_events(data) VALUES(?)',(encode(dict(
            status=status,reasons=sorted(set(reasons)),at=self.s.now().isoformat(),**FLAGS)),))

    def _block_record(self,events,cursor,reason):
        with self.s.store.lock(),self.s.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for event in events:
                fp=event_digest(event)
                old=db.execute('SELECT fingerprint FROM preparation_consumed WHERE id=?',(event['id'],)).fetchone()
                need(old is None or old[0]==fp,'CONFIRMED_EVENT_CONFLICT')
                db.execute('INSERT OR IGNORE INTO preparation_consumed VALUES(?,?)',(event['id'],fp))
            self._pause_in_transaction(db)
            self._audit(db,'BLOCKED',[reason]);self._cursor(db,cursor)

    def _entry(self,event,cursor):
        with self.s.store.lock():
            ensure_route(self.s.store);c=self.s._session()
            fp=event_digest(event)
            with self.s.store.db() as db:
                old=db.execute('SELECT fingerprint FROM preparation_consumed WHERE id=?',(event['id'],)).fetchone()
            if old:
                need(old[0]==fp,'CONFIRMED_EVENT_CONFLICT')
                with self.s.store.db() as db:self._cursor(db,cursor)
                return
            now=self.s.now();signal=aware(event['event_at'])
            if c['mode']!='ARMED' or self.s.store.stop_state()['pending']:
                self._block_record_unlocked(event,cursor,'CONTROLLER_PAUSED_OR_STOP_PENDING');return
            if day(signal)!=day(now) or not 0<=(now-signal).total_seconds()<=60 or not c.get('resumed_at') or signal<=aware(c['resumed_at']):
                self._block_record_unlocked(event,cursor,'SIGNAL_STALE_FUTURE_OR_PRE_RESUME');return
            if pending(self.s.store):
                self._block_record_unlocked(event,cursor,'UNRESOLVED_PREPARATION');return
        # Slow GET evidence collection does not hold the controller flock; Pause
        # can be queued/applied while it runs. Admission is rechecked afterward.
        try:
            bundle,pin=self.provider()
        except Exception:
            self._block_record([event],cursor,'EVIDENCE_PROVIDER_UNAVAILABLE');return
        with self.s.store.lock():
            ensure_route(self.s.store)
            current=self.s._session()
            adapter_path=Path(os.getenv('HILEGA_PREPARATION_ADAPTER_DB','data/research/hilega-broker-adapter-closed/adapter.sqlite'))
            result=evaluate(bundle,pin,direction=event['direction'],as_of=self.s.now().isoformat(),
                controller_db=self.s.store.path,adapter_db=adapter_path,
                expected_version=c['version'],bridge_run_id=self.run_id,signal_at=event['event_at'])
            if result['status']!='READ_ONLY_PREFLIGHT_CHECKS_PASS':
                self._record_result_unlocked(event,cursor,result['reasons']);return
            priced=pricing_preview(bundle,pin,as_of=self.s.now().isoformat(),profile=PROFILE)
            plan=next(p for p in priced['plans'] if p['direction']==event['direction'])
            if not plan['evidence_checks_passed']:
                self._record_result_unlocked(event,cursor,plan['reasons']);return
            self.checkpoint('BEFORE_TRANSACTION')
            # Keep a read transaction on the local closed adapter through the
            # controller commit. This is not atomicity with the remote broker.
            with readonly(adapter_path) as adapter,self.s.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                meta=adapter.execute('SELECT data FROM meta WHERE id=1').fetchone()
                need(meta is not None and json.loads(meta[0])==dict(scope=pin['scope'],mode='LIVE_CLOSED'),'ADAPTER_SCOPE_CHANGED_BEFORE_COMMIT')
                need(not any(adapter.execute('SELECT 1 FROM '+t+' LIMIT 1').fetchone() for t in ('requests','attempts','receipts')),'ADAPTER_ACTIVITY_CHANGED_BEFORE_COMMIT')
                latest=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
                stop=db.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
                need(latest==current and latest['version']==c['version'] and latest['mode']=='ARMED' and stop[0]==stop[1],
                     'CONTROL_CHANGED_OR_STOP_PENDING')
                need(not db.execute('SELECT 1 FROM preparation_plans LIMIT 1').fetchone(),'UNRESOLVED_PREPARATION')
                # Independently recheck all signed input freshness after DB waits.
                again=next(p for p in pricing_preview(bundle,pin,as_of=self.s.now().isoformat(),profile=PROFILE)['plans'] if p['direction']==event['direction'])
                need(again['evidence_checks_passed'] and all(again[k]==plan[k] for k in (
                    'bundle_fingerprint','cash_capture_fingerprint','contract_fingerprint','quote_fingerprint',
                    'instrument','quantity','proposed_cost_cents')), 'EVIDENCE_CHANGED_OR_STALE_BEFORE_COMMIT')
                plan=again
                now=self.s.now();self.s._check_fresh(latest)
                need(day(now)==latest['session_date'] and 0<=(now-signal).total_seconds()<=60,'SIGNAL_OR_SESSION_CHANGED_BEFORE_COMMIT')
                # Mutable local bridge evidence shares this transaction/DB.
                from market_lab.hilega_production_bridge_health_v1 import effective
                health=db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()
                health=json.loads(health[0]) if health else None
                need(health is not None and health.get('run_id')==self.run_id and effective(health,now)['healthy'],
                     'BRIDGE_EVIDENCE_CHANGED_BEFORE_COMMIT')
                bound=dict(id=event['id'],signal_at=event['event_at'],direction=event['direction'],
                    source_sequence=event['source_sequence'],source_record_hash=event['source_record_hash'],
                    instrument=plan['instrument'],quantity=plan['quantity'],status='EVIDENCE_LINKED_UNSENT',
                    evidence=plan,account_scope=pin['scope'],created_at=now.isoformat(),**FLAGS)
                hold=dict(id=event['id'],held_cents=plan['proposed_cost_cents'],
                    evidence_mode='REAL_CASH_OBSERVED_SHADOW_ONLY',real_cash_reserved=False,**FLAGS)
                outbox=dict(id=event['id'],reservation_reference=event['id'],
                    bundle_fingerprint=plan['bundle_fingerprint'],instrument=plan['instrument'],quantity=plan['quantity'],
                    status='NON_EXECUTABLE_PRICING_POLICY_PENDING',request_body=None,**FLAGS)
                old_bundle=db.execute('SELECT data FROM preparation_evidence WHERE digest=?',(plan['bundle_fingerprint'],)).fetchone()
                need(old_bundle is None or json.loads(old_bundle[0])==bundle,'PERSISTED_EVIDENCE_CONFLICT')
                db.execute('INSERT OR IGNORE INTO preparation_evidence VALUES(?,?)',(plan['bundle_fingerprint'],encode(bundle)))
                db.execute('INSERT INTO preparation_plans VALUES(?,?)',(event['id'],encode(bound)))
                self.checkpoint('AFTER_PLAN_INSERT')
                db.execute('INSERT INTO preparation_shadow_holds VALUES(?,?)',(event['id'],encode(hold)))
                db.execute('INSERT INTO preparation_outbox VALUES(?,?)',(event['id'],encode(outbox)))
                db.execute('INSERT INTO preparation_consumed VALUES(?,?)',(event['id'],fp))
                latest.update(mode='PAUSED',version=latest['version']+1,reconciled=False,reason='APPLICATION_UNSENT_PREPARATION_REQUIRES_REVIEW')
                db.execute('UPDATE control SET data=? WHERE id=1',(encode(latest),))
                self._audit(db,'EVIDENCE_LINKED_UNSENT',['PRICING_POLICY_AND_REAL_RESERVATION_PENDING'])
                self._cursor(db,cursor);self.checkpoint('BEFORE_COMMIT')
            self.checkpoint('AFTER_COMMIT')

    def _pause_in_transaction(self,db):
        c=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        if c['mode']=='ARMED':
            c.update(mode='PAUSED',version=c['version']+1,reconciled=False,reason='APPLICATION_PREPARATION_BLOCKED_REQUIRES_EXPLICIT_RESUME')
            db.execute('UPDATE control SET data=? WHERE id=1',(encode(c),))

    def _block_record_unlocked(self,event,cursor,reason):
        self._record_result_unlocked(event,cursor,[reason])

    def _record_result_unlocked(self,event,cursor,reasons):
        with self.s.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT fingerprint FROM preparation_consumed WHERE id=?',(event['id'],)).fetchone()
            fp=event_digest(event);need(old is None or old[0]==fp,'CONFIRMED_EVENT_CONFLICT')
            db.execute('INSERT OR IGNORE INTO preparation_consumed VALUES(?,?)',(event['id'],fp))
            self._pause_in_transaction(db)
            self._audit(db,'BLOCKED',reasons);self._cursor(db,cursor)

    def run_source_once(self,path):
        fd=os.open(str(self.s.store.path)+'.preparation-source.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:return self._run_source_once(path)
            except Exception:
                with self.s.store.lock():self.s._block('APPLICATION_PREPARATION_SOURCE_REJECTED')
                raise
            finally:fcntl.flock(lock,fcntl.LOCK_UN)

    def _run_source_once(self,path):
        records=verified_records(path);source=str(Path(path).resolve())
        source_at=source_timestamp(records,POLICY,VERSION)
        with self.s.store.lock(),self.s.store.db() as db:
            previous=db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()
            previous=json.loads(previous[0]) if previous else None
            if previous is None:
                self._cursor(db,dict(path=source,sequence=len(records),hash=records[-1]['record_hash'] if records else None))
                return dict(status='BASELINED_WAIT_NEXT_CONFIRMED_SIGNAL',source_at=source_at,**FLAGS)
        need(previous['path']==source and previous['sequence']<=len(records),'SOURCE_CHANGED_OR_TRUNCATED')
        need(not previous['sequence'] or records[previous['sequence']-1]['record_hash']==previous['hash'],'SOURCE_PREFIX_REPLACED')
        for row in records[previous['sequence']:]:
            cursor=dict(path=source,sequence=row['sequence'],hash=row['record_hash'])
            p=row.get('payload') or {};at=p.get('decision_timestamp') or p.get('cutoff_timestamp')
            relevant=p.get('policy_id')==POLICY and at and day(aware(at))==day(self.s.now())
            if relevant:
                need(p.get('strategy_version')==VERSION,'SOURCE_POLICY_OR_VERSION_MISMATCH')
                events=accepted(row)
            else:events=[]
            if any(e['role']=='EXIT' for e in events):
                self._block_record(events,cursor,'EXIT_OR_REVERSAL_REQUIRES_LIVE_OWNERSHIP')
            elif events:self._entry(events[0],cursor)
            else:
                with self.s.store.lock(),self.s.store.db() as db:self._cursor(db,cursor)
        return dict(status='APPLICATION_PREPARATION_SOURCE_PROCESSED',source_at=source_at,**FLAGS)

    def poll(self):
        return dict(status='PREPARATION_ONLY_NO_BROKER_RECONCILIATION',**FLAGS)
