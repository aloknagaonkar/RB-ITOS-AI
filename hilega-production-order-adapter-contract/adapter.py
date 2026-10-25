"""Offline order-adapter contract. Exact FakeTransport only; no network imports."""
import fcntl,hashlib,json,os,sqlite3,uuid
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal,InvalidOperation
from pathlib import Path

TERMINAL={'FILLED','CANCELLED','REJECTED'}
class Blocked(ValueError):pass
class TransportTimeout(RuntimeError):pass

def encode(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def price(v):
    if isinstance(v,bool):raise Blocked('INVALID_PRICE')
    try:d=Decimal(str(v))
    except (InvalidOperation,ValueError):raise Blocked('INVALID_PRICE') from None
    if not d.is_finite() or d<=0:raise Blocked('INVALID_PRICE')
    return d

def aware(v):
    try:t=datetime.fromisoformat(v)
    except (TypeError,ValueError):raise Blocked('INVALID_TIME') from None
    if t.tzinfo is None:raise Blocked('AWARE_TIME_REQUIRED')
    return t

def qty(v):
    if type(v)is not int or v<=0:raise Blocked('POSITIVE_INTEGER_QUANTITY_REQUIRED')
    return v

class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);os.close(fd)
        with self.db() as d:d.executescript('''
          CREATE TABLE IF NOT EXISTS meta(id INTEGER PRIMARY KEY,data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS intents(id TEXT PRIMARY KEY,data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS fake_orders(id TEXT PRIMARY KEY,data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS fake_fills(id TEXT PRIMARY KEY,data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS snapshots(generation INTEGER PRIMARY KEY,fingerprint TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS seen_fills(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS fake_meta(id INTEGER PRIMARY KEY, generation INTEGER NOT NULL);
          INSERT OR IGNORE INTO fake_meta VALUES(1,0);''')
    @contextmanager
    def db(self):
        d=sqlite3.connect(self.path,timeout=15);d.execute('PRAGMA synchronous=FULL')
        try:yield d;d.commit()
        except BaseException:d.rollback();raise
        finally:d.close()
    @contextmanager
    def lock(self):
        fd=os.open(str(self.path)+'.adapter.lock',os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,'a') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(f,fcntl.LOCK_UN)
    def rows(self,table):
        if table not in {'intents','fake_orders','fake_fills','audit'}:raise Blocked('TABLE_NOT_ALLOWED')
        with self.db() as d:return [json.loads(x[0]) for x in d.execute('SELECT data FROM '+table+' ORDER BY rowid')]
    def put(self,row):
        with self.db() as d:d.execute('INSERT OR REPLACE INTO intents VALUES(?,?)',(row['request_id'],encode(row)))
    def event(self,kind,**fields):
        with self.db() as d:d.execute('INSERT INTO audit(data) VALUES(?)',(encode(dict(type=kind,**fields)),))

