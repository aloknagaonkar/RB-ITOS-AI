"""Upstox request/receipt adapter. Real HTTP mutations remain closed in code."""
import hashlib,hmac,json,os,sqlite3,uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError
from urllib.parse import urlencode
from .mapping import place_ack,cancel_ack,cancel_draft,stamp

class Blocked(ValueError):pass
class GateClosed(Blocked):pass
class OutcomeUnknown(RuntimeError):pass

def encode(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(v):return hashlib.sha256(encode(v).encode()).hexdigest()
def identity(v):
    if not isinstance(v,str) or not 1<=len(v)<=200 or any(ord(c)<32 for c in v):raise Blocked('INVALID_IDENTITY')
    return v

def require_live_clearance():
    # No environment/config/browser switch can authorize production in this package.
    raise GateClosed('PRODUCTION_MUTATIONS_CLOSED_IN_CODE')

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

class HttpTransport:
    mode='LIVE_CLOSED'
    def __init__(self,token_provider):self.token_provider=token_provider
    def check(self):require_live_clearance()
    def send(self,attempt_id,wire):
        self.check() # BEFORE token access, Request construction or network.
        # Production implementation is intentionally unreachable behind the gate.
        url='https://api-hft.upstox.com'+wire['path']
        if wire.get('query'):url+='?'+urlencode(wire['query'])
        if wire['host']!='api-hft.upstox.com' or (wire['method'],wire['path']) not in {('POST','/v3/order/place'),('DELETE','/v3/order/cancel')}:raise Blocked('ENDPOINT_NOT_ALLOWED')
        token=self.token_provider()
        if not isinstance(token,str) or not token.strip():raise GateClosed('TOKEN_UNAVAILABLE')
        request=Request(url,data=encode(wire['body']).encode() if wire.get('body') is not None else None,method=wire['method'],headers={'Authorization':'Bearer '+token.strip(),'Accept':'application/json','Content-Type':'application/json','User-Agent':'RB-ITOS-AI/1.0 (broker execution adapter)'})
        try:
            with build_opener(NoRedirect()).open(request,timeout=8) as response:
                raw=response.read(65537);status=response.status
            if len(raw)>65536:raise OutcomeUnknown('RESPONSE_TOO_LARGE_NO_RETRY')
            body=json.loads(raw)
        except Exception:
            # All ambiguous HTTP/redirect/parse/timeout paths require reconciliation.
            # No raw response, token or exception message is persisted or printed.
            raise OutcomeUnknown('TRANSPORT_OUTCOME_REQUIRES_RECONCILIATION_NO_RETRY') from None
        return dict(attempt_id=attempt_id,wire_fingerprint=sha(wire),http_status=status,body=body,origin='LOCAL_HTTP_TRANSPORT')

class Store:
    def __init__(self,path,scope,mode):
        if mode not in {'LIVE_CLOSED','OFFLINE_FIXTURE'}:raise Blocked('MODE_INVALID')
        self.path=Path(path);self.scope=identity(scope);self.mode=mode
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600);os.close(fd);self.path.chmod(0o600)
        with self.tx() as d:
            d.executescript('''CREATE TABLE IF NOT EXISTS meta(id INTEGER PRIMARY KEY,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,request_id TEXT NOT NULL,operation TEXT NOT NULL,data TEXT NOT NULL,UNIQUE(request_id,operation));
              CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS fixture_orders(id TEXT PRIMARY KEY,attempt TEXT UNIQUE NOT NULL,data TEXT NOT NULL);''')
            old=d.execute('SELECT data FROM meta WHERE id=1').fetchone();expected=encode(dict(scope=scope,mode=mode))
            if old and old[0]!=expected:raise Blocked('STORE_SCOPE_OR_MODE_MISMATCH')
            d.execute('INSERT OR IGNORE INTO meta VALUES(1,?)',(expected,))
    @contextmanager
    def tx(self):
        d=sqlite3.connect(self.path,timeout=15);d.execute('PRAGMA synchronous=FULL');d.execute('BEGIN IMMEDIATE')
        try:yield d;d.commit()
        except BaseException:d.rollback();raise
        finally:d.close()
    def event(self,d,kind,**fields):d.execute('INSERT INTO events(data) VALUES(?)',(encode(dict(type=kind,**fields)),))
    def requests(self):
        with self.tx() as d:return [json.loads(x[0]) for x in d.execute('SELECT data FROM requests ORDER BY rowid')]

