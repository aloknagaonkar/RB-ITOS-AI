"""Isolated integration contract: installed Service holds -> closed/injected adapter."""
import hashlib,importlib.util,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent

def load_adapter(root=ROOT):
    dependencies=json.loads(Path(__file__).with_name('dependencies.json').read_text())
    for relative,fingerprint in dependencies.items():
        path=root/relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=fingerprint:raise ValueError('DEPENDENCY_CHANGED_'+relative)
    folder=root/'hilega-production-broker-adapter-closed'
    def load(name,path):
        spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module
    mapping=load('provider_mapping',folder/'provider_mapping.py')
    adapter=load('controller_link_adapter',folder/'adapter.py')
    return adapter,mapping

class LinkBlocked(ValueError):pass

class Link:
    def __init__(self,service,adapter,modules):
        self.service=service;self.adapter=adapter;self.module,self.mapping=modules
        if type(adapter)is not self.module.Adapter:raise LinkBlocked('EXACT_CLOSED_ADAPTER_REQUIRED')
        # This integration test must never attach to the normal workspace DB.
        marker=service.store.path.parent/'ISOLATED_LINK_VALIDATION.json'
        try:config=json.loads(marker.read_text())
        except (OSError,ValueError):raise LinkBlocked('ISOLATED_CONTROLLER_REQUIRED') from None
        if config!={'controller_db':str(service.store.path.resolve()),'purpose':'ISOLATED_CONTROLLER_ADAPTER_VALIDATION'}:raise LinkBlocked('ISOLATED_CONTROLLER_REQUIRED')
        if adapter.store.path.parent.resolve()!=service.store.path.parent.resolve():raise LinkBlocked('ISOLATED_COLOCATED_ADAPTER_REQUIRED')
    def dispatch_prepared(self,entry_id,contract,*,as_of):
        s=self.service
        with s.store.lock():
            c=s._session()
            if c['mode']!='ARMED' or s.store.stop_state()['pending']:raise LinkBlocked('CONTROLLER_PAUSED_OR_STOP_REQUESTED')
            s._check_fresh(c);s._check_bridge_health()
            rows=s.store.intents();entry=next((x for x in rows if x['id']==entry_id),None)
            if entry is None or entry['side']!='BUY' or entry['status']!='REQUESTED' or entry['filled']!=0:raise LinkBlocked('UNSUBMITTED_PREPARED_CONTROLLER_ENTRY_REQUIRED')
            if s.broker.find(entry_id) is not None:raise LinkBlocked('SIMULATOR_ORDER_ALREADY_SUBMITTED')
            from market_lab.hilega_sim_allocation_v1 import rows as holds,config,money
            hold=next((x for x in holds(s.store) if x['id']==entry_id),None)
            if hold is None or hold['held_cents']<=0 or hold['instrument']!=entry['instrument'] or hold['quantity']!=entry['quantity']:raise LinkBlocked('MATCHING_HELD_RESERVATION_REQUIRED')
            funds=config(s.store).get('funds')
            if not funds or not 0<=(s.now()-self.mapping.stamp(funds['at'])).total_seconds()<=30:raise LinkBlocked('SYNTHETIC_FUNDS_STALE')
            required=(money(entry['price'])*entry['quantity']+money(config(s.store)['buffer']))*100
            if hold['held_cents']<required:raise LinkBlocked('RESERVATION_TOO_SMALL')
            if entry['signal_at']<=c.get('resumed_at','') or not 0<=(s.now()-self.mapping.stamp(entry['signal_at'])).total_seconds()<=60:raise LinkBlocked('SIGNAL_STALE_OR_PRE_RESUME')
            side={'SIMULATOR|CE':'CE','SIMULATOR|PE':'PE'}.get(entry['instrument'])
            if side is None or contract.get('instrument_type')!=side:raise LinkBlocked('EXPLICIT_FIXTURE_DIRECTIONAL_MAPPING_REQUIRED')
            quantity=contract.get('lot_size')
            if type(quantity)is not int or quantity<=0 or entry['quantity']%quantity:raise LinkBlocked('LOT_QUANTITY_MAPPING_INVALID')
            request=self.mapping.draft(contract,request_id=entry_id,side='BUY',lots=entry['quantity']//quantity,as_of=as_of)
            self.adapter.prepare(request,signal_id=entry['signal_id'],signal_at=entry['signal_at'],direction='BULLISH' if side=='CE' else 'BEARISH',reservation_reference=hold['id'],as_of=as_of)
            result=self.adapter.submit(entry_id)
            # Result/attempt is not a simulator execution or fill. Unknown/injected
            # evidence must pause the controller and retain its full reservation.
            if result.get('status')=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE':
                entry.update(status='CANCELLED',not_submitted=True,cleanup=False,adapter_boundary='CLOSED_NO_TRANSPORT')
                s.store.put(entry);s._block('CLOSED_BROKER_BOUNDARY_NO_SUBMISSION');s._reconcile()
            else:
                entry.update(status='UNKNOWN',adapter_boundary='ISOLATED_ADAPTER_EVIDENCE_REQUIRES_OWNERSHIP_LINK')
                s.store.put(entry);s._block('BROKER_ADAPTER_OUTCOME_REQUIRES_OWNERSHIP_LINK')
            s.store.event('CLOSED_ADAPTER_LINK_RESULT',s.now().isoformat(),intent_id=entry_id,adapter_mode=self.adapter.store.mode,production_execution_enabled=False)
            return dict(adapter_result=result,controller_entry=entry,production_execution_enabled=False,orders_sent_to_upstox=False,
                reservation_link_verified_against_simulator=True,real_funds_reservation_verified=False,live_contract_mapping_verified=False)
    def cancel_fixture(self,entry_id):
        if self.adapter.store.mode!='OFFLINE_FIXTURE':raise LinkBlocked('FIXTURE_ONLY_CANCEL_VALIDATION')
        return self.adapter.cancel(entry_id)
