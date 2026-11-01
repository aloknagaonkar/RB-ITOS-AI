"""One public API for the validated isolated controller/adapter/ownership/release path.
No active workspace attachment or production routing. Fixture fills are explicit.
"""
import fcntl,json,os,uuid,hashlib
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from market_lab.hilega_production_foundation.core import Service,Store,SimBroker,IST,Blocked,TERMINAL,positive_int,money
from market_lab.hilega_sim_allocation_v1 import synthetic_funds
from . import adapter as broker_adapter,mapping,availability
from .controller_link import Link
from .ownership import EvidenceLink
from .release import ReleaseConsumer

class PortBlocked(ValueError):pass
class PreparedForPort(BaseException):pass

class PreparationController(Service):
    projection_reader=None
    def _submit(self,row):
        if row['side']!='BUY':raise PortBlocked('LEGACY_SIMULATOR_EXIT_NOT_A_BROKER_PORT_EXIT')
        raise PreparedForPort(row)
    def _projection(self):
        if self.projection_reader is None:return dict(verified=False,certified_ids=[],reason='PORT_PROJECTION_NOT_READY')
        return self.projection_reader()
    def _certified(self):
        p=self._projection()
        return set(p.get('certified_ids',[])) if p.get('verified') else set()
    def _reconcile(self):
        external=[r for r in self.store.intents() if r.get('adapter_boundary')=='ISOLATED_ADAPTER_EVIDENCE_REQUIRES_OWNERSHIP_LINK']
        if not external:return super()._reconcile()
        try:
            self._honor_stop();p=self._projection()
            if not p.get('verified'):raise Blocked('BROKER_PORT_'+p.get('reason','OWNERSHIP_UNVERIFIED'))
            certified=set(p['certified_ids'])
            if any(r['id'] not in certified for r in external):raise Blocked('BROKER_PORT_POSITION_OR_EXIT_UNRESOLVED')
            from market_lab.hilega_sim_allocation_v1 import rows as reservations
            if any(h['held_cents'] for h in reservations(self.store)):raise Blocked('BROKER_PORT_RESERVATION_RELEASE_REQUIRED')
            if any(self.broker.positions().values()):raise Blocked('SIMULATOR_EXPOSURE_CANNOT_MIX_WITH_BROKER_PORT')
            for row in self.store.intents():
                if row['id'] in certified:
                    if row.get('cleanup'):row['cleanup']=False;self.store.put(row)
                    continue
                if row['status'] not in TERMINAL or row.get('cleanup') or 'external_observed_quantity' in row:raise Blocked('OTHER_EXECUTION_UNRESOLVED')
                if row['side']=='BUY' and self._remaining(row)[0]:raise Blocked('OTHER_POSITION_OPEN')
            c=self._session();c.update(reconciled=True,last_reconciled_at=self.now().isoformat())
            self.store.save_control(c);self.store.event('CONSOLIDATED_OFFLINE_PORT_RECONCILED',self.now().isoformat(),snapshot_id=p['snapshot_id'])
            return True
        except Exception:
            self._block('BROKER_PORT_RECONCILIATION_REQUIRED');return False
    def command(self,action,*,request_id,expected_version,actor,position_id=None,session_date=None):
        if action!='resume':return super().command(action,request_id=request_id,expected_version=expected_version,actor=actor,position_id=position_id,session_date=session_date)
        if not actor or len(actor)>100:raise Blocked('ACTOR_REQUIRED')
        payload=dict(action=action,expected_version=expected_version,actor=actor,position_id=position_id,session_date=session_date)
        with self.store.lock():
            self._honor_stop();c=self._session();prior,fp=self.store.previous(request_id,payload)
            if prior:return dict(prior,idempotent_replay=True,current_status=self._status())
            if expected_version!=c['version'] or session_date!=c['session_date']:raise Blocked('STALE_STATE_OR_SESSION_REFRESH_REQUIRED')
            if self.store.stop_state()['pending']:raise Blocked('DURABLE_STOP_PENDING')
            self._check_bridge_health()
            from market_lab.hilega_sim_allocation_v1 import require_ready
            require_ready(self.store,self.now());self._check_fresh(c);certified=self._certified()
            for row in self.store.intents():
                if row['id'] in certified:continue
                if row.get('cleanup') or row['status'] not in TERMINAL or 'external_observed_quantity' in row:raise Blocked('UNRESOLVED_EXECUTION_STATE')
                if row['side']=='BUY' and self._remaining(row)[0]:raise Blocked('POSITION_ALREADY_OPEN')
            c.update(mode='ARMED',version=c['version']+1,reason='OFFLINE_PORT_NEXT_FRESH_SIGNAL_ONLY',resumed_at=self.now().isoformat())
            self.store.save_control(c)
            result=dict(request_id=request_id,action=action,status=self._status())
            self.store.event('CONTROL_COMMAND',self.now().isoformat(),actor=actor,request_id=request_id,action=action,version=c['version'])
            self.store.remember(request_id,fp,result);return result
    def _status(self):
        r=super()._status();p=self._projection();r['broker_port_projection']=p
        external=[x for x in r['positions'] if x.get('adapter_boundary')=='ISOLATED_ADAPTER_EVIDENCE_REQUIRES_OWNERSHIP_LINK']
        c=r['control'];stamp=c.get('last_reconciled_at')
        fresh=stamp is not None and 0<=(self.now()-datetime.fromisoformat(stamp)).total_seconds()<=30
        gates=(not r['bridge_health']['required'] or r['bridge_health']['healthy']) and (not r['allocation']['required'] or r['allocation']['ready'])
        if external and p.get('verified') and all(x['id'] in set(p.get('certified_ids',[])) for x in external) and c['reconciled'] and fresh and gates:
            r['label']='ARMED_OFFLINE_PORT_NEXT_FRESH_SIGNAL' if r['control']['mode']=='ARMED' else 'PAUSED_OFFLINE_PORT_FLAT'
        return r
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
            external=any(r.get('adapter_boundary')=='ISOLATED_ADAPTER_EVIDENCE_REQUIRES_OWNERSHIP_LINK' for r in self.store.intents())
            if external and not self._projection().get('verified'):
                self._block('BROKER_PORT_ENTRY_EVIDENCE_STALE_OR_UNVERIFIED');raise Blocked('BROKER_PORT_ENTRY_EVIDENCE_STALE_OR_UNVERIFIED')
            self._check_fresh(c)
            if 'resumed_at' not in c or signal<=datetime.fromisoformat(c['resumed_at']):
                raise Blocked('PRE_RESUME_SIGNAL_NOT_ELIGIBLE')
            age=(self.now()-signal).total_seconds()
            if not 0<=age<=60:raise Blocked('SIGNAL_STALE_OR_FUTURE')
            certified=self._certified()
            for row in self.store.intents():
                if row['id'] in certified:continue
                if row['status'] not in TERMINAL or row.get('cleanup') or 'external_observed_quantity' in row:raise Blocked('EXPOSURE_OR_ORDER_UNRESOLVED')
                if row['side']=='BUY' and self._remaining(row)[0]:raise Blocked('POSITION_ALREADY_OPEN')
            # Allocation is durably held before the first simulator BUY transport call.
            from market_lab.hilega_sim_allocation_v1 import reserve
            intent=dict(id=sid,signal_id=signal_id,signal_at=signal_at,side='BUY',instrument=instrument,
                quantity=quantity,price=str(amount),filled=0,status='REQUESTED',session_date=c['session_date'],created_at=self.now().isoformat())
            reserve(self,sid,instrument=instrument,quantity=quantity,price=amount,intent=intent)
            return self._submit(intent)

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
        self._start_epoch()
        self.controller.projection_reader=self._projection_view
    def _start_epoch(self):
        with self.controller.store.db() as d:
            d.execute('CREATE TABLE IF NOT EXISTS port_reconciliation_epoch(id INTEGER PRIMARY KEY,data TEXT NOT NULL)')
            old=d.execute('SELECT data FROM port_reconciliation_epoch WHERE id=1').fetchone()
            generation=json.loads(old[0])['generation']+1 if old else 1
            epoch=dict(generation=generation,accepted_generation=None,snapshot_id=None,recovery_at=self.clock().isoformat())
            d.execute('INSERT OR REPLACE INTO port_reconciliation_epoch VALUES(1,?)',(json.dumps(epoch),))
    def _projection_view(self):
        def blocked(reason):return dict(verified=False,certified_ids=[],reason=reason,production_execution_enabled=False)
        if self.evidence is None:return blocked('NO_OFFLINE_OWNERSHIP_SOURCE')
        try:
            with self.controller.store.db() as d:
                e=d.execute('SELECT data FROM port_reconciliation_epoch WHERE id=1').fetchone()
                epoch=json.loads(e[0]) if e else None
                tables={r[0] for r in d.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                receipts=[json.loads(x[0]) for x in d.execute('SELECT data FROM broker_fixture_release_receipts')] if 'broker_fixture_release_receipts' in tables else []
                settlements={x[0]:json.loads(x[1]) for x in d.execute('SELECT controller_id,data FROM broker_fixture_settlements')} if 'broker_fixture_settlements' in tables else {}
                holds={json.loads(x[0])['id']:json.loads(x[0]) for x in d.execute('SELECT data FROM sim_allocation_reservations')}
            if not epoch or epoch['accepted_generation']!=epoch['generation']:return blocked('NEW_SNAPSHOT_REQUIRED_AFTER_RECOVERY')
            report=self.evidence.ledger.report(as_of=self.clock().isoformat());state=report['state']
            if state.get('exposure_verified') is not True or state.get('status')!='RECONCILED_OFFLINE_FIXTURE':return blocked('OWNERSHIP_STALE_OR_UNVERIFIED')
            if state.get('pending_orders'):return blocked('OWNED_ORDER_PENDING')
            if state.get('snapshot_id')!=epoch['snapshot_id']:return blocked('SNAPSHOT_EPOCH_MISMATCH')
            with self.evidence.tx() as d:
                source=d.execute('SELECT data FROM verified_snapshot WHERE id=1').fetchone()
                source=json.loads(source[0]) if source else None
            if not source or source['snapshot_id']!=state['snapshot_id']:return blocked('OWNERSHIP_SOURCE_MISMATCH')
            with self.evidence.ledger.db() as d:
                source_hash=d.execute('SELECT hash FROM own_snapshots WHERE account=? AND id=?',(self.evidence.scope,source['snapshot_id'])).fetchone()
                if not source_hash or source_hash[0]!=broker_adapter.sha(source):return blocked('OWNERSHIP_SOURCE_CHANGED')
                original_hashes=dict(d.execute('SELECT id,hash FROM own_snapshots WHERE account=?',(self.evidence.scope,)))
            linked={x['request_id'] for x in self.evidence.links()}
            if any(r['request_id'] not in linked or not r.get('order_id') for r in self.adapter.store.requests()):return blocked('ADAPTER_REQUEST_UNRESOLVED')
            positions={p['entry_id']:p for p in state['positions']};certified=[]
            for receipt in receipts:
                cid=receipt['controller_id'];settlement=settlements.get(cid);hold=holds.get(cid)
                if not settlement or not hold or hold['held_cents']!=0 or settlement['remaining']!=0:return blocked('SETTLEMENT_OR_RELEASE_MISMATCH')
                if original_hashes.get(receipt['snapshot_id'])!=receipt['source_fingerprint'] or settlement['source_fingerprint']!=receipt['source_fingerprint']:return blocked('SETTLEMENT_EVIDENCE_CHANGED')
                p=positions.get(settlement['ownership_entry_id'])
                if not p or p['remaining']!=0:return blocked('SETTLED_ENTRY_HAS_EXPOSURE')
                certified.append(cid)
            return dict(verified=True,certified_ids=certified,snapshot_id=state['snapshot_id'],remaining=sum(p['remaining'] for p in state['positions']),production_execution_enabled=False)
        except Exception:return blocked('PROJECTION_EVIDENCE_UNAVAILABLE')
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
    def resume_next_fresh(self,*,expected_version=None,session_date=None,request_id=None):
        with self.lock():
            self._command('reconcile');c=self.controller.status()['control']
            return self.controller.command('resume',request_id=request_id or str(uuid.uuid4()),expected_version=c['version'] if expected_version is None else expected_version,session_date=c['session_date'] if session_date is None else session_date,actor='CONSOLIDATED_ISOLATED_PORT')
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
        with self.lock():
            try:result=self.evidence.reconcile(snapshot,as_of=self.clock().isoformat())
            except Exception:
                with self.controller.store.lock():self.controller._block('BROKER_PORT_EVIDENCE_REJECTED')
                raise
            if result['reconciliation']['status'] not in {'RECONCILED_OFFLINE_FIXTURE','IDEMPOTENT_REPLAY'}:
                with self.controller.store.lock():self.controller._block('BROKER_PORT_EVIDENCE_REJECTED')
            with self.controller.store.db() as d:
                epoch=json.loads(d.execute('SELECT data FROM port_reconciliation_epoch WHERE id=1').fetchone()[0])
                if result['reconciliation']['status']=='RECONCILED_OFFLINE_FIXTURE' and mapping.stamp(snapshot['observed_at'])>=mapping.stamp(epoch['recovery_at']):
                    epoch.update(accepted_generation=epoch['generation'],snapshot_id=snapshot['snapshot_id'])
                else:epoch.update(accepted_generation=None,snapshot_id=None)
                d.execute('UPDATE port_reconciliation_epoch SET data=? WHERE id=1',(json.dumps(epoch),))
            return result
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
            self.adapter.recover();self._start_epoch();return self.status()
    def status(self):
        result=dict(availability=availability(),mode=self.mode,controller=self.controller.status(),adapter=self.adapter.status(),
            production_execution_enabled=False,entry_permission=False,orders_sent_to_upstox=False,
            active_workspace_attached=False,simulator_fill_count=len(self.simulator.fills()))
        if self.evidence:
            result['ownership']=self.evidence.ledger.report(as_of=self.clock().isoformat())
            result['release_consumer']=self.consumer.status()
        return result
