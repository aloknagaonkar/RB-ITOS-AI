"""Isolated single-leg simulator allocation orchestration, not installed app wiring."""
import fcntl,hashlib,json,os,uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from reservation_ledger import Ledger,Blocked as AllocationBlocked,canonical,money
from market_lab.hilega_production_foundation.core import Service,SimBroker,Blocked,TERMINAL

class Controller:
    def __init__(self,service,allocation_path,account='OFFLINE_SIMULATOR'):
        if type(service)is not Service or type(service.broker)is not SimBroker:raise AllocationBlocked('SIMULATOR_SERVICE_ONLY')
        if Path(allocation_path).resolve()==service.store.path.resolve():raise AllocationBlocked('SEPARATE_ALLOCATION_DB_REQUIRED')
        self.s=service;self.ledger=Ledger(allocation_path,account)
        with self.s.store.db() as d:d.execute('CREATE TABLE IF NOT EXISTS allocation_links(id TEXT PRIMARY KEY,data TEXT NOT NULL)')
    @contextmanager
    def lock(self):
        fd=os.open(str(self.s.store.path)+'.allocation-controller.lock',os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,'a') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(f,fcntl.LOCK_UN)
    def links(self):
        with self.s.store.db() as d:return [json.loads(x[0]) for x in d.execute('SELECT data FROM allocation_links ORDER BY rowid')]
    def put(self,row):
        with self.s.store.db() as d:d.execute('INSERT OR REPLACE INTO allocation_links VALUES(?,?)',(row['id'],canonical(row)))
    def _mark(self,link,state,proof=False):
        current=next(x for x in self.ledger.status()['reservations'] if x['id']==link['id'])
        if current['state']==state:return
        if current['state']=='RESERVED' and state in {'PARTIAL','FILLED'}:
            self.ledger.evidence(uuid.uuid4().hex,link['id'],state='SUBMITTED',as_of=self.s.now().isoformat())
        self.ledger.evidence(uuid.uuid4().hex,link['id'],state=state,as_of=self.s.now().isoformat(),terminal_no_exposure=proof)
    def funds(self,snapshot_id,cash):
        return self.ledger.snapshot(snapshot_id,cash=cash,observed_at=self.s.now().isoformat(),as_of=self.s.now().isoformat(),session_date=self.s.now().date().isoformat())
    def submit(self,*,signal_id,signal_at,snapshot_id,legs,bridge_run_id=None):
        # The existing Service handles one instrument per signal. Never pretend a
        # multi-leg order is atomic; explicit unsupported basket blocks before reserve.
        if not isinstance(legs,list) or len(legs)!=1:raise AllocationBlocked('SINGLE_LEG_INTEGRATION_ONLY')
        leg=legs[0];day=self.s.now().date().isoformat();sid=hashlib.sha256((day+'|'+signal_id).encode()).hexdigest()
        fingerprint=hashlib.sha256(canonical(dict(signal_id=signal_id,signal_at=signal_at,snapshot_id=snapshot_id,legs=legs)).encode()).hexdigest()
        with self.lock():
            previous=next((x for x in self.links() if x['id']==sid),None)
            if previous:
                if previous['fingerprint']!=fingerprint:raise AllocationBlocked('PLAN_CONFLICT_NO_RESUBMISSION')
                self._sync()
                return dict(status='ALREADY_CONSUMED_NO_RESUBMISSION',intent_id=sid,entry_permission=False)
            if self.s.status()['control']['mode']!='ARMED':raise Blocked('TRADING_PAUSED')
            link=dict(id=sid,signal_id=signal_id,fingerprint=fingerprint,leg=leg,state='PREPARING',created_at=self.s.now().isoformat())
            self.put(link)
            try:self.ledger.reserve(sid,signal_id=signal_id,snapshot_id=snapshot_id,legs=legs,as_of=self.s.now().isoformat(),session_date=day)
            except AllocationBlocked:
                link['state']='RESERVATION_REJECTED';self.put(link);raise
            link['state']='RESERVED_BEFORE_SUBMIT';self.put(link)
            try:
                intent=self.s.submit_entry(signal_id=signal_id,signal_at=signal_at,instrument=leg['instrument'],
                    quantity=leg['quantity'],price=leg['ask'],bridge_run_id=bridge_run_id)
            except Blocked:
                # Installed Service raises Blocked before _submit; transport exceptions
                # produce durable UNKNOWN instead. Verify no evidence before release.
                if not any(i['id']==sid for i in self.s.store.intents()) and self.s.broker.find(sid) is None:
                    self._mark(link,'RELEASED',True);link['state']='GATE_BLOCKED_NO_ORDER';self.put(link)
                else:self._mark(link,'UNKNOWN')
                raise
            link['state']='INTENT_RECORDED';self.put(link)
            if intent['status']=='UNKNOWN':self._mark(link,'UNKNOWN')
            else:self._mark(link,'SUBMITTED')
            self._sync()
            return intent
    def _sync(self):
        with self.s.store.lock():
            reconciled=self.s._reconcile();intents={x['id']:x for x in self.s.store.intents()}
            for link in self.links():
                if link['state'] in {'RESERVATION_REJECTED','GATE_BLOCKED_NO_ORDER'}:continue
                holds={x['id']:x for x in self.ledger.status()['reservations']}
                if link['id'] not in holds:
                    self.s._block('ALLOCATION_LINK_WITHOUT_RESERVATION_REVIEW');continue
                row=intents.get(link['id'])
                if row is None:
                    # Crash between reservation and intent: hold; do not infer rejection.
                    self._mark(link,'UNKNOWN');self.s._block('RESERVED_INTENT_OUTCOME_UNRESOLVED');continue
                leg=link['leg']
                if row['instrument']!=leg['instrument'] or row['quantity']!=leg['quantity']:
                    self.s._block('ALLOCATION_INTENT_MAPPING_MISMATCH');raise AllocationBlocked('ALLOCATION_INTENT_MAPPING_MISMATCH')
                hold=holds[link['id']]
                if row['filled'] and money(row['average_price'])*row['filled']>Decimal(hold['amount_cents'])/100:
                    self.s._block('SIMULATED_FILL_EXCEEDS_RESERVED_AMOUNT');raise AllocationBlocked('SIMULATED_FILL_EXCEEDS_RESERVED_AMOUNT')
                if hold['state']=='RELEASED':
                    remaining,exits=self.s._remaining(row)
                    if remaining or row['status'] not in TERMINAL or any(x['status'] not in TERMINAL for x in exits):
                        self.s._block('RELEASED_RESERVATION_HAS_EXPOSURE');raise AllocationBlocked('RELEASED_RESERVATION_HAS_EXPOSURE')
                    continue
                if not reconciled or row['status'] in {'UNKNOWN','REQUESTED'} or 'external_observed_quantity' in row:
                    self._mark(link,'UNKNOWN');continue
                remaining,exits=self.s._remaining(row)
                if row['status'] in TERMINAL and remaining==0 and all(x['status'] in TERMINAL for x in exits) and not row.get('cleanup'):
                    self._mark(link,'RELEASED',True)
                elif row['filled']==row['quantity']:self._mark(link,'FILLED')
                elif row['filled']:self._mark(link,'PARTIAL')
                else:self._mark(link,'SUBMITTED')
            return dict(reconciled=reconciled,allocation=self.ledger.status(),simulator=self.s._status())
    def sync(self):
        with self.lock():return self._sync()