class FixtureTransport:
    """Explicit durable fake response source. No sockets or broker credentials."""
    mode='OFFLINE_FIXTURE'
    def __init__(self,store):
        if store.mode!=self.mode:raise Blocked('FIXTURE_CANNOT_USE_LIVE_STORE')
        self.store=store;self.timeout_before=False;self.timeout_after=False;self.split_ack=False;self.cancel_timeout=False
    def check(self):return None
    def send(self,attempt_id,wire):
        if self.timeout_before:self.timeout_before=False;raise OutcomeUnknown('EXPLICIT_FIXTURE_BEFORE_ACCEPTANCE_TIMEOUT')
        if wire['method']=='POST':
            b=wire['body'];oid='FIXTURE-'+uuid.uuid4().hex
            row=dict(order_id=oid,attempt_id=attempt_id,instrument=b['instrument_token'],product=b['product'],side=b['transaction_type'],quantity=b['quantity'],filled=0,status='OPEN')
            with self.store.tx() as d:d.execute('INSERT INTO fixture_orders VALUES(?,?,?)',(oid,attempt_id,encode(row)))
            if self.timeout_after:self.timeout_after=False;raise OutcomeUnknown('EXPLICIT_FIXTURE_ACCEPTED_RESPONSE_LOST')
            ids=[oid,'FIXTURE-SPLIT'] if self.split_ack else [oid]
            body=dict(status='success',data=dict(order_ids=ids))
        else:
            oid=wire['query']['order_id']
            with self.store.tx() as d:
                found=d.execute('SELECT data FROM fixture_orders WHERE id=?',(oid,)).fetchone()
                if not found:raise OutcomeUnknown('FIXTURE_ORDER_NOT_FOUND')
                row=json.loads(found[0])
                if row['status']!='FILLED':row['status']='CANCELLED'
                d.execute('UPDATE fixture_orders SET data=? WHERE id=?',(encode(row),oid))
            if self.cancel_timeout:raise OutcomeUnknown('EXPLICIT_FIXTURE_CANCEL_RESPONSE_LOST')
            body=dict(status='success',data=dict(order_id=oid))
        return dict(attempt_id=attempt_id,wire_fingerprint=sha(wire),http_status=200,body=body,origin='EXPLICIT_FIXTURE_TRANSPORT')
    def fill(self,oid,cumulative):
        with self.store.tx() as d:
            found=d.execute('SELECT data FROM fixture_orders WHERE id=?',(oid,)).fetchone()
            if not found:raise Blocked('ORDER_NOT_FOUND')
            row=json.loads(found[0])
            if type(cumulative)is not int or not row['filled']<=cumulative<=row['quantity'] or row['status'] in {'FILLED','CANCELLED'}:raise Blocked('INVALID_FIXTURE_FILL')
            row.update(filled=cumulative,status='FILLED' if cumulative==row['quantity'] else 'PARTIAL')
            d.execute('UPDATE fixture_orders SET data=? WHERE id=?',(encode(row),oid))
    def orders(self):
        with self.store.tx() as d:return [json.loads(x[0]) for x in d.execute('SELECT data FROM fixture_orders ORDER BY rowid')]

