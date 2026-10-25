"""Offline-only durable execution controller. No network or production transport."""
import fcntl
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

class Blocked(ValueError): pass
TERMINAL = {'FILLED', 'CANCELLED', 'REJECTED'}

def enc(v): return json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False)
def time_(v):
    t = datetime.fromisoformat(v)
    if t.tzinfo is None: raise Blocked('AWARE_TIME_REQUIRED')
    return t

def cash_cents(value):
    if isinstance(value, bool): raise Blocked('INVALID_AMOUNT')
    try: d = Decimal(str(value))
    except (InvalidOperation, ValueError): raise Blocked('INVALID_AMOUNT') from None
    if not d.is_finite() or d < 0 or d * 100 != (d * 100).to_integral_value(): raise Blocked('INVALID_AMOUNT')
    return int(d * 100)

def identity(v):
    if not isinstance(v,str) or not 1 <= len(v) <= 120 or any(ord(c)<32 for c in v): raise Blocked('INVALID_IDENTITY')
    return v

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600); os.close(fd)
        with self.tx() as d:
            d.executescript('''
              CREATE TABLE IF NOT EXISTS control(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS pause_request(id INTEGER PRIMARY KEY, generation INTEGER NOT NULL);
              INSERT OR IGNORE INTO pause_request VALUES(1,0);
              CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS venue_orders(id TEXT PRIMARY KEY, ref TEXT UNIQUE NOT NULL, data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS venue_fills(id TEXT PRIMARY KEY, data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS metadata(id INTEGER PRIMARY KEY, data TEXT NOT NULL);
            ''')
    @contextmanager
    def tx(self):
        d = sqlite3.connect(self.path, timeout=15)
        d.execute('PRAGMA synchronous=FULL'); d.execute('BEGIN IMMEDIATE')
        try: yield d; d.commit()
        except BaseException: d.rollback(); raise
        finally: d.close()
    @contextmanager
    def gate(self):
        fd=os.open(str(self.path)+'.controller.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'a') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(f,fcntl.LOCK_UN)
    def rows(self,d,table):
        if table not in {'plans','venue_orders','venue_fills','events'}: raise Blocked('TABLE_NOT_ALLOWED')
        return [json.loads(r[0]) for r in d.execute('SELECT data FROM '+table+' ORDER BY rowid')]
    def put(self,d,row): d.execute('INSERT OR REPLACE INTO plans VALUES(?,?)',(row['id'],enc(row)))
    def event(self,d,kind,**kw): d.execute('INSERT INTO events(data) VALUES(?)',(enc(dict(type=kind,**kw)),))

class FixtureVenue:
    """Exact local fixture; no injectable real transport. Order acceptance is separate."""
    def __init__(self,store): self.store=store
    def place(self,plan):
        with self.store.tx() as d:
            row=dict(id='FIXTURE-'+uuid.uuid4().hex,ref=plan['id'],side=plan['side'],quantity=plan['quantity'],filled=0,status='OPEN',instrument=plan['instrument'])
            d.execute('INSERT INTO venue_orders VALUES(?,?,?)',(row['id'],row['ref'],enc(row)))
        return row['id']
    def fill(self,oid,cumulative,price='100'):
        cents=cash_cents(price)
        if cents<=0: raise Blocked('POSITIVE_PRICE_REQUIRED')
        with self.store.tx() as d:
            found=d.execute('SELECT data FROM venue_orders WHERE id=?',(oid,)).fetchone()
            if not found: raise Blocked('ORDER_NOT_FOUND')
            row=json.loads(found[0]);old=row['filled']
            if type(cumulative)is not int or not old<=cumulative<=row['quantity']: raise Blocked('INVALID_FILL_QUANTITY')
            if cumulative==old:return
            if row['status'] in TERMINAL: raise Blocked('TERMINAL_ORDER')
            fill=dict(id=uuid.uuid4().hex,order_id=oid,quantity=cumulative-old,price_cents=cents,side=row['side'],instrument=row['instrument'])
            row.update(filled=cumulative,status='FILLED' if cumulative==row['quantity'] else 'PARTIAL')
            d.execute('UPDATE venue_orders SET data=? WHERE id=?',(enc(row),oid))
            d.execute('INSERT INTO venue_fills VALUES(?,?)',(fill['id'],enc(fill)))
    def cancel(self,oid):
        with self.store.tx() as d:
            found=d.execute('SELECT data FROM venue_orders WHERE id=?',(oid,)).fetchone()
            if not found: raise Blocked('ORDER_NOT_FOUND')
            row=json.loads(found[0])
            if row['status'] not in TERMINAL:
                row['status']='CANCELLED';d.execute('UPDATE venue_orders SET data=? WHERE id=?',(enc(row),oid))

class Controller:
    def __init__(self,path,*,session_date,clock):
        # An offline fixture scope is pinned into this DB. There is no LIVE mode.
        self.store=Store(path);self.clock=clock;self.session=session_date
        self.venue=FixtureVenue(self.store);self.checkpoint=lambda stage:None
        with self.store.tx() as d:
            meta=d.execute('SELECT data FROM metadata WHERE id=1').fetchone()
            expected=dict(scope='OFFLINE_FIXTURE_ONLY',session_date=session_date)
            if meta and json.loads(meta[0])!=expected: raise Blocked('SESSION_OR_SCOPE_MISMATCH')
            d.execute('INSERT OR IGNORE INTO metadata VALUES(1,?)',(enc(expected),))
            d.execute('INSERT OR IGNORE INTO control VALUES(1,?)',(enc(dict(mode='PAUSED',version=1,reason='NEW_INSTALL',cash_cents=None,funds_at=None,resumed_at=None,seen_pause=0)),))
    def now(self):
        t=self.clock();time_(t.isoformat())
        if t.date().isoformat()!=self.session: raise Blocked('SESSION_CHANGED_REQUIRES_NEW_STORE')
        return t
    def _control(self,d): return json.loads(d.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
    def _save(self,d,c): d.execute('UPDATE control SET data=? WHERE id=1',(enc(c),))
    def _generation(self,d): return d.execute('SELECT generation FROM pause_request WHERE id=1').fetchone()[0]
    def _pause(self,d,reason):
        c=self._control(d);c.update(mode='PAUSED',version=c['version']+1,reason=reason,seen_pause=self._generation(d));self._save(d,c)
        self.store.event(d,'PAUSED',reason=reason,version=c['version'])
    def _assert_armed(self,d,version):
        c=self._control(d)
        if c['version']!=version: raise Blocked('STALE_CONTROL_VERSION')
        if c['mode']!='ARMED' or c['seen_pause']!=self._generation(d): raise Blocked('PAUSED_OR_PAUSE_REQUESTED')
        return c
    def funds(self,value):
        with self.store.gate(),self.store.tx() as d:
            c=self._control(d);c.update(cash_cents=cash_cents(value),funds_at=self.now().isoformat());self._save(d,c)
    def _funds_valid(self,c):
        if c['cash_cents'] is None or c['funds_at'] is None or not 0<=(self.now()-time_(c['funds_at'])).total_seconds()<=30: raise Blocked('FUNDS_STALE_OR_MISSING')
    def resume(self,request_id,expected_version):
        identity(request_id);fingerprint=enc(['RESUME',expected_version,self.session])
        with self.store.gate():
            self._reconcile()
            with self.store.tx() as d:
                prior=d.execute('SELECT fingerprint,result FROM commands WHERE id=?',(request_id,)).fetchone()
                if prior:
                    if prior[0]!=fingerprint: raise Blocked('COMMAND_ID_CONFLICT')
                    return json.loads(prior[1])
                c=self._control(d)
                if c['version']!=expected_version: raise Blocked('STALE_CONTROL_VERSION')
                if c['seen_pause']!=self._generation(d): raise Blocked('PAUSE_REQUEST_NOT_COMPLETED')
                self._funds_valid(c)
                plans=self.store.rows(d,'plans')
                if any(p['state'] not in TERMINAL or p['side']=='BUY' and p['held_cents']>0 for p in plans): raise Blocked('EXPOSURE_OR_RECOVERY_REVIEW')
                c.update(mode='ARMED',version=c['version']+1,resumed_at=self.now().isoformat(),reason='OPERATOR_RESUME');self._save(d,c)
                result=dict(version=c['version'],mode=c['mode'])
                d.execute('INSERT INTO commands VALUES(?,?,?)',(request_id,fingerprint,enc(result)));return result
    def entry(self,request_id,*,expected_version,signal_at,instrument='NSE_FO|12345',quantity=65,ask='100',buffer='100'):
        identity(request_id);identity(instrument)
        if type(quantity)is not int or quantity!=65: raise Blocked('OFFLINE_SINGLE_LOT_65_ONLY')
        price=cash_cents(ask);reserve=price*quantity+cash_cents(buffer)
        if price<=0: raise Blocked('POSITIVE_ASK_REQUIRED')
        payload=dict(signal_at=signal_at,instrument=instrument,quantity=quantity,ask_cents=price,reserve_cents=reserve)
        with self.store.gate():
            with self.store.tx() as d:
                old=d.execute('SELECT data FROM plans WHERE id=?',(request_id,)).fetchone()
                if old:
                    row=json.loads(old[0])
                    if row.get('payload')!=payload: raise Blocked('REQUEST_ID_CONFLICT')
                    return row # durable consumption: never dispatch again
                c=self._assert_armed(d,expected_version);self._funds_valid(c)
                t=time_(signal_at)
                if t<=time_(c['resumed_at']) or not 0<=(self.now()-t).total_seconds()<=60: raise Blocked('SIGNAL_NOT_FRESH_AFTER_RESUME')
                plans=self.store.rows(d,'plans')
                if any(p['state'] not in TERMINAL or p['side']=='BUY' and p['held_cents']>0 for p in plans): raise Blocked('EXPOSURE_OR_RECOVERY_REVIEW')
                if reserve>c['cash_cents']//2: raise Blocked('HALF_CASH_CAP_EXCEEDED')
                row=dict(id=request_id,side='BUY',parent=None,instrument=instrument,quantity=quantity,filled=0,state='PREPARED',order_id=None,held_cents=reserve,payload=payload)
                self.store.put(d,row);self.store.event(d,'RESERVATION_AND_INTENT_COMMITTED',request_id=request_id,held_cents=reserve)
                self.checkpoint('IN_PREPARE_TRANSACTION')
            self.checkpoint('AFTER_PREPARE_COMMIT')
            return self._dispatch(row)
    def _dispatch(self,row):
        with self.store.tx() as d:
            c=self._control(d)
            if row['side']=='BUY' and (c['mode']!='ARMED' or c['seen_pause']!=self._generation(d)):
                row.update(state='CANCELLED',held_cents=0);self.store.put(d,row);return row
            row['state']='IN_FLIGHT';self.store.put(d,row)
        self.checkpoint('AFTER_IN_FLIGHT_COMMIT')
        # The submission boundary is serialized by the controller gate. Pause
        # can already persist its request; any accepted pending order is cleaned.
        with self.store.tx() as d:
            c=self._control(d)
            if row['side']=='BUY' and c['seen_pause']!=self._generation(d):
                row.update(state='CANCELLED',held_cents=0);self.store.put(d,row);return row
        oid=self.venue.place(row)
        self.checkpoint('AFTER_FIXTURE_ACCEPT_BEFORE_ACK')
        with self.store.tx() as d:
            row.update(order_id=oid,state='ACKNOWLEDGED');self.store.put(d,row)
        self.checkpoint('AFTER_ACK_COMMIT')
        self._reconcile()
        with self.store.tx() as d: pending=self._control(d)['seen_pause']!=self._generation(d)
        if pending:self._finish_pause()
        return next(p for p in self.status()['plans'] if p['id']==row['id'])
    def request_pause(self):
        # Persist before waiting for a submission lock; status becomes blocked.
        with self.store.tx() as d:
            d.execute('UPDATE pause_request SET generation=generation+1 WHERE id=1')
            self.store.event(d,'PAUSE_REQUEST_DURABLE',generation=self._generation(d))
    def pause(self):
        self.request_pause()
        with self.store.gate(): self._finish_pause()
        return self.status()
    def _finish_pause(self):
        with self.store.tx() as d:
            self._pause(d,'OPERATOR_PAUSE')
            pending=[p['id'] for p in self.store.rows(d,'plans') if p['side']=='BUY' and p['state'] not in TERMINAL]
        # Pending-at-Pause fills are cleaned; established FILLED positions stay.
        for key in pending: self._exit(key)
        self._reconcile()
    def exit(self,entry_id):
        identity(entry_id);self.request_pause()
        with self.store.gate():
            with self.store.tx() as d:self._pause(d,'MANUAL_EXIT')
            return self._exit(entry_id)
    def _exit(self,entry_id):
        self._reconcile()
        with self.store.tx() as d:
            plans=self.store.rows(d,'plans');entry=next((p for p in plans if p['id']==entry_id and p['side']=='BUY'),None)
        if not entry: raise Blocked('OWNED_ENTRY_NOT_FOUND')
        if not entry['order_id'] and entry['state']=='PREPARED':
            with self.store.tx() as d:
                entry.update(state='CANCELLED',held_cents=0);self.store.put(d,entry)
            return entry # durable state proves dispatch was never begun
        if not entry['order_id']: raise Blocked('ACCEPTANCE_UNKNOWN_NO_RESUBMISSION')
        if entry['state'] not in TERMINAL:self.venue.cancel(entry['order_id']);self._reconcile()
        with self.store.tx() as d:
            plans=self.store.rows(d,'plans');entry=next(p for p in plans if p['id']==entry_id)
            previous=next((p for p in plans if p['parent']==entry_id),None)
            if previous:return previous # no replacement SELL, even if cancelled
            remaining=entry['filled']
            if not remaining:return entry
            row=dict(id='EXIT-'+entry_id,side='SELL',parent=entry_id,instrument=entry['instrument'],quantity=remaining,filled=0,state='PREPARED',order_id=None,held_cents=0)
            self.store.put(d,row);self.store.event(d,'EXIT_INTENT_COMMITTED',request_id=row['id'])
        return self._dispatch(row)
    def _reconcile(self):
        with self.store.tx() as d:
            orders=self.store.rows(d,'venue_orders');fills=self.store.rows(d,'venue_fills');plans=self.store.rows(d,'plans')
            by_ref={o['ref']:o for o in orders}
            if set(by_ref)-{p['id'] for p in plans}: self._pause(d,'UNMAPPED_FIXTURE_ACTIVITY');return False
            for p in plans:
                o=by_ref.get(p['id'])
                if not o:
                    if p['state'] in {'IN_FLIGHT','UNKNOWN','ACKNOWLEDGED','OPEN','PARTIAL','FILLED'}:
                        p['state']='UNKNOWN';self.store.put(d,p);self._pause(d,'ACCEPTANCE_UNKNOWN_NO_RESUBMISSION')
                    continue
                if p['order_id'] and p['order_id']!=o['id']:raise Blocked('ORDER_BINDING_CHANGED')
                if any(p[k]!=o[k] for k in ('side','quantity','instrument')):raise Blocked('ORDER_IDENTITY_MISMATCH')
                executions=[f for f in fills if f['order_id']==o['id']]
                if sum(f['quantity'] for f in executions)!=o['filled'] or o['filled']<p['filled']:raise Blocked('FILL_EVIDENCE_MISMATCH')
                p.update(order_id=o['id'],filled=o['filled'],state=o['status']);self.store.put(d,p)
            for p in plans:
                if p['side']!='BUY':continue
                exits=[x for x in plans if x['parent']==p['id']]
                remaining=p['filled']-sum(x['filled'] for x in exits)
                if remaining<0:raise Blocked('OVERSELL')
                if p['state'] in TERMINAL and all(x['state'] in TERMINAL for x in exits) and remaining==0 and p['held_cents']:
                    p['held_cents']=0;self.store.put(d,p);self.store.event(d,'TERMINAL_FLAT_RELEASE',request_id=p['id'])
                    self.checkpoint('BEFORE_FLAT_RELEASE_COMMIT')
            return True
    def reconcile(self):
        with self.store.gate():
            try:return self._reconcile()
            except Exception:
                with self.store.tx() as d:self._pause(d,'RECONCILIATION_FAILED')
                raise
    def recover(self):
        with self.store.gate():
            with self.store.tx() as d:self._pause(d,'RESTART_REQUIRES_REVIEW')
            self._reconcile()
        return self.status()
    def status(self):
        with self.store.tx() as d:
            c=self._control(d);plans=self.store.rows(d,'plans');pending=c['seen_pause']!=self._generation(d)
            return dict(control=c,pause_requested=pending,entry_permission=False,effective_fixture_entry_armed=c['mode']=='ARMED' and not pending,
                plans=plans,held_cents=sum(p['held_cents'] for p in plans),events=self.store.rows(d,'events'),
                fixture_orders=self.store.rows(d,'venue_orders'),production_execution_enabled=False,orders_sent_to_upstox=False,evidence_mode='OFFLINE_FIXTURE_ONLY')
