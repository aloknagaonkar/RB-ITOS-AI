"""Durable draft/binding evidence. Live submission and live ack import remain disabled."""
import fcntl,hashlib,json,os,sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from provider_mapping import place_ack,stamp,Blocked
POLICY='BULLISH_GAP2_FULL_WMA2';VERSION='bullish-gap2-full-wma2-2.0.0-wma40-reversal'

def enc(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def sha(v):return hashlib.sha256(enc(v).encode()).hexdigest()

class Registry:
    def __init__(self,path,account_scope,mode):
        if mode not in {'OFFLINE_FIXTURE','LIVE_READ_ONLY'}:raise Blocked('NO_LIVE_EXECUTION_MODE')
        if not isinstance(account_scope,str) or not account_scope:raise Blocked('ACCOUNT_SCOPE_REQUIRED')
        self.path=Path(path);self.path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);os.close(fd)
        self.scope=account_scope;self.mode=mode
        with self.lock():
            with self.db() as d:
                d.executescript('''CREATE TABLE IF NOT EXISTS binding_meta(id INTEGER PRIMARY KEY,data TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS binding_intents(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,data TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS binding_receipts(id TEXT PRIMARY KEY,intent_id TEXT UNIQUE NOT NULL,order_id TEXT UNIQUE NOT NULL,data TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS binding_captures(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,data TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS binding_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT NOT NULL);''')
                row=d.execute('SELECT data FROM binding_meta WHERE id=1').fetchone();meta=dict(scope=account_scope,mode=mode)
                if row and json.loads(row[0])!=meta:raise Blocked('ACCOUNT_OR_EVIDENCE_MODE_MISMATCH')
                if not row:d.execute('INSERT INTO binding_meta VALUES(1,?)',(enc(meta),))
        self.ledger=None
        if mode=='OFFLINE_FIXTURE':
            from market_lab.hilega_production_ownership_v1 import Ledger
            self.ledger=Ledger(Path(str(self.path)+'.ownership-fixture.sqlite'),account_scope)
    @contextmanager
    def db(self):
        d=sqlite3.connect(self.path,timeout=15);d.execute('PRAGMA synchronous=FULL')
        try:yield d;d.commit()
        except BaseException:d.rollback();raise
        finally:d.close()
    @contextmanager
    def lock(self):
        fd=os.open(str(self.path)+'.binding.lock',os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,'a') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(f,fcntl.LOCK_UN)
    def _rows(self):
        with self.db() as d:return [json.loads(x[0]) for x in d.execute('SELECT data FROM binding_intents ORDER BY rowid')]
    def _put(self,row,fingerprint):
        with self.db() as d:d.execute('INSERT OR REPLACE INTO binding_intents VALUES(?,?,?)',(row['intent_id'],fingerprint,enc(row)))
    def _event(self,kind,**kw):
        with self.db() as d:d.execute('INSERT INTO binding_events(data) VALUES(?)',(enc(dict(type=kind,**kw)),))
    def prepare(self,request,*,signal_id,signal_at,direction,policy_id=POLICY,strategy_version=VERSION,parent_id=None):
        if policy_id!=POLICY or strategy_version!=VERSION:raise Blocked('CURRENT_POLICY_VERSION_REQUIRED')
        if request.get('model')!='HILEGA_DISABLED_UPSTOX_REQUEST_DRAFT_V1' or request.get('submission_enabled') is not False:raise Blocked('DISABLED_REQUEST_DRAFT_REQUIRED')
        body=request['body']
        if request.get('fingerprint')!=sha(body):raise Blocked('REQUEST_FINGERPRINT_INVALID')
        when=stamp(request['created_at']);signal=stamp(signal_at)
        if signal>when or signal.date()!=when.date():raise Blocked('SIGNAL_TIME_OUTSIDE_INTENT_SESSION')
        if direction not in {'BULLISH','BEARISH'} or not isinstance(signal_id,str) or not signal_id:raise Blocked('SIGNAL_ID_DIRECTION_REQUIRED')
        rid=request.get('request_id')
        if not isinstance(rid,str) or not rid:raise Blocked('LOCAL_REQUEST_ID_REQUIRED')
        plan=dict(scope=self.scope,request=request,signal_id=signal_id,signal_at=signal_at,direction=direction,policy_id=policy_id,strategy_version=strategy_version,parent_id=parent_id)
        fp=sha(plan)
        with self.lock():
            with self.db() as d:old=d.execute('SELECT fingerprint,data FROM binding_intents WHERE id=?',(rid,)).fetchone()
            if old and old[0]!=fp:raise Blocked('INTENT_ID_REUSED_WITH_DIFFERENT_PLAN')
            if old and json.loads(old[1]).get('ownership_id') is not None:return dict(json.loads(old[1]),idempotent_replay=True)
            if old and self.mode=='LIVE_READ_ONLY':return dict(json.loads(old[1]),idempotent_replay=True)
            others=self._rows()
            if not old and any(x['signal_id']==signal_id and x['request']['body']['transaction_type']=='BUY' and x['session_date']==when.date().isoformat() for x in others):raise Blocked('SIGNAL_ALREADY_HAS_INTENT')
            if body['transaction_type']=='SELL':
                parent=next((x for x in others if x['intent_id']==parent_id),None)
                if not parent or parent['request']['body']['transaction_type']!='BUY':raise Blocked('PARENT_ENTRY_INTENT_REQUIRED')
                pb=parent['request']['body']
                if body['instrument_token']!=pb['instrument_token'] or body['product']!=pb['product'] or body['quantity']>pb['quantity']:raise Blocked('EXIT_PARENT_REQUEST_MISMATCH')
            elif body['transaction_type']!='BUY' or parent_id is not None:raise Blocked('ENTRY_PARENT_OR_SIDE_INVALID')
            row=json.loads(old[1]) if old else dict(intent_id=rid,session_date=when.date().isoformat(),state='DRAFT_ONLY',ownership_id=None,**plan)
            self._put(row,fp) # committed BEFORE any ownership registration/receipt binding
            if self.ledger is not None:
                if body['transaction_type']=='BUY':
                    own=self.ledger.register_entry(signal_id=signal_id,signal_at=signal_at,intent_at=request['created_at'],direction=direction,
                        instrument=body['instrument_token'],product=body['product'],quantity_=body['quantity'],policy_id=policy_id,strategy_version=strategy_version)
                else:
                    if not parent.get('ownership_id'):raise Blocked('PARENT_OWNERSHIP_REGISTRATION_PENDING')
                    own=self.ledger.register_exit(entry_id=parent['ownership_id'],exit_key=rid,intent_at=request['created_at'],quantity_=body['quantity'],reason='OFFLINE_MATCHING_EXIT')
                row.update(ownership_id=own,state='OFFLINE_INTENT_REGISTERED');self._put(row,fp)
            self._event('DISABLED_INTENT_PERSISTED',intent_id=rid,mode=self.mode)
            return row
    def bind_fixture_ack(self,intent_id,receipt_id,response,*,at):
        if self.mode!='OFFLINE_FIXTURE':raise Blocked('FIXTURE_ACK_CANNOT_BIND_LIVE_INTENT')
        if not isinstance(receipt_id,str) or not 1<=len(receipt_id)<=200:raise Blocked('RECEIPT_ID_REQUIRED')
        parsed=place_ack(response)
        if parsed['status']!='ACKNOWLEDGED_NOT_FILLED':raise Blocked('ACK_UNKNOWN_OR_SPLIT_REVIEW_NO_BINDING')
        oid=parsed['order_id'];stamp(at)
        with self.lock():
            row=next((x for x in self._rows() if x['intent_id']==intent_id),None)
            if row is None or row.get('ownership_id') is None:raise Blocked('REGISTERED_INTENT_REQUIRED_BEFORE_ACK')
            if stamp(at)<stamp(row['request']['created_at']):raise Blocked('ACK_PRECEDES_INTENT')
            receipt=dict(intent_id=intent_id,receipt_id=receipt_id,order_id=oid,response=response,at=at,evidence_mode='OFFLINE_FIXTURE')
            with self.db() as d:
                existing=d.execute('SELECT data FROM binding_receipts WHERE id=?',(receipt_id,)).fetchone()
                bound=d.execute('SELECT data FROM binding_receipts WHERE intent_id=? OR order_id=?',(intent_id,oid)).fetchone()
                if existing and json.loads(existing[0])!=receipt:raise Blocked('ACK_RECEIPT_ID_CONFLICT')
                if bound and json.loads(bound[0])!=receipt:raise Blocked('ORDER_OR_INTENT_ALREADY_BOUND')
                if not existing:d.execute('INSERT INTO binding_receipts VALUES(?,?,?,?)',(receipt_id,intent_id,oid,enc(receipt)))
            # Separate durable stores: a crash here is retried idempotently for
            # evidence binding only. This NEVER submits an order.
            self.ledger.bind_order(intent_id=row['ownership_id'],order_id=oid,at=at)
            with self.db() as d:fp=d.execute('SELECT fingerprint FROM binding_intents WHERE id=?',(intent_id,)).fetchone()[0]
            row.update(state='OFFLINE_ACK_BOUND',order_id=oid);self._put(row,fp)
            return dict(status='OFFLINE_ACK_BOUND_NOT_FILLED',intent_id=intent_id,production_execution_enabled=False)
    def reconcile_fixture(self,snapshot,*,as_of):
        if self.mode!='OFFLINE_FIXTURE' or snapshot.get('evidence_mode')!='OFFLINE_FIXTURE':raise Blocked('FIXTURE_RECONCILIATION_ONLY')
        with self.lock():
            if any(x.get('ownership_id') is None for x in self._rows()):raise Blocked('INTENT_REGISTRATION_INCOMPLETE')
            return self.ledger.reconcile(snapshot,as_of=as_of)
    def record_live_capture(self,snapshot,pin,*,as_of):
        if self.mode!='LIVE_READ_ONLY':raise Blocked('LIVE_CAPTURE_CANNOT_ENTER_FIXTURE_REGISTRY')
        from market_lab.hilega_production_account_adapter_v1 import verify
        verify(snapshot,pin,as_of=as_of)
        if snapshot['account_scope']!=self.scope:raise Blocked('LIVE_CAPTURE_ACCOUNT_SCOPE_MISMATCH')
        sid=snapshot['snapshot_id'];fp=sha(snapshot)
        with self.lock():
            with self.db() as d:
                prior=d.execute('SELECT fingerprint FROM binding_captures WHERE id=?',(sid,)).fetchone()
                if prior and prior[0]!=fp:raise Blocked('CAPTURE_ID_CONTENT_CONFLICT')
                if not prior:d.execute('INSERT INTO binding_captures VALUES(?,?,?)',(sid,fp,enc(snapshot)))
            self._event('LIVE_READ_ONLY_CAPTURE_RECORDED',snapshot_id=sid)
        activity=bool(snapshot['orders'] or snapshot['trades'] or any(x['quantity'] for x in snapshot['positions']))
        return dict(status='UNMAPPED_REAL_ACTIVITY_REVIEW' if activity else 'EMPTY_ACCOUNT_READ_ONLY_BASELINE',
            capture_verified=True,live_intents_bound=0,ownership_verified=False,entry_permission=False,production_execution_enabled=False,orders_sent=False)
    def bind_live_ack(self,*a,**kw):raise Blocked('LIVE_TRANSPORT_RECEIPT_PROVENANCE_NOT_IMPLEMENTED_BINDING_DISABLED')
    def submit(self,*a,**kw):raise Blocked('LIVE_SUBMISSION_DISABLED_IN_CODE')
    def status(self,*,as_of):
        with self.lock():
            with self.db() as d:
                receipts=[json.loads(x[0]) for x in d.execute('SELECT data FROM binding_receipts ORDER BY rowid')]
                captures=d.execute('SELECT COUNT(*) FROM binding_captures').fetchone()[0]
            return dict(model='HILEGA_DISABLED_INTENT_BINDING_V1',mode=self.mode,intents=self._rows(),receipts=receipts,live_capture_count=captures,
                offline_ownership=self.ledger.report(as_of=as_of) if self.ledger else None,
                live_binding_enabled=False,production_execution_enabled=False,orders_sent=False,entry_permission=False)