class Adapter:
    def __init__(self,store,transport):
        if type(transport) not in {FixtureTransport,HttpTransport} or transport.mode!=store.mode:raise Blocked('EXACT_TRANSPORT_AND_PINNED_MODE_REQUIRED')
        if type(transport)is FixtureTransport and transport.store.path.resolve()!=store.path.resolve():raise Blocked('FIXTURE_STORE_MISMATCH')
        self.store=store;self.transport=transport;self.checkpoint=lambda stage:None
    def prepare(self,draft,*,signal_id,signal_at,direction,reservation_reference,as_of):
        # Reservation linkage is a reference only. This module has NO authority to
        # reserve, release or claim a verified live funds allocation.
        identity(signal_id);identity(reservation_reference);identity(draft.get('request_id'))
        allowed={'model','request_id','created_at','documented_method','documented_host','documented_path','body','fingerprint','submission_enabled','entry_permission','orders_sent'}
        if set(draft)!=allowed or draft['model']!='HILEGA_DISABLED_UPSTOX_REQUEST_DRAFT_V1':raise Blocked('EXACT_DISABLED_DRAFT_REQUIRED')
        if any(draft[k] is not False for k in ('submission_enabled','entry_permission','orders_sent')):raise Blocked('DISABLED_DRAFT_REQUIRED')
        if sha(draft['body'])!=draft['fingerprint']:raise Blocked('BODY_FINGERPRINT_MISMATCH')
        if (draft['documented_method'],draft['documented_host'],draft['documented_path'])!=('POST','api-hft.upstox.com','/v3/order/place'):raise Blocked('FIXED_PLACE_ENDPOINT_REQUIRED')
        now=stamp(as_of);created=stamp(draft['created_at']);signal=stamp(signal_at)
        if now.date()!=created.date() or signal.date()!=created.date() or signal>created or not 0<=(now-created).total_seconds()<=60:raise Blocked('FRESH_SESSION_REQUEST_REQUIRED')
        if direction not in {'BULLISH','BEARISH'}:raise Blocked('DIRECTION_REQUIRED')
        body=draft['body']
        fields={'quantity','product','validity','price','tag','instrument_token','order_type','transaction_type','disclosed_quantity','trigger_price','is_amo','slice'}
        if body.get('order_type')=='MARKET':fields.add('market_protection')
        if set(body)!=fields or body.get('order_type') not in {'MARKET','LIMIT'}:raise Blocked('UNEXPECTED_BODY_FIELDS')
        if body.get('product')!='I' or body.get('validity')!='DAY' or body.get('is_amo') is not False or body.get('slice') is not False:raise Blocked('INITIAL_REQUEST_CONTRACT_REQUIRED')
        if body.get('transaction_type') not in {'BUY','SELL'} or type(body.get('quantity'))is not int or body['quantity']<=0:raise Blocked('SIDE_OR_QUANTITY_INVALID')
        plan=dict(request_id=draft['request_id'],draft=draft,signal_id=signal_id,signal_at=signal_at,direction=direction,reservation_reference=reservation_reference)
        fp=sha(plan);row=dict(plan,state='PREPARED',order_id=None,filled=None,remaining=None,reservation_verified=False)
        with self.store.tx() as d:
            old=d.execute('SELECT fingerprint,data FROM requests WHERE id=?',(row['request_id'],)).fetchone()
            if old:
                if old[0]!=fp:raise Blocked('REQUEST_ID_CONFLICT')
                return dict(json.loads(old[1]),idempotent_replay=True)
            if any(x['signal_id']==signal_id for x in [json.loads(v[0]) for v in d.execute('SELECT data FROM requests')]):raise Blocked('SIGNAL_ALREADY_CONSUMED')
            d.execute('INSERT INTO requests VALUES(?,?,?)',(row['request_id'],fp,encode(row)))
            self.store.event(d,'REQUEST_PREPARED',request_id=row['request_id'],body_fingerprint=draft['fingerprint'])
        return row
    def _wire(self,row,operation):
        if operation=='PLACE':return dict(method='POST',host='api-hft.upstox.com',path='/v3/order/place',body=row['draft']['body'])
        if not row.get('order_id'):raise Blocked('ACKNOWLEDGED_ORDER_REQUIRED_FOR_CANCEL')
        request=cancel_draft(row['order_id'])
        return dict(method='DELETE',host=request['documented_host'],path=request['documented_path'],query=request['query'])
    def submit(self,request_id):return self._send(request_id,'PLACE')
    def cancel(self,request_id):return self._send(request_id,'CANCEL')
    def _send(self,request_id,operation):
        identity(request_id)
        try:self.transport.check()
        except GateClosed:
            with self.store.tx() as d:self.store.event(d,'PRODUCTION_GATE_REFUSED',request_id=request_id,operation=operation)
            return dict(status='PRODUCTION_MUTATIONS_CLOSED_IN_CODE',orders_sent=False,production_execution_enabled=False)
        with self.store.tx() as d:
            old=d.execute('SELECT data FROM attempts WHERE request_id=? AND operation=?',(request_id,operation)).fetchone()
            if old:return dict(json.loads(old[0]),idempotent_replay=True) # NEVER send twice
            found=d.execute('SELECT data FROM requests WHERE id=?',(request_id,)).fetchone()
            if not found:raise Blocked('REQUEST_NOT_PREPARED')
            row=json.loads(found[0]);wire=self._wire(row,operation);attempt_id=uuid.uuid4().hex
            attempt=dict(attempt_id=attempt_id,request_id=request_id,operation=operation,wire=wire,state='IN_FLIGHT',retry_allowed=False)
            d.execute('INSERT INTO attempts VALUES(?,?,?,?)',(attempt_id,request_id,operation,encode(attempt)))
            row['state']='IN_FLIGHT' if operation=='PLACE' else 'CANCEL_IN_FLIGHT';d.execute('UPDATE requests SET data=? WHERE id=?',(encode(row),request_id))
            self.store.event(d,'ATTEMPT_COMMITTED_BEFORE_TRANSPORT',attempt_id=attempt_id,operation=operation)
        self.checkpoint('AFTER_ATTEMPT_COMMIT')
        try:receipt=self.transport.send(attempt_id,wire)
        except Exception:
            with self.store.tx() as d:
                attempt['state']='UNKNOWN';d.execute('UPDATE attempts SET data=? WHERE id=?',(encode(attempt),attempt_id))
                row['state']='UNKNOWN' if operation=='PLACE' else 'CANCEL_OUTCOME_UNKNOWN';d.execute('UPDATE requests SET data=? WHERE id=?',(encode(row),request_id))
                self.store.event(d,'OUTCOME_UNKNOWN_NO_RESUBMISSION',attempt_id=attempt_id)
            return attempt
        self.checkpoint('AFTER_TRANSPORT_BEFORE_RECEIPT')
        self._persist_receipt(attempt,receipt)
        self.checkpoint('AFTER_RECEIPT_COMMIT')
        return self._bind_receipt(attempt,receipt)
    def _persist_receipt(self,attempt,receipt):
        origin='EXPLICIT_FIXTURE_TRANSPORT' if self.store.mode=='OFFLINE_FIXTURE' else 'LOCAL_HTTP_TRANSPORT'
        if receipt.get('origin')!=origin or receipt.get('attempt_id')!=attempt['attempt_id'] or receipt.get('wire_fingerprint')!=sha(attempt['wire']):raise Blocked('RECEIPT_PROVENANCE_MISMATCH')
        with self.store.tx() as d:
            old=d.execute('SELECT data FROM receipts WHERE id=?',(attempt['attempt_id'],)).fetchone()
            if old and old[0]!=encode(receipt):raise Blocked('RECEIPT_CONTENT_CHANGED')
            d.execute('INSERT OR IGNORE INTO receipts VALUES(?,?)',(attempt['attempt_id'],encode(receipt)))
    def _bind_receipt(self,attempt,receipt):
        self._persist_receipt(attempt,receipt)
        with self.store.tx() as d:
            row=json.loads(d.execute('SELECT data FROM requests WHERE id=?',(attempt['request_id'],)).fetchone()[0])
            if attempt['operation']=='PLACE':
                parsed=place_ack(receipt['body']) if receipt['http_status']==200 else dict(status='UNKNOWN')
                if parsed['status']=='ACKNOWLEDGED_NOT_FILLED':
                    oid=parsed['order_id']
                    for other in [json.loads(x[0]) for x in d.execute('SELECT data FROM requests WHERE id<>?',(row['request_id'],))]:
                        if other.get('order_id')==oid:raise Blocked('ORDER_ID_ALREADY_BOUND')
                    row.update(order_id=oid,state='ACKNOWLEDGED_NOT_FILLED')
                else:row['state']='UNKNOWN'
            else:
                parsed=cancel_ack(receipt['body'],row['order_id']) if receipt['http_status']==200 else dict(status='UNKNOWN')
                row['state']='CANCEL_ACK_RECONCILE_REQUIRED' if parsed['status']=='CANCEL_ACKNOWLEDGED_RECONCILE_REQUIRED' else 'CANCEL_OUTCOME_UNKNOWN'
            attempt['state']=row['state'];d.execute('UPDATE requests SET data=? WHERE id=?',(encode(row),row['request_id']))
            d.execute('UPDATE attempts SET data=? WHERE id=?',(encode(attempt),attempt['attempt_id']))
        return attempt
    def recover(self):
        # Recovery only consumes persisted receipts. It never resubmits a request
        # or adopts an unacknowledged live order by tag/instrument/client reference.
        with self.store.tx() as d:attempts=[json.loads(x[0]) for x in d.execute('SELECT data FROM attempts ORDER BY rowid')]
        for attempt in attempts:
            with self.store.tx() as d:receipt=d.execute('SELECT data FROM receipts WHERE id=?',(attempt['attempt_id'],)).fetchone()
            if receipt:self._bind_receipt(attempt,json.loads(receipt[0]))
            else:
                with self.store.tx() as d:
                    row=json.loads(d.execute('SELECT data FROM requests WHERE id=?',(attempt['request_id'],)).fetchone()[0])
                    row['state']='UNKNOWN' if attempt['operation']=='PLACE' else 'CANCEL_OUTCOME_UNKNOWN'
                    attempt['state']=row['state'];d.execute('UPDATE requests SET data=? WHERE id=?',(encode(row),row['request_id']))
                    d.execute('UPDATE attempts SET data=? WHERE id=?',(encode(attempt),attempt['attempt_id']))
        with self.store.tx() as d:
            for row in [json.loads(x[0]) for x in d.execute('SELECT data FROM requests')]:
                if row.get('order_id') and row['state'] not in {'UNKNOWN','CANCEL_OUTCOME_UNKNOWN'}:
                    row.update(state='RECONCILIATION_REQUIRED',filled=None,remaining=None)
                    d.execute('UPDATE requests SET data=? WHERE id=?',(encode(row),row['request_id']))
        return self.status()
    def reconcile_fixture(self):
        if type(self.transport)is not FixtureTransport:raise Blocked('FIXTURE_RECONCILIATION_CANNOT_USE_LIVE_STORE')
        orders={x['order_id']:x for x in self.transport.orders()}
        with self.store.tx() as d:
            for row in [json.loads(x[0]) for x in d.execute('SELECT data FROM requests ORDER BY rowid')]:
                if not row.get('order_id'):continue # unknown acceptance is never adopted
                order=orders.get(row['order_id'])
                if not order:raise Blocked('BOUND_FIXTURE_ORDER_MISSING')
                body=row['draft']['body']
                if any(order[a]!=body[b] for a,b in [('instrument','instrument_token'),('product','product'),('side','transaction_type'),('quantity','quantity')]):raise Blocked('FIXTURE_ORDER_IDENTITY_MISMATCH')
                row.update(state=order['status'],filled=order['filled'],remaining=None)
                d.execute('UPDATE requests SET data=? WHERE id=?',(encode(row),row['request_id']))
        return self.status()
    def reconcile_read_only(self,capture,pin,*,as_of):
        from market_lab.hilega_production_account_adapter_v1 import verify
        if self.store.mode!='LIVE_CLOSED':raise Blocked('LIVE_CAPTURE_CANNOT_ENTER_FIXTURE_STORE')
        verify(capture,pin,as_of=as_of)
        if pin['scope']!=self.store.scope:raise Blocked('ACCOUNT_SCOPE_MISMATCH')
        known={r['order_id']:r for r in self.store.requests() if r.get('order_id')}
        actual={r['order_id']:r for r in capture['orders']}
        matched=0;review=False
        for oid,row in known.items():
            order=actual.get(oid);body=row['draft']['body']
            if order is None:review=True;continue
            if any(order[a]!=body[b] for a,b in [('instrument','instrument_token'),('product','product'),('side','transaction_type'),('quantity','quantity')]):raise Blocked('LIVE_ORDER_IDENTITY_MISMATCH')
            matched+=1
        if set(actual)-set(known) or capture['positions'] or capture['trades']:review=True
        return dict(status='READ_ONLY_OWNERSHIP_REVIEW' if review or known else 'EMPTY_READ_ONLY_BASELINE',matched_known_order_count=matched,
            ownership_verified=False,entry_permission=False,production_execution_enabled=False,orders_sent=False)
    def import_acknowledgement(self,*args,**kwargs):raise Blocked('CALLER_ACK_IMPORT_DISABLED')
    def release_reservation(self,*args,**kwargs):raise Blocked('ADAPTER_HAS_NO_RELEASE_AUTHORITY')
    def status(self):
        with self.store.tx() as d:
            requests=[json.loads(x[0]) for x in d.execute('SELECT data FROM requests ORDER BY rowid')]
            attempts=[json.loads(x[0]) for x in d.execute('SELECT data FROM attempts ORDER BY rowid')]
            return dict(model='HILEGA_BROKER_ADAPTER_CLOSED_V1',mode=self.store.mode,requests=requests,attempts=attempts,receipt_count=d.execute('SELECT COUNT(*) FROM receipts').fetchone()[0],
                production_execution_enabled=False,entry_permission=False,orders_sent_to_upstox=False,
                application_integrated=False,reservation_integration='REFERENCE_ONLY_UNVERIFIED',account_ownership_verified=False)