class FakeTransport:
    """Durable synthetic venue. Fault flags are explicit offline injection."""
    def __init__(self,store,clock):
        self.store=store;self.clock=clock;self.timeout_after_accept=False;self.timeout_before_accept=False
        self.reject_next=False;self.cancel_timeout=False;self.unavailable=False;self.auto_sell_fill=True;self.fill_on_cancel=0;self.before_place=None
    def _check(self):
        if self.unavailable:raise TransportTimeout('FAKE_UNAVAILABLE')
    def _generation(self,d):d.execute('UPDATE fake_meta SET generation=generation+1 WHERE id=1')
    def place(self,intent):
        self._check()
        if self.before_place:self.before_place(intent)
        if self.timeout_before_accept:
            self.timeout_before_accept=False;raise TransportTimeout('FAKE_NO_ACCEPTANCE_RESPONSE')
        if any(o['client_reference']==intent['request_id'] for o in self.store.rows('fake_orders')):raise Blocked('FAKE_DUPLICATE_POST')
        row=dict(order_id='FAKE-'+uuid.uuid4().hex,client_reference=intent['request_id'],account_scope='OFFLINE_ACCOUNT',
            instrument=intent['instrument'],product=intent['product'],side=intent['side'],quantity=intent['quantity'],
            filled=0,pending=intent['quantity'],status='OPEN')
        if self.reject_next:
            self.reject_next=False;row.update(status='REJECTED',pending=0)
        with self.store.db() as d:
            d.execute('INSERT INTO fake_orders VALUES(?,?)',(row['order_id'],encode(row)));self._generation(d)
        if row['side']=='SELL' and self.auto_sell_fill and row['status']!='REJECTED':self.fill(row['order_id'],row['quantity'],intent['price'])
        if self.timeout_after_accept:
            self.timeout_after_accept=False;raise TransportTimeout('FAKE_ACCEPTED_RESPONSE_LOST')
        return dict(order_id=row['order_id'])
    def fill(self,order_id,cumulative,average):
        self._check();average=price(average)
        with self.store.db() as d:
            d.execute('BEGIN IMMEDIATE');r=d.execute('SELECT data FROM fake_orders WHERE id=?',(order_id,)).fetchone()
            if not r:raise Blocked('ORDER_NOT_FOUND')
            o=json.loads(r[0]);old=o['filled']
            if type(cumulative)is not int or not old<=cumulative<=o['quantity']:raise Blocked('INVALID_CUMULATIVE_FILL')
            if cumulative==old:return
            if o['status'] in TERMINAL:raise Blocked('TERMINAL_ORDER_FILL_CHANGE')
            previous=sum(Decimal(x['price'])*x['quantity'] for x in self.store.rows('fake_fills') if x['order_id']==order_id)
            incremental=(average*cumulative-previous)/(cumulative-old)
            if incremental<=0:raise Blocked('INVALID_EXECUTION_PRICE')
            f=dict(trade_id='FILL-'+uuid.uuid4().hex,order_id=order_id,instrument=o['instrument'],product=o['product'],side=o['side'],quantity=cumulative-old,price=str(incremental))
            o.update(filled=cumulative,pending=o['quantity']-cumulative,status='FILLED' if cumulative==o['quantity'] else 'PARTIAL')
            d.execute('UPDATE fake_orders SET data=? WHERE id=?',(encode(o),order_id))
            d.execute('INSERT INTO fake_fills VALUES(?,?)',(f['trade_id'],encode(f)));self._generation(d)
    def cancel(self,order_id):
        self._check();o=next(x for x in self.store.rows('fake_orders') if x['order_id']==order_id)
        if o['status'] not in TERMINAL:
            if self.fill_on_cancel:self.fill(order_id,min(o['quantity'],o['filled']+self.fill_on_cancel),'100')
            o=next(x for x in self.store.rows('fake_orders') if x['order_id']==order_id)
            if o['status']!='FILLED':
                o.update(status='CANCELLED',pending=0)
                with self.store.db() as d:d.execute('UPDATE fake_orders SET data=? WHERE id=?',(encode(o),order_id));self._generation(d)
        if self.cancel_timeout:raise TransportTimeout('FAKE_CANCEL_ACK_LOST')
    def snapshot(self):
        self._check();orders=self.store.rows('fake_orders');fills=self.store.rows('fake_fills');positions={}
        for o in orders:
            k=(o['instrument'],o['product']);positions[k]=positions.get(k,0)+(o['filled'] if o['side']=='BUY' else -o['filled'])
        with self.store.db() as d:g=d.execute('SELECT generation FROM fake_meta WHERE id=1').fetchone()[0]
        return dict(evidence_mode='OFFLINE_FAKE_TRANSPORT',account_scope='OFFLINE_ACCOUNT',complete=True,generation=g,
            observed_at=self.clock().isoformat(),orders=orders,fills=fills,
            positions=[dict(instrument=k[0],product=k[1],quantity=v) for k,v in positions.items()])

