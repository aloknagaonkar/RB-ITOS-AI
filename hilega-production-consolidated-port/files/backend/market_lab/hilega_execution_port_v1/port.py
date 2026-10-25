"""One public API for the validated isolated controller/adapter/ownership/release path.
No active workspace attachment or production routing. Fixture fills are explicit.
"""
import fcntl,json,os,uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from market_lab.hilega_production_foundation.core import Service,Store,SimBroker,IST
from market_lab.hilega_sim_allocation_v1 import synthetic_funds
from . import adapter as broker_adapter,mapping,availability
from .controller_link import Link
from .ownership import EvidenceLink
from .release import ReleaseConsumer

class PortBlocked(ValueError):pass
class PreparedForPort(BaseException):pass

class PreparationController(Service):
    def _submit(self,row):
        # Capture the actual public entry path AFTER its atomic hold+intent commit,
        # before any SimBroker call. There is no temporary method monkeypatch.
        if row['side']!='BUY':raise PortBlocked('LEGACY_SIMULATOR_EXIT_NOT_A_BROKER_PORT_EXIT')
        raise PreparedForPort(row)

class ClosedPort:
    def __init__(self,directory,*,mode,clock=None):
        if mode not in {'OFFLINE_FIXTURE','LIVE_CLOSED'}:raise PortBlocked('CLOSED_OR_FIXTURE_MODE_ONLY')
        self.directory=Path(directory).resolve()
        if self.directory.exists():raise PortBlocked('CREATE_REQUIRES_FRESH_DIRECTORY_USE_OPEN_FOR_RECOVERY')
        self.directory.mkdir(parents=True,mode=0o700);self.mode=mode;self.clock=clock or (lambda:datetime.now(IST))
        db=self.directory/'controller-simulation.sqlite'
        self._private_json('port.json',dict(mode=mode,scope='EXPLICIT_CONSOLIDATED_ISOLATED_SCOPE',version=1))
        self._private_json('ISOLATED_LINK_VALIDATION.json',dict(controller_db=str(db),purpose='ISOLATED_CONTROLLER_ADAPTER_VALIDATION'))
        self._initialize(worker_start=True)
    @classmethod
    def open(cls,directory,*,clock=None):
        self=cls.__new__(cls);self.directory=Path(directory).resolve();self.clock=clock or (lambda:datetime.now(IST))
        try:meta=json.loads((self.directory/'port.json').read_text())
        except (OSError,ValueError):raise PortBlocked('CONSOLIDATED_PORT_METADATA_REQUIRED') from None
        if meta!={'mode':meta.get('mode'),'scope':'EXPLICIT_CONSOLIDATED_ISOLATED_SCOPE','version':1} or meta.get('mode') not in {'OFFLINE_FIXTURE','LIVE_CLOSED'}:raise PortBlocked('PORT_METADATA_INVALID')
        self.mode=meta['mode']
        with self.lock():
            self._initialize(worker_start=True);self.adapter.recover()
        return self
    def _private_json(self,name,data):
        fd=os.open(self.directory/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump(data,f)
    def _initialize(self,*,worker_start):
        store=Store(self.directory/'controller-simulation.sqlite');self.simulator=SimBroker(store)
        self.controller=PreparationController(store,self.simulator,self.clock,worker_start=worker_start)
        scope='EXPLICIT_CONSOLIDATED_ISOLATED_SCOPE';adapter_store=broker_adapter.Store(self.directory/'adapter.sqlite',scope,self.mode)
        transport=broker_adapter.FixtureTransport(adapter_store) if self.mode=='OFFLINE_FIXTURE' else broker_adapter.HttpTransport(lambda:(_ for _ in ()).throw(PortBlocked('TOKEN_MUST_NOT_BE_READ')))
        self.adapter=broker_adapter.Adapter(adapter_store,transport);self.link=Link(self.controller,self.adapter,(broker_adapter,mapping))
        self.evidence=EvidenceLink(self.link,self.directory/'evidence.sqlite') if self.mode=='OFFLINE_FIXTURE' else None
        self.consumer=ReleaseConsumer(self.evidence) if self.evidence else None
    @contextmanager
    def lock(self):
        fd=os.open(self.directory/'port.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'a') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(f,fcntl.LOCK_UN)
    def fund_synthetic(self,cash):
        with self.lock():return synthetic_funds(self.controller,cash)
    def _command(self,action):
        c=self.controller.status()['control']
        return self.controller.command(action,request_id=str(uuid.uuid4()),expected_version=c['version'],session_date=c['session_date'],actor='CONSOLIDATED_ISOLATED_PORT')
    def resume_next_fresh(self):
        with self.lock():
            # Deliberately don't bypass legacy UNKNOWN intents after a broker
            # settlement. Full multi-cycle broker projection routing is pending.
            self._command('reconcile');return self._command('resume')
    def pause(self):
        with self.lock():return self._command('pause')
    def enter(self,*,signal_id,signal_at,contract,lots=1,synthetic_ask='100'):
        if type(lots)is not int or lots<=0:raise PortBlocked('POSITIVE_LOTS_REQUIRED')
        side=contract.get('instrument_type')
        if side not in {'CE','PE'}:raise PortBlocked('EXPLICIT_OPTION_DIRECTION_REQUIRED')
        lot=contract.get('lot_size')
        if type(lot)is not int or lot<=0:raise PortBlocked('EXPLICIT_LOT_SIZE_REQUIRED')
        with self.lock():
            try:self.controller.submit_entry(signal_id=signal_id,signal_at=signal_at,instrument='SIMULATOR|'+side,quantity=lot*lots,price=synthetic_ask)
            except PreparedForPort as prepared:row=prepared.args[0]
            else:raise PortBlocked('CONTROLLER_PREPARATION_BOUNDARY_NOT_REACHED')
            try:result=self.link.dispatch_prepared(row['id'],contract,as_of=self.clock().isoformat())
            except Exception:
                with self.controller.store.lock():self.controller._block('CONSOLIDATED_PREPARATION_REQUIRES_REVIEW')
                raise
            if self.evidence:self.evidence.register_entry(row['id'])
            return dict(controller_id=row['id'],**result)
    def _fixture(self):
        if self.mode!='OFFLINE_FIXTURE':raise PortBlocked('EXPLICIT_OFFLINE_FIXTURE_REQUIRED')
    def fixture_fill(self,request_id,cumulative):
        self._fixture()
        with self.lock():
            row=next((x for x in self.adapter.store.requests() if x['request_id']==request_id),None)
            if not row or not row.get('order_id'):raise PortBlocked('BOUND_ORDER_REQUIRED')
            self.adapter.transport.fill(row['order_id'],cumulative)
    def cancel_entry(self,controller_id):
        self._fixture()
        with self.lock():return self.link.cancel_fixture(controller_id)
    def reconcile_offline(self,snapshot):
        self._fixture()
        with self.lock():return self.evidence.reconcile(snapshot,as_of=self.clock().isoformat())
    def prepare_fixture_exit(self,controller_id,*,request_id,quantity,contract):
        self._fixture()
        if type(quantity)is not int or quantity<=0:raise PortBlocked('POSITIVE_EXIT_QUANTITY_REQUIRED')
        with self.lock():
            at=self.clock().isoformat();r=mapping.draft(contract,request_id=request_id,side='SELL',lots=1,as_of=at)
            # Explicit fixture-only partial-lot request; no production sizing claim.
            r['body']['quantity']=quantity;r['fingerprint']=broker_adapter.sha(r['body'])
            self.adapter.prepare(r,signal_id=request_id,signal_at=at,direction='BULLISH' if contract['instrument_type']=='CE' else 'BEARISH',reservation_reference=controller_id,as_of=at)
            self.evidence.register_exit(request_id,controller_id,as_of=at)
            return self.adapter.submit(request_id)
    def release_offline(self,controller_id,*,snapshot_id,request_id):
        self._fixture()
        with self.lock():return self.consumer.consume(controller_id,snapshot_id=snapshot_id,request_id=request_id,as_of=self.clock().isoformat())
    def recover(self):
        with self.lock():
            with self.controller.store.lock():self.controller._block('CONSOLIDATED_PORT_RECOVERY_REQUIRES_RECONCILIATION')
            self.adapter.recover();return self.status()
    def status(self):
        result=dict(availability=availability(),mode=self.mode,controller=self.controller.status(),adapter=self.adapter.status(),
            production_execution_enabled=False,entry_permission=False,orders_sent_to_upstox=False,
            active_workspace_attached=False,simulator_fill_count=len(self.simulator.fills()))
        if self.evidence:
            result['ownership']=self.evidence.ledger.report(as_of=self.clock().isoformat())
            result['release_consumer']=self.consumer.status()
        return result
