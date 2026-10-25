"""Durable broker-request outbox. Mutation boundary is unconditionally disabled."""
import hashlib,json,os,sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from provider_mapping import stamp
POLICY='BULLISH_GAP2_FULL_WMA2'
VERSION='bullish-gap2-full-wma2-2.0.0-wma40-reversal'
class Blocked(ValueError):pass

def encode(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(v):return hashlib.sha256(encode(v).encode()).hexdigest()
def identity(v):
    if not isinstance(v,str) or not 1<=len(v)<=200 or any(ord(c)<32 for c in v):raise Blocked('INVALID_IDENTITY')
    return v

def validate_draft(request,*,as_of):
    allowed={'model','request_id','created_at','documented_method','documented_host','documented_path','body','fingerprint','submission_enabled','entry_permission','orders_sent'}
    if not isinstance(request,dict) or set(request)!=allowed:raise Blocked('EXACT_DISABLED_DRAFT_REQUIRED')
    if request['model']!='HILEGA_DISABLED_UPSTOX_REQUEST_DRAFT_V1':raise Blocked('DRAFT_MODEL_INVALID')
    if any(request[k] is not False for k in ('submission_enabled','entry_permission','orders_sent')):raise Blocked('DISABLED_FLAGS_REQUIRED')
    if (request['documented_method'],request['documented_host'],request['documented_path'])!=('POST','api-hft.upstox.com','/v3/order/place'):raise Blocked('FIXED_DOCUMENTED_ENDPOINT_REQUIRED')
    now=stamp(as_of);created=stamp(request['created_at'])
    if created.date()!=now.date() or not 0<=(now-created).total_seconds()<=60:raise Blocked('REQUEST_STALE_FUTURE_OR_WRONG_SESSION')
    identity(request['request_id']);body=request['body']
    if not isinstance(body,dict) or sha(body)!=request['fingerprint']:raise Blocked('REQUEST_BODY_FINGERPRINT_INVALID')
    base={'quantity','product','validity','price','tag','instrument_token','order_type','transaction_type','disclosed_quantity','trigger_price','is_amo','slice'}
    expected=base|({'market_protection'} if body.get('order_type')=='MARKET' else set())
    if set(body)!=expected:raise Blocked('UNEXPECTED_BROKER_BODY_FIELDS')
    if type(body['quantity'])is not int or body['quantity']<=0 or body['transaction_type'] not in {'BUY','SELL'}:raise Blocked('QUANTITY_OR_SIDE_INVALID')
    if body['product']!='I' or body['validity']!='DAY' or body['is_amo'] is not False or body['slice'] is not False:raise Blocked('INITIAL_INTRADAY_UNSLICED_REQUEST_REQUIRED')
    if body['order_type'] not in {'MARKET','LIMIT'}:raise Blocked('ORDER_TYPE_INVALID')
    # Metadata/quote/cash eligibility is NOT inferred from a syntactically valid
    # request. This outbox never authorizes submission or releases reservations.
    return json.loads(encode(request))

class Outbox:
    def __init__(self,path,account_scope):
        self.path=Path(path);self.scope=identity(account_scope)
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW,0o600);os.close(fd);self.path.chmod(0o600)
        with self.tx() as d:
            d.executescript('''CREATE TABLE IF NOT EXISTS outbox_meta(id INTEGER PRIMARY KEY,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS outbox_requests(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS outbox_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL);''')
            expected=encode(dict(account_scope=account_scope,mode='DISABLED_ONLY'))
            old=d.execute('SELECT data FROM outbox_meta WHERE id=1').fetchone()
            if old and old[0]!=expected:raise Blocked('OUTBOX_SCOPE_MISMATCH')
            d.execute('INSERT OR IGNORE INTO outbox_meta VALUES(1,?)',(expected,))
    @contextmanager
    def tx(self):
        d=sqlite3.connect(self.path,timeout=15);d.execute('PRAGMA synchronous=FULL');d.execute('BEGIN IMMEDIATE')
        try:yield d;d.commit()
        except BaseException:d.rollback();raise
        finally:d.close()
    def _event(self,d,kind,**fields):d.execute('INSERT INTO outbox_events(data) VALUES(?)',(encode(dict(type=kind,**fields)),))
    def prepare(self,request,*,signal_id,signal_at,direction,as_of,policy_id=POLICY,strategy_version=VERSION,parent_id=None):
        draft=validate_draft(request,as_of=as_of);identity(signal_id)
        if policy_id!=POLICY or strategy_version!=VERSION:raise Blocked('CURRENT_POLICY_VERSION_REQUIRED')
        if direction not in {'BULLISH','BEARISH'}:raise Blocked('DIRECTION_REQUIRED')
        signal=stamp(signal_at);created=stamp(draft['created_at'])
        if signal.date()!=created.date() or signal>created:raise Blocked('SIGNAL_TIME_INVALID')
        row=dict(id=draft['request_id'],account_scope=self.scope,request=draft,signal_id=signal_id,signal_at=signal_at,direction=direction,parent_id=parent_id,
            policy_id=policy_id,strategy_version=strategy_version,state='PREPARED_DISABLED',order_id=None,
            account_identity_verified=False,reservation_verified=False,production_execution_enabled=False,orders_sent=False)
        fingerprint=sha({k:v for k,v in row.items() if k!='state'})
        with self.tx() as d:
            old=d.execute('SELECT fingerprint,data FROM outbox_requests WHERE id=?',(row['id'],)).fetchone()
            if old:
                if old[0]!=fingerprint:raise Blocked('REQUEST_ID_CONFLICT')
                return dict(json.loads(old[1]),idempotent_replay=True)
            others=[json.loads(x[0]) for x in d.execute('SELECT data FROM outbox_requests')]
            if draft['body']['transaction_type']=='BUY':
                if parent_id is not None:raise Blocked('ENTRY_CANNOT_HAVE_PARENT')
                if any(x['signal_id']==signal_id and x['request']['body']['transaction_type']=='BUY' for x in others):raise Blocked('SIGNAL_ALREADY_PREPARED')
            else:
                parent=next((x for x in others if x['id']==parent_id),None)
                if parent is None or parent['request']['body']['transaction_type']!='BUY':raise Blocked('EXIT_PARENT_REQUIRED')
                if draft['body']['instrument_token']!=parent['request']['body']['instrument_token']:raise Blocked('EXIT_INSTRUMENT_MISMATCH')
                # A parent draft is not execution ownership. SELL remains disabled.
            d.execute('INSERT INTO outbox_requests VALUES(?,?,?)',(row['id'],fingerprint,encode(row)))
            self._event(d,'BROKER_REQUEST_PREPARED_DISABLED',request_id=row['id'],as_of=as_of,body_fingerprint=draft['fingerprint'])
        return row
    def attempt_submission(self,request_id):
        with self.tx() as d:
            found=d.execute('SELECT data FROM outbox_requests WHERE id=?',(identity(request_id),)).fetchone()
            if not found:raise Blocked('REQUEST_NOT_PREPARED')
            row=json.loads(found[0]);row['state']='BLOCKED_TRANSPORT_DISABLED'
            d.execute('UPDATE outbox_requests SET data=? WHERE id=?',(encode(row),request_id))
            self._event(d,'SUBMISSION_REFUSED_NO_NETWORK',request_id=request_id)
        return dict(status='BLOCKED_TRANSPORT_DISABLED',request_id=request_id,retry_allowed=False,
            unknown_acceptance=False,orders_sent=False,production_execution_enabled=False,entry_permission=False)
    def import_acknowledgement(self,*args,**kwargs):raise Blocked('LIVE_ACK_PROVENANCE_NOT_IMPLEMENTED_IMPORT_DISABLED')
    def cancel(self,*args,**kwargs):raise Blocked('LIVE_CANCEL_TRANSPORT_DISABLED')
    def modify(self,*args,**kwargs):raise Blocked('LIVE_MODIFY_TRANSPORT_DISABLED')
    def release_reservation(self,*args,**kwargs):raise Blocked('OUTBOX_HAS_NO_RESERVATION_RELEASE_AUTHORITY')
    def status(self):
        with self.tx() as d:
            return dict(model='HILEGA_DISABLED_DISPATCH_OUTBOX_V1',requests=[json.loads(x[0]) for x in d.execute('SELECT data FROM outbox_requests ORDER BY rowid')],events=[json.loads(x[0]) for x in d.execute('SELECT data FROM outbox_events ORDER BY seq')],
                mode='DISABLED_ONLY',production_execution_enabled=False,orders_sent=False,entry_permission=False,
                live_transport_implemented=False,live_ack_binding_implemented=False,application_integrated=False)