class Adapter:
    def __init__(self,store,transport,clock):
        if type(transport)is not FakeTransport or transport.store.path.resolve()!=store.path.resolve():raise Blocked('EXACT_OFFLINE_FAKE_TRANSPORT_REQUIRED')
        self.store=store;self.transport=transport;self.clock=clock
        with store.lock():self._pause('ADAPTER_START_REQUIRES_EXPLICIT_RESUME')
    def _control(self):
        with self.store.db() as d:r=d.execute('SELECT data FROM meta WHERE id=1').fetchone()
        return json.loads(r[0]) if r else dict(mode='PAUSED',version=0)
    def _pause(self,reason):
        c=self._control();c.update(mode='PAUSED',version=c['version']+1,reason=reason)
        with self.store.db() as d:d.execute('INSERT OR REPLACE INTO meta VALUES(1,?)',(encode(c),))
        self.store.event('ENTRIES_PAUSED',reason=reason,version=c['version'])
    def _position(self,entry):
        return entry.get('filled',0)-sum(x.get('filled',0) for x in self.store.rows('intents') if x.get('parent')==entry['request_id'])
    def _reconcile(self,snap=None):
        snap=snap if snap is not None else self.transport.snapshot();now=aware(self.clock().isoformat())
        if snap.get('evidence_mode')!='OFFLINE_FAKE_TRANSPORT' or snap.get('account_scope')!='OFFLINE_ACCOUNT' or snap.get('complete') is not True:raise Blocked('SNAPSHOT_SCOPE_OR_COMPLETENESS')
        if not 0<=(now-aware(snap['observed_at'])).total_seconds()<=30:raise Blocked('SNAPSHOT_STALE_OR_FUTURE')
        generation=snap.get('generation')
        if type(generation)is not int or generation<0:raise Blocked('INVALID_GENERATION')
        body={k:v for k,v in snap.items() if k!='observed_at'};fp=hashlib.sha256(encode(body).encode()).hexdigest()
        with self.store.db() as d:
            latest=d.execute('SELECT MAX(generation) FROM snapshots').fetchone()[0]
            prior=d.execute('SELECT fingerprint FROM snapshots WHERE generation=?',(generation,)).fetchone()
        if latest is not None and generation<latest:raise Blocked('SNAPSHOT_GENERATION_REGRESSION')
        if prior and prior[0]!=fp:raise Blocked('SAME_GENERATION_DIFFERENT_EVIDENCE')
        orders={};refs={};fills={};updates=[];expected_positions={}
        for o in snap['orders']:
            if o['order_id'] in orders:raise Blocked('DUPLICATE_ORDER_ID')
            orders[o['order_id']]=o;refs.setdefault(o['client_reference'],[]).append(o)
        for f in snap['fills']:
            if f['trade_id'] in fills:raise Blocked('DUPLICATE_EXECUTION_ID')
            qty(f['quantity']);price(f['price']);fills[f['trade_id']]=f
        with self.store.db() as d:seen=dict(d.execute('SELECT id,fingerprint FROM seen_fills'))
        if set(seen)-set(fills):raise Blocked('EXECUTION_EVIDENCE_DISAPPEARED')
        for tid,f in fills.items():
            if tid in seen and seen[tid]!=hashlib.sha256(encode(f).encode()).hexdigest():raise Blocked('EXECUTION_CORRECTION_REVIEW_REQUIRED')
        bound=set()
        for row in self.store.rows('intents'):
            matches=refs.get(row['request_id'],[])
            if len(matches)!=1:raise Blocked('ORDER_ACCEPTANCE_UNRESOLVED_NO_RESUBMISSION')
            o=matches[0]
            if row.get('order_id') and row['order_id']!=o['order_id']:raise Blocked('ORDER_BINDING_CHANGED')
            if any(o.get(k)!=row[k] for k in ('instrument','product','side','quantity')) or o.get('account_scope')!='OFFLINE_ACCOUNT':raise Blocked('ORDER_IDENTITY_MISMATCH')
            q=o.get('filled');pending=o.get('pending');status=o.get('status')
            if type(q)is not int or type(pending)is not int or not row.get('filled',0)<=q<=row['quantity'] or pending<0 or q+pending>row['quantity']:raise Blocked('FILL_REGRESSION_OR_QUANTITY_INVALID')
            if status not in TERMINAL|{'OPEN','PARTIAL'} or status=='FILLED' and q!=row['quantity'] or status in TERMINAL and pending:raise Blocked('ORDER_STATUS_INCONSISTENT')
            executions=[f for f in fills.values() if f['order_id']==o['order_id']]
            if sum(f['quantity'] for f in executions)!=q:raise Blocked('ORDER_EXECUTION_TOTAL_MISMATCH')
            if any(any(f.get(k)!=row[k] for k in ('instrument','product','side')) for f in executions):raise Blocked('EXECUTION_IDENTITY_MISMATCH')
            new=dict(row,order_id=o['order_id'],status=status,filled=q,pending=pending)
            updates.append(new);bound.add(o['order_id']);key=(row['instrument'],row['product']);expected_positions[key]=expected_positions.get(key,0)+(q if row['side']=='BUY' else -q)
        if set(orders)!=bound or any(f['order_id'] not in bound for f in fills.values()):raise Blocked('UNMAPPED_ACCOUNT_ACTIVITY')
        actual={}
        for p in snap['positions']:
            key=(p['instrument'],p['product'])
            if key in actual or type(p['quantity'])is not int:raise Blocked('POSITION_EVIDENCE_INVALID')
            actual[key]=p['quantity']
        if actual!=expected_positions or any(v<0 for v in actual.values()):raise Blocked('POSITION_FILL_MISMATCH')
        for r in updates:
            if r['side']=='BUY':
                sold=sum(x['filled'] for x in updates if x.get('parent')==r['request_id'])
                if sold>r['filled']:raise Blocked('EXIT_FILL_EXCEEDS_OWNED_ENTRY')
        # Apply all validated rows and execution identities together, after checks.
        with self.store.db() as d:
            for r in updates:d.execute('UPDATE intents SET data=? WHERE id=?',(encode(r),r['request_id']))
            for tid,f in fills.items():d.execute('INSERT OR IGNORE INTO seen_fills VALUES(?,?)',(tid,hashlib.sha256(encode(f).encode()).hexdigest()))
            d.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?)',(generation,fp))
        return dict(status='RECONCILED_OFFLINE_FAKE',generation=generation,orders=len(orders),fills=len(fills))
    def reconcile(self,snapshot=None):
        with self.store.lock():
            try:return self._reconcile(snapshot)
            except Exception:
                self._pause('RECONCILIATION_REVIEW_REQUIRED');raise
    def resume(self):
        with self.store.lock():
            try:self._reconcile()
            except Exception:self._pause('RESUME_RECONCILIATION_REQUIRED');raise
            c=self._control();c.update(mode='ARMED',version=c['version']+1,resumed_at=self.clock().isoformat())
            with self.store.db() as d:d.execute('UPDATE meta SET data=? WHERE id=1',(encode(c),))
    def _place(self,row):
        row.update(status='IN_FLIGHT',filled=0,pending=row['quantity']);self.store.put(row)
        self.store.event('INTENT_DURABLE_BEFORE_TRANSPORT',request_id=row['request_id'],side=row['side'])
        try:
            ack=self.transport.place(row);row['order_id']=ack['order_id'];row['status']='ACKNOWLEDGED';self.store.put(row)
        except Exception:
            row['status']='UNKNOWN';self.store.put(row);self._pause('SUBMISSION_OUTCOME_UNKNOWN')
            return row
        try:self._reconcile()
        except Exception:self._pause('ACKNOWLEDGED_ORDER_EVIDENCE_REVIEW');raise
        return next(x for x in self.store.rows('intents') if x['request_id']==row['request_id'])
    def buy(self,request_id,*,instrument,quantity,limit_price,signal_at):
        qty(quantity);price(limit_price)
        if not isinstance(request_id,str) or not request_id or not isinstance(instrument,str) or not instrument:raise Blocked('IDENTITY_REQUIRED')
        payload=dict(instrument=instrument,quantity=quantity,price=str(price(limit_price)),signal_at=signal_at,side='BUY',product='I',parent=None)
        fp=hashlib.sha256(encode(payload).encode()).hexdigest()
        with self.store.lock():
            old=next((x for x in self.store.rows('intents') if x['request_id']==request_id),None)
            if old:
                if old['fingerprint']!=fp:raise Blocked('REQUEST_ID_CONFLICT')
                return dict(old,idempotent_replay=True) # never POST again, including UNKNOWN
            c=self._control();signal_time=aware(signal_at)
            if c['mode']!='ARMED':raise Blocked('ENTRIES_PAUSED')
            if signal_time<=aware(c['resumed_at']) or not 0<=(self.clock()-signal_time).total_seconds()<=60:raise Blocked('SIGNAL_NOT_FRESH_AFTER_RESUME')
            try:self._reconcile()
            except Exception:self._pause('ENTRY_RECONCILIATION_REQUIRED');raise
            if any(x['status'] not in TERMINAL or x['side']=='BUY' and self._position(x)>0 for x in self.store.rows('intents')):raise Blocked('EXPOSURE_OR_ORDER_UNRESOLVED')
            return self._place(dict(payload,request_id=request_id,fingerprint=fp))
    def _exit(self,entry_id):
        self._reconcile();entry=next((x for x in self.store.rows('intents') if x['request_id']==entry_id and x['side']=='BUY'),None)
        if entry is None:raise Blocked('OWNED_ENTRY_NOT_FOUND')
        if entry['status'] not in TERMINAL:
            self.transport.cancel(entry['order_id']);self._reconcile();entry=next(x for x in self.store.rows('intents') if x['request_id']==entry_id)
        if entry['status'] not in TERMINAL:raise Blocked('ENTRY_CANCEL_NOT_CONFIRMED')
        rid='EXIT-'+entry_id;old=next((x for x in self.store.rows('intents') if x['request_id']==rid),None)
        if old:
            if old['status'] in TERMINAL and self._position(entry)>0:raise Blocked('TERMINAL_EXIT_WITH_REMAINING_EXPOSURE_REVIEW')
            return dict(old,idempotent_replay=True) # never another SELL for unresolved exit
        remaining=self._position(entry)
        if not remaining:return dict(status='FLAT_CONFIRMED',remaining=0)
        return self._place(dict(request_id=rid,instrument=entry['instrument'],quantity=remaining,price=entry['price'],side='SELL',product=entry['product'],parent=entry_id,fingerprint='EXIT-'+entry_id))
    def exit(self,entry_id,manual=True):
        with self.store.lock():
            if manual:self._pause('MANUAL_EXIT')
            try:return self._exit(entry_id)
            except Exception:self._pause('EXIT_RECONCILIATION_REQUIRED');raise
    def pause(self):
        with self.store.lock():
            self._pause('OPERATOR_PAUSE')
            # Only entries pending in application state at Pause require cleanup.
            pending=[r for r in self.store.rows('intents') if r['side']=='BUY' and r['status'] not in TERMINAL]
            try:
                for row in pending:self._exit(row['request_id'])
                return self._reconcile()
            except Exception:self._pause('PAUSE_CLEANUP_REVIEW_REQUIRED');raise
    def status(self):
        with self.store.lock():return dict(control=self._control(),intents=self.store.rows('intents'),
            production_execution_enabled=False,orders_sent_to_upstox=False,evidence_mode='OFFLINE_FAKE_TRANSPORT')
