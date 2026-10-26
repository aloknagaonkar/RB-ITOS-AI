"""Persistent controls and fill ledger with one submission/control lock.
SIMULATION ONLY. No network imports, real credentials or broker transport.
UI and CLI integrations must call Service rather than maintain their own flags.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
import fcntl
import hashlib
import json
import os
import sqlite3
import uuid

IST=ZoneInfo('Asia/Kolkata')
TERMINAL={'FILLED','CANCELLED','REJECTED'}

class Blocked(ValueError):pass
class BrokerUnavailable(RuntimeError):pass
class OutcomeUnknown(RuntimeError):pass

def encode(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def positive_int(v):
    if type(v) is not int or v<=0:raise Blocked('POSITIVE_INTEGER_REQUIRED')
    return v

def money(v):
    if isinstance(v,bool):raise Blocked('INVALID_MONEY')
    try:d=Decimal(str(v))
    except Exception:raise Blocked('INVALID_MONEY') from None
    if not d.is_finite() or d<0:raise Blocked('INVALID_MONEY')
    return d

class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        # New DBs created with owner-only permissions. Deployment must protect directory.
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR,0o600);os.close(fd)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS control(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sim_orders(id TEXT PRIMARY KEY,intent TEXT UNIQUE NOT NULL,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sim_fills(id TEXT PRIMARY KEY,order_id TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sim_allocation_config(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sim_allocation_reservations(id TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sim_stop_state(id INTEGER PRIMARY KEY CHECK(id=1),generation INTEGER NOT NULL,handled INTEGER NOT NULL);
            INSERT OR IGNORE INTO sim_stop_state VALUES(1,0,0);
            CREATE TABLE IF NOT EXISTS sim_stop_requests(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,generation INTEGER NOT NULL,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sim_bridge_health(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
            ''')
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=15)
        db.execute('PRAGMA synchronous=FULL')
        try:
            yield db;db.commit()
        except BaseException:
            db.rollback();raise
        finally:db.close()
    @contextmanager
    def lock(self):
        fd=os.open(str(self.path)+'.control.lock',os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,'a') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(f,fcntl.LOCK_UN)
    def queue_stop(self,rid,payload):
        # Independent of the control flock: a pending stop vetoes new BUY.
        uuid.UUID(rid);fp=hashlib.sha256(encode(payload).encode()).hexdigest()
        with self.db() as d:
            d.execute('BEGIN IMMEDIATE')
            old=d.execute('SELECT fingerprint FROM sim_stop_requests WHERE id=?',(rid,)).fetchone()
            if old and old[0]!=fp:raise Blocked('REQUEST_ID_REUSED_WITH_DIFFERENT_COMMAND')
            if not old:
                prior=d.execute('SELECT fingerprint FROM requests WHERE id=?',(rid,)).fetchone()
                if prior and prior[0]!=fp:raise Blocked('REQUEST_ID_REUSED_WITH_DIFFERENT_COMMAND')
                if not prior:
                    d.execute('UPDATE sim_stop_state SET generation=generation+1 WHERE id=1')
                    generation=d.execute('SELECT generation FROM sim_stop_state WHERE id=1').fetchone()[0]
                    d.execute('INSERT INTO sim_stop_requests VALUES(?,?,?,?)',(rid,fp,generation,encode(payload)))
    def stop_state(self):
        with self.db() as d:g,h=d.execute('SELECT generation,handled FROM sim_stop_state WHERE id=1').fetchone()
        return dict(generation=g,handled=h,pending=g>h)
    def control(self):
        with self.db() as d:r=d.execute('SELECT data FROM control WHERE id=1').fetchone()
        return json.loads(r[0]) if r else None
    def save_control(self,v):
        with self.db() as d:d.execute('INSERT OR REPLACE INTO control VALUES(1,?)',(encode(v),))
    def put(self,v):
        with self.db() as d:d.execute('INSERT OR REPLACE INTO intents VALUES(?,?)',(v['id'],encode(v)))
    def intents(self):
        with self.db() as d:return [json.loads(r[0]) for r in d.execute('SELECT data FROM intents ORDER BY rowid')]
    def event(self,kind,at,**kw):
        with self.db() as d:d.execute('INSERT INTO events(data) VALUES(?)',(encode(dict(type=kind,at=at,**kw)),))
    def events(self):
        with self.db() as d:return [dict(sequence=r[0],**json.loads(r[1])) for r in d.execute('SELECT seq,data FROM events ORDER BY seq')]
    def previous(self,rid,payload):
        uuid.UUID(rid)
        fp=hashlib.sha256(encode(payload).encode()).hexdigest()
        with self.db() as d:r=d.execute('SELECT fingerprint,result FROM requests WHERE id=?',(rid,)).fetchone()
        if r and r[0]!=fp:raise Blocked('REQUEST_ID_REUSED_WITH_DIFFERENT_COMMAND')
        return (json.loads(r[1]) if r else None),fp
    def remember(self,rid,fp,result):
        with self.db() as d:d.execute('INSERT INTO requests VALUES(?,?,?)',(rid,fp,encode(result)))

class SimBroker:
    """Durable fake broker. Fault flags are test injection, not production settings."""
    simulation_only=True
    def __init__(self,store):
        self.store=store;self.timeout_after_accept=False;self.unavailable=False
        self.fill_on_cancel=0;self.auto_fill_sells=True;self.before_accept=None
        self.clock=lambda:datetime.now(IST)
    def _check(self):
        if self.unavailable:raise BrokerUnavailable('SIMULATED_BROKER_UNAVAILABLE')
    def place(self,intent):
        self._check()
        if self.before_accept:self.before_accept()
        with self.store.db() as d:
            prior=d.execute('SELECT data FROM sim_orders WHERE intent=?',(intent['id'],)).fetchone()
            if prior:raise Blocked('DUPLICATE_BROKER_SUBMISSION')
            row=dict(order_id='SIM-'+uuid.uuid4().hex,intent_id=intent['id'],instrument=intent['instrument'],
                     side=intent['side'],quantity=intent['quantity'],filled=0,average_price=None,status='OPEN',created_at=self.clock().isoformat())
            if row['side']=='SELL' and self.auto_fill_sells:
                row.update(filled=row['quantity'],average_price=intent['price'],status='FILLED')
            d.execute('INSERT INTO sim_orders VALUES(?,?,?)',(row['order_id'],intent['id'],encode(row)))
            if row['filled']:self._record_fill(d,row,row['filled'],money(row['average_price']))
        if self.timeout_after_accept:
            self.timeout_after_accept=False;raise OutcomeUnknown('SIMULATED_RESPONSE_LOST')
        return row
    def find(self,intent_id):
        self._check()
        with self.store.db() as d:r=d.execute('SELECT data FROM sim_orders WHERE intent=?',(intent_id,)).fetchone()
        return json.loads(r[0]) if r else None
    def _save(self,row):
        with self.store.db() as d:d.execute('UPDATE sim_orders SET data=? WHERE id=?',(encode(row),row['order_id']))
    def cancel(self,intent_id):
        row=self.find(intent_id)
        if not row:raise OutcomeUnknown('ORDER_NOT_FOUND_IS_NOT_REJECTION')
        if row['status'] not in TERMINAL:
            if self.fill_on_cancel:self.fill(intent_id,min(row['quantity'],row['filled']+self.fill_on_cancel),100)
            row=self.find(intent_id)
            if row['status']!='FILLED':row['status']='CANCELLED';self._save(row)
        return self.find(intent_id)
    def _record_fill(self,d,row,quantity,price):
        at=self.clock()
        if at.tzinfo is None:raise Blocked('AWARE_SIM_FILL_TIME_REQUIRED')
        execution=dict(trade_id='SIM-FILL-'+uuid.uuid4().hex,order_id=row['order_id'],intent_id=row['intent_id'],
            instrument=row['instrument'],side=row['side'],quantity=quantity,price=str(price),
            filled_at=at.isoformat(),evidence_mode='SIMULATOR_GENERATED')
        d.execute('INSERT INTO sim_fills VALUES(?,?,?)',(execution['trade_id'],row['order_id'],encode(execution)))
    def fills(self):
        self._check()
        with self.store.db() as d:return [json.loads(r[0]) for r in d.execute('SELECT data FROM sim_fills ORDER BY rowid')]
    def orders(self):
        self._check()
        with self.store.db() as d:return [json.loads(r[0]) for r in d.execute('SELECT data FROM sim_orders ORDER BY rowid')]
    def fill(self,intent_id,cumulative,price):
        self._check();average=money(price)
        with self.store.db() as d:
            d.execute('BEGIN IMMEDIATE')
            found=d.execute('SELECT data FROM sim_orders WHERE intent=?',(intent_id,)).fetchone()
            row=json.loads(found[0]) if found else None
            if not row or type(cumulative) is not int or not row['filled']<=cumulative<=row['quantity']:
                raise Blocked('INVALID_SIMULATED_FILL')
            if cumulative and average<=0:raise Blocked('FILL_PRICE_MISSING')
            if row['status'] in TERMINAL and cumulative!=row['filled']:raise Blocked('SIM_ORDER_ALREADY_TERMINAL')
            if cumulative==row['filled']:
                if cumulative and money(row['average_price'])!=average:raise Blocked('SIM_FILL_PRICE_CORRECTION_REQUIRES_REVIEW')
                return
            delta=cumulative-row['filled']
            old_notional=money(row['average_price'])*row['filled'] if row['filled'] else Decimal(0)
            execution_price=(average*cumulative-old_notional)/delta
            if execution_price<=0:raise Blocked('INVALID_INCREMENTAL_SIM_FILL_PRICE')
            row.update(filled=cumulative,average_price=str(average),status='FILLED' if cumulative==row['quantity'] else 'PARTIAL')
            d.execute('UPDATE sim_orders SET data=? WHERE id=?',(encode(row),row['order_id']))
            self._record_fill(d,row,delta,execution_price)
    def positions(self):
        self._check()
        with self.store.db() as d:rows=[json.loads(r[0]) for r in d.execute('SELECT data FROM sim_orders')]
        out={}
        for r in rows:out[r['instrument']]=out.get(r['instrument'],0)+(1 if r['side']=='BUY' else -1)*r['filled']
        return out
    def external_sell(self,instrument,quantity,price):
        positive_int(quantity)
        if quantity>self.positions().get(instrument,0):raise Blocked('EXTERNAL_SELL_EXCEEDS_POSITION')
        row=dict(order_id='SIM-EXT-'+uuid.uuid4().hex,intent_id='EXTERNAL-'+uuid.uuid4().hex,
                 instrument=instrument,side='SELL',quantity=quantity,filled=quantity,
                 average_price=str(money(price)),status='FILLED',created_at=self.clock().isoformat())
        with self.store.db() as d:
            d.execute('INSERT INTO sim_orders VALUES(?,?,?)',(row['order_id'],row['intent_id'],encode(row)))
            self._record_fill(d,row,quantity,money(price))
        return row

class Service:
    def __init__(self,store,broker,clock=None,*,worker_start=True):
        if type(broker) is not SimBroker:raise Blocked('FOUNDATION_SUPPORTS_SIM_BROKER_ONLY')
        self.store=store;self.broker=broker;self.clock=clock or (lambda:datetime.now(IST))
        self.broker.clock=self.clock
        with store.lock():
            self._session()
            if os.getenv('HILEGA_PRODUCTION_WORKSPACE_MODE')=='SIMULATION_ONLY':
                from ..hilega_sim_allocation_v1 import ensure
                ensure(store,self.now())
            if worker_start:self._block('PROCESS_START_RECONCILIATION_REQUIRED')
    def now(self):
        n=self.clock()
        if n.tzinfo is None:raise Blocked('AWARE_CLOCK_REQUIRED')
        return n.astimezone(IST)
    def _session(self):
        day=self.now().date().isoformat();c=self.store.control()
        if c is None or c['session_date']!=day:
            c=dict(session_date=day,version=(c['version']+1 if c else 1),mode='PAUSED',
                   reconciled=False,last_reconciled_at=None,reason='SESSION_START_UNARMED',
                   simulation_only=True,production_execution_enabled=False)
            self.store.save_control(c);self.store.event('SESSION_START_UNARMED',self.now().isoformat(),version=c['version'])
        return c
    def _block(self,reason):
        c=self._session();c.update(mode='PAUSED',version=c['version']+1,reconciled=False,reason=reason)
        self.store.save_control(c);self.store.event('ENTRIES_BLOCKED',self.now().isoformat(),reason=reason,version=c['version'])
    def _honor_stop(self,inflight_id=None):
        state=self.store.stop_state()
        if not state['pending']:return False
        with self.store.db() as d:
            requests=[json.loads(x[0]) for x in d.execute('SELECT data FROM sim_stop_requests WHERE generation>? AND generation<=?',(state['handled'],state['generation']))]
        flatten=any(r['action']=='flatten' for r in requests)
        self._block('DURABLE_OPERATOR_FLATTEN_REQUEST' if flatten else 'DURABLE_OPERATOR_STOP_REQUEST')
        for entry in self.store.intents():
            if entry['side']=='BUY' and (flatten or entry['status'] not in TERMINAL or entry['id']==inflight_id):
                entry['cleanup']=True;self.store.put(entry)
        with self.store.db() as d:d.execute('UPDATE sim_stop_state SET handled=? WHERE id=1',(state['generation'],))
        return True
    def _check_fresh(self,c):
        if not c.get('reconciled') or not c.get('last_reconciled_at'):raise Blocked('RECONCILIATION_REQUIRED')
        age=(self.now()-datetime.fromisoformat(c['last_reconciled_at'])).total_seconds()
        if not 0<=age<=30:raise Blocked('RECONCILIATION_STALE')
    def _submit(self,row):
        # Intent committed BEFORE transport; crash leaves REQUESTED, never retry blindly.
        row.setdefault('created_at',self.now().isoformat())
        self.store.put(row);self.store.event('ORDER_INTENT_PERSISTED',self.now().isoformat(),intent_id=row['id'],side=row['side'])
        if row['side']=='BUY' and self.store.stop_state()['pending']:
            self._honor_stop()
            row.update(status='CANCELLED',not_submitted=True,cleanup=False)
            self.store.put(row);self._reconcile()
            return row
        try:
            evidence=self.broker.place(row);self._apply(row,evidence)
            if row['side']=='BUY' and self._honor_stop(inflight_id=row['id']):
                self._reconcile()
                row=next(i for i in self.store.intents() if i['id']==row['id'])
        except Exception:
            row['status']='UNKNOWN';self.store.put(row);self._block('ORDER_OUTCOME_UNKNOWN')
            # Never leak arbitrary transport exception text or claim no order exists.
            return row
        return row
    def _apply(self,row,e):
        if (e.get('intent_id')!=row['id'] or e.get('instrument')!=row['instrument'] or
            e.get('side')!=row['side'] or e.get('quantity')!=row['quantity']):raise Blocked('BROKER_IDENTITY_MISMATCH')
        filled=e.get('filled')
        if type(filled) is not int or not row.get('filled',0)<=filled<=row['quantity']:raise Blocked('FILL_REGRESSION_OR_INVALID_QUANTITY')
        if e.get('status') not in TERMINAL|{'OPEN','PARTIAL'}:raise Blocked('UNRECOGNIZED_ORDER_STATUS')
        if e['status']=='FILLED' and filled!=row['quantity']:raise Blocked('INCONSISTENT_COMPLETE_FILL')
        if filled and (e.get('average_price') is None or money(e['average_price'])<=0):raise Blocked('FILL_PRICE_MISSING')
        changed=(row.get('order_id'),row.get('filled'),row.get('average_price'),row.get('status'))!=(e['order_id'],filled,e.get('average_price'),e['status'])
        row.update(order_id=e['order_id'],filled=filled,average_price=e.get('average_price'),status=e['status'])
        self.store.put(row)
        if changed:self.store.event('ORDER_EVIDENCE_UPDATED',self.now().isoformat(),intent_id=row['id'],order_id=e['order_id'],side=row['side'],status=e['status'],filled=filled,quantity=row['quantity'],average_price=e.get('average_price'))
    def _remaining(self,entry):
        exits=[i for i in self.store.intents() if i.get('parent')==entry['id']]
        remaining=entry['filled']-sum(i['filled'] for i in exits)
        if remaining<0:raise Blocked('SELL_EXCEEDS_ENTRY')
        return remaining,exits
    def _exit(self,entry):
        if entry['status'] in {'UNKNOWN','REQUESTED'}:raise Blocked('ENTRY_OUTCOME_UNRESOLVED')
        if entry['status'] not in TERMINAL:
            e=self.broker.cancel(entry['id']);self._apply(entry,e)
        if entry['status'] not in TERMINAL:raise Blocked('ENTRY_CANCEL_NOT_TERMINAL')
        remaining,exits=self._remaining(entry)
        if any(x['status'] not in TERMINAL for x in exits):return
        if remaining==0:return
        # External activity must be reconciled BEFORE issuing a SELL.
        actual=self.broker.positions().get(entry['instrument'])
        if actual is None or actual!=remaining:raise Blocked('BROKER_POSITION_MISMATCH')
        if remaining:
            self._submit(dict(id=uuid.uuid4().hex,side='SELL',instrument=entry['instrument'],quantity=remaining,
                price=entry['price'],parent=entry['id'],status='REQUESTED',filled=0,session_date=self._session()['session_date']))
    def _reconcile(self):
        try:
            self._honor_stop()
            for row in self.store.intents():
                if row.get('not_submitted'):
                    if row['status']!='CANCELLED' or row['filled']!=0 or self.broker.find(row['id']) is not None:
                        raise Blocked('NOT_SUBMITTED_EVIDENCE_CONFLICT')
                    continue
                e=self.broker.find(row['id'])
                if e is None:raise Blocked('MISSING_ORDER_EVIDENCE')
                self._apply(row,e)
            positions=self.broker.positions()
            # Simulator's external orders are individually attributable. Production
            # requires explicit ownership reconciliation; instrument alone is insufficient.
            buys=[i for i in self.store.intents() if i['side']=='BUY']
            instruments={i['instrument'] for i in buys if not i.get('not_submitted')}
            if any(q and k not in instruments for k,q in positions.items()):raise Blocked('UNOWNED_BROKER_POSITION')
            for instrument in instruments:
                entries=[i for i in buys if i['instrument']==instrument]
                expected=sum(self._remaining(i)[0] for i in entries)
                actual=positions.get(instrument)
                if actual is None:raise Blocked('MISSING_POSITION_IS_NOT_FLAT')
                if actual!=expected:
                    # Do not guess fill attribution/P&L or manufacture a SELL execution.
                    self._block('EXTERNAL_ACTIVITY_REQUIRES_REVIEW')
                    for entry in entries:
                        if self._remaining(entry)[0] or entry.get('cleanup'):
                            entry['external_observed_quantity']=actual;self.store.put(entry)
                    return False
            for entry in buys:
                if self._session()['mode']=='PAUSED' and entry['status'] not in TERMINAL:
                    entry['cleanup']=True;self.store.put(entry)
                if entry.get('cleanup'):
                    self._exit(entry)
                    latest=next(i for i in self.store.intents() if i['id']==entry['id'])
                    left,es=self._remaining(latest)
                    if left==0 and all(i['status'] in TERMINAL for i in es) and latest['status'] in TERMINAL:
                        latest['cleanup']=False;self.store.put(latest)
            if any(i['status'] in {'UNKNOWN','REQUESTED'} for i in self.store.intents()):
                raise Blocked('ORDER_OUTCOME_UNKNOWN')
            from ..hilega_sim_allocation_v1 import reconcile as reconcile_allocation
            reconcile_allocation(self)
            c=self._session();c.update(reconciled=True,last_reconciled_at=self.now().isoformat())
            self.store.save_control(c);self.store.event('BROKER_RECONCILED',self.now().isoformat())
            return True
        except Exception:
            self._block('RECONCILIATION_REQUIRED');return False
    def command(self,action,*,request_id,expected_version,actor,position_id=None,session_date=None):
        if action not in {'pause','resume','reconcile','exit','flatten'}:raise Blocked('UNKNOWN_COMMAND')
        if not actor or len(actor)>100:raise Blocked('ACTOR_REQUIRED')
        payload=dict(action=action,expected_version=expected_version,actor=actor,position_id=position_id,session_date=session_date)
        # Stop intent is durable before waiting for an in-flight submission.
        if action in {'pause','flatten'}:self.store.queue_stop(request_id,payload)
        with self.store.lock():
            self._honor_stop()
            c=self._session();prior,fp=self.store.previous(request_id,payload)
            if prior:return dict(prior,idempotent_replay=True,current_status=self._status())
            # Pause/flatten are monotonic safety commands: stale browser may still stop.
            if action in {'resume','exit'} and (expected_version!=c['version'] or session_date!=c['session_date']):
                raise Blocked('STALE_STATE_OR_SESSION_REFRESH_REQUIRED')
            if action in {'pause','flatten'}:
                self._block('OPERATOR_PAUSE')
                for entry in self.store.intents():
                    if entry['side']=='BUY' and (action=='flatten' or entry['status'] not in TERMINAL):
                        entry['cleanup']=True;self.store.put(entry)
                self._reconcile()
            elif action=='reconcile':self._reconcile()
            elif action=='resume':
                if self.store.stop_state()['pending']:raise Blocked('DURABLE_STOP_PENDING')
                self._check_bridge_health()
                from ..hilega_sim_allocation_v1 import require_ready
                require_ready(self.store,self.now())
                self._check_fresh(c)
                if any(i.get('cleanup') or i['status'] not in TERMINAL or 'external_observed_quantity' in i for i in self.store.intents()):
                    raise Blocked('UNRESOLVED_EXECUTION_STATE')
                c.update(mode='ARMED',version=c['version']+1,reason='NEXT_FRESH_SIGNAL_ONLY',resumed_at=self.now().isoformat())
                self.store.save_control(c)
            elif action=='exit':
                self._block('MANUAL_EXIT_REQUIRES_EXPLICIT_RESUME')
                entries=[i for i in self.store.intents() if i['id']==position_id and i['side']=='BUY']
                if len(entries)!=1:raise Blocked('POSITION_NOT_FOUND')
                entries[0]['cleanup']=True;self.store.put(entries[0]);self._reconcile()
            result=dict(request_id=request_id,action=action,status=self._status())
            self.store.event('CONTROL_COMMAND',self.now().isoformat(),actor=actor,request_id=request_id,action=action,version=result['status']['control']['version'])
            self.store.remember(request_id,fp,result);return result
    def submit_entry(self,*,signal_id,signal_at,instrument,quantity,price,bridge_run_id=None):
        positive_int(quantity)
        if not instrument or not isinstance(signal_id,str) or not signal_id:raise Blocked('SIGNAL_AND_INSTRUMENT_REQUIRED')
        amount=money(price)
        if amount<=0:raise Blocked('PRICE_MUST_BE_POSITIVE')
        signal=datetime.fromisoformat(signal_at)
        if signal.tzinfo is None:raise Blocked('AWARE_SIGNAL_TIME_REQUIRED')
        with self.store.lock():
            c=self._session();sid=hashlib.sha256((c['session_date']+'|'+signal_id).encode()).hexdigest()
            if any(i['id']==sid for i in self.store.intents()):raise Blocked('SIGNAL_ALREADY_CONSUMED')
            if c['mode']!='ARMED' or self.store.stop_state()['pending']:
                self.store.event('ENTRY_BLOCKED',self.now().isoformat(),signal_id=signal_id,reason='TRADING_PAUSED')
                raise Blocked('TRADING_PAUSED')
            self._check_bridge_health(run_id=bridge_run_id,submitting=True)
            self._check_fresh(c)
            if 'resumed_at' not in c or signal<=datetime.fromisoformat(c['resumed_at']):
                raise Blocked('PRE_RESUME_SIGNAL_NOT_ELIGIBLE')
            age=(self.now()-signal).total_seconds()
            if not 0<=age<=60:raise Blocked('SIGNAL_STALE_OR_FUTURE')
            for row in self.store.intents():
                if row['status'] not in TERMINAL or row.get('cleanup') or 'external_observed_quantity' in row:raise Blocked('EXPOSURE_OR_ORDER_UNRESOLVED')
                if row['side']=='BUY' and self._remaining(row)[0]:raise Blocked('POSITION_ALREADY_OPEN')
            # Allocation is durably held before the first simulator BUY transport call.
            from ..hilega_sim_allocation_v1 import reserve
            intent=dict(id=sid,signal_id=signal_id,signal_at=signal_at,side='BUY',instrument=instrument,
                quantity=quantity,price=str(amount),filled=0,status='REQUESTED',session_date=c['session_date'],created_at=self.now().isoformat())
            reserve(self,sid,instrument=instrument,quantity=quantity,price=amount,intent=intent)
            return self._submit(intent)
    def strategy_exit(self,*,position_id,exit_id,price):
        """Simulator-only strategy exit. Does not arm/resume or invoke manual pause."""
        amount=money(price)
        if amount<=0 or not isinstance(exit_id,str) or not exit_id:raise Blocked('VALID_EXIT_ID_AND_PRICE_REQUIRED')
        with self.store.lock():
            self._session()
            if not self._reconcile():raise Blocked('STRATEGY_EXIT_RECONCILIATION_REQUIRED')
            entries=[i for i in self.store.intents() if i['id']==position_id and i['side']=='BUY']
            if len(entries)!=1:raise Blocked('POSITION_NOT_FOUND')
            entry=entries[0]
            try:
                if entry['status'] not in TERMINAL:
                    self._apply(entry,self.broker.cancel(entry['id']))
                if entry['status'] not in TERMINAL:raise Blocked('ENTRY_CANCEL_NOT_TERMINAL')
                remaining,exits=self._remaining(entry)
                if any(i['status'] not in TERMINAL for i in exits):return dict(status='EXIT_PENDING',remaining=remaining)
                if remaining==0:return dict(status='FLAT_CONFIRMED',remaining=0)
                if self.broker.positions().get(entry['instrument'])!=remaining:raise Blocked('BROKER_POSITION_MISMATCH')
                if any(i['id']==exit_id for i in self.store.intents()):raise Blocked('EXIT_ALREADY_CONSUMED_NO_RESUBMISSION')
                self._submit(dict(id=exit_id,side='SELL',instrument=entry['instrument'],quantity=remaining,
                    price=str(amount),parent=entry['id'],status='REQUESTED',filled=0,session_date=self._session()['session_date']))
                if not self._reconcile():raise Blocked('EXIT_OUTCOME_UNCONFIRMED')
                entry=next(i for i in self.store.intents() if i['id']==position_id)
                remaining,exits=self._remaining(entry)
                return dict(status='FLAT_CONFIRMED' if remaining==0 and all(i['status'] in TERMINAL for i in exits) else 'EXIT_PENDING',remaining=remaining)
            except Exception:
                self._block('STRATEGY_EXIT_OUTCOME_UNCONFIRMED')
                raise Blocked('STRATEGY_EXIT_OUTCOME_UNCONFIRMED') from None
    def _check_bridge_health(self,*,run_id=None,submitting=False):
        from ..hilega_production_bridge_health_v1 import assert_ready,HealthBlocked
        try:assert_ready(self.store,self.now(),run_id=run_id,submitting=submitting)
        except HealthBlocked as exc:
            if self._session()['mode']=='ARMED':
                self._block(str(exc));self._reconcile()
            raise Blocked(str(exc)) from None
    def _watch_bridge_locked(self):
        from ..hilega_production_bridge_health_v1 import summary
        health=summary(self.store,self.now())
        if health['required'] and not health['healthy'] and self._session()['mode']=='ARMED':
            self._block('SIM_BRIDGE_'+health['status']);self._reconcile()
        return health
    def watch_bridge_health(self):
        with self.store.lock():return self._watch_bridge_locked()
    def _status(self):
        c=self._session();rows=self.store.intents()
        from ..hilega_production_bridge_health_v1 import summary
        health=summary(self.store,self.now())
        uncertainty=any(i['status'] in {'UNKNOWN','REQUESTED'} or 'external_observed_quantity' in i for i in rows)
        cleanup=any(i.get('cleanup') for i in rows)
        pending=any(i['side']=='BUY' and i['status'] not in TERMINAL for i in rows)
        exposure=sum(self._remaining(i)[0] for i in rows if i['side']=='BUY')
        stamp=c.get('last_reconciled_at')
        stale=stamp is None or not 0<=(self.now()-datetime.fromisoformat(stamp)).total_seconds()<=30
        label=('BLOCKED_RECONCILIATION_REQUIRED' if not c['reconciled'] or uncertainty else
               'BLOCKED_RECONCILIATION_STALE' if stale else
               'STOPPING_CANCEL_OR_FLATTEN_PENDING' if cleanup else
               'PAUSED_PENDING_ENTRY_REQUIRES_CANCEL' if pending and c['mode']=='PAUSED' else
               'ARMED_SIMULATION_NEXT_SIGNAL' if c['mode']=='ARMED' else
               'PAUSED_EXISTING_POSITION_OPEN' if exposure else 'PAUSED_NO_PENDING_ENTRIES')
        if health['required'] and not health['healthy']:label='BLOCKED_'+health['status']
        from ..hilega_sim_allocation_v1 import summary as allocation_summary
        allocation=allocation_summary(self.store,self.now())
        if allocation['required'] and not allocation['ready'] and health.get('healthy',True):label='BLOCKED_'+allocation['status']
        stop=self.store.stop_state()
        if stop['pending']:label='STOP_REQUESTED_WAITING_FOR_CLEANUP'
        return dict(control=c,label=label,bridge_health=health,allocation=allocation,
                    durable_execution=dict(model='HILEGA_DURABLE_SIM_INTEGRATION_V1',stop_requested=stop['pending'],stop_generation=stop['generation'],handled_generation=stop['handled'],atomic_reservation_intent=True,production_execution_enabled=False),pending_entry_orders=pending,ledger_remaining_quantity=exposure,
                    positions=rows,production_execution_enabled=False,simulator_only=True,
                    notice='Simulation ledger only. Not connected to live strategy, UI or Upstox.')
    def status(self):
        with self.store.lock():return self._status()


def plan(config, contracts, available_cash):
    """Offline arithmetic only; caller must supply validated current instrument/quote evidence."""
    offsets=config['strike_offsets'];lots=positive_int(config['lots_per_strike'])
    if not isinstance(offsets,list) or not 1<=len(offsets)<=5 or len(set(offsets))!=len(offsets) or any(type(x)is not int or x not in range(-2,3) for x in offsets):
        raise Blocked('INVALID_STRIKE_OFFSETS')
    if money(config['allocation_fraction'])!=Decimal('.5'):raise Blocked('INITIAL_ALLOCATION_MUST_BE_50_PERCENT')
    if len(contracts)!=len(offsets):raise Blocked('CONTRACT_COUNT_MISMATCH')
    if len({x['instrument'] for x in contracts})!=len(contracts):raise Blocked('DUPLICATE_CONTRACT')
    if {x['offset'] for x in contracts}!=set(offsets):raise Blocked('CONTRACT_OFFSETS_MISMATCH')
    budget=money(available_cash)*Decimal('.5');total=Decimal(0);legs=[]
    for row in contracts:
        quantity=positive_int(row['lot_size'])*lots
        if money(row['price'])<=0:raise Blocked('PRICE_MUST_BE_POSITIVE')
        estimate=money(row['price'])*quantity+money(row.get('estimated_charges',0))+money(row.get('buffer',0))
        total+=estimate;legs.append(dict(offset=row['offset'],instrument=row['instrument'],quantity=quantity,estimated_cost=str(estimate)))
    return dict(simulation_only=True,eligible=total<=budget and total>0,cap=str(budget),estimated_total=str(total),legs=legs,
                production_eligible=False,daily_loss_limit=config.get('daily_loss_limit'),
                limitations=['FUNDS_FIELD_MAPPING_NOT_VERIFIED','EXPOSURE_RESERVATION_NOT_IMPLEMENTED','NO_PRODUCTION_TRANSPORT'])
