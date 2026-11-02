from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
import test_closed_application_coordinator_v1 as base
from test_closed_application_coordinator_v1 import env,bound_env,ready,case,flow
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_execution_port_v1 import adapter as port
from market_lab.hilega_exclusive_closed_route_v1 import enroll_candidate_route
from market_lab.hilega_execution_session_factory_v1 import ExecutionSessionFactory,worker_poll
from market_lab.hilega_private_context_v1 import PrivateContextLoader,LiveProviders,MODEL,sha,capture_owned
import market_lab.hilega_private_context_v1 as pc


def write(path,data):
    path.write_bytes(data if isinstance(data,bytes) else json.dumps(data).encode());path.chmod(0o600)


@pytest.fixture
def private(flow,tmp_path):
    e=flow;folder=tmp_path/'private-context';folder.mkdir(mode=0o700)
    pin=dict(PIN,model='HILEGA_UPSTOX_ACCOUNT_PIN_V1',broker='UPSTOX',approved_at=e['clock'][0].isoformat())
    write(folder/'pin.json',pin);write(folder/'authority.json',e['authority']);write(folder/'token',b'synthetic-token')
    config=dict(model=MODEL,production_execution_enabled=False,application_db=str(e['store'].path.resolve()),
        adapter_db=str(e['adapter_store'].path.resolve()),journal=str(e['path'].resolve()),seed_request_id=e['key'],bridge_run_id='synthetic-lease',
        pin_file=str(folder/'pin.json'),pin_sha256=sha((folder/'pin.json').read_bytes()),authority_file=str(folder/'authority.json'),
        authority_sha256=sha((folder/'authority.json').read_bytes()),broker_token_file=str(folder/'token'),broker_token_sha256=sha((folder/'token').read_bytes()),
        issued_at=(e['clock'][0]-timedelta(seconds=1)).isoformat(),expires_at=(e['clock'][0]+timedelta(hours=3)).isoformat())
    write(folder/'context.json',config)
    return e,folder,config


def loader(private):
    e,folder,config=private
    return PrivateContextLoader(e['source'],e['adapter_store'],e['path'],folder/'context.json',sha((folder/'context.json').read_bytes()),clock=lambda:e['clock'][0])


def enroll(e):enroll_candidate_route(base.session(e))


def test_direct_loader_gate_precedes_private_file_access():
    instance=PrivateContextLoader(None,None,None,Path('/nonexistent/context.json'),'0'*64)
    with patch.object(pc,'private_read',side_effect=AssertionError('No private read')):
        with pytest.raises(port.GateClosed):instance()


def test_factory_gate_does_not_read_private_context(private):
    e,folder,config=private
    with patch.object(pc,'private_read',side_effect=AssertionError('No private read')):
        result=worker_poll(e['source'],e['path'],factory=ExecutionSessionFactory(loader(private)))
    assert result['status']=='EXECUTION_SESSION_FACTORY_CLOSED_IN_CODE' and e['send'].call_count==0


def test_valid_context_assembles_without_reading_token_or_capturing(private):
    e,folder,config=private;enroll(e);original=pc.private_read
    def guarded(path,*args):
        assert Path(path)!=folder/'token','Token must be deferred'
        return original(path,*args)
    with patch.object(port,'require_live_clearance',return_value=None),patch.object(pc,'private_read',side_effect=guarded):ctx=loader(private)()
    assert ctx['adapter'].store is e['adapter_store'] and ctx['seed_request_id']==e['key']
    assert set(ctx['providers'])=={'entry','account','exit','next'} and e['send'].call_count==0
    assert base.count(e,base.STATE)==0


def test_expired_context_blocks_before_session_state(private):
    e,folder,config=private;e['clock'][0]+=timedelta(hours=4)
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(ValueError,match='PRIVATE_CONTEXT_EXPIRED_OR_FUTURE'):loader(private)()
    assert base.count(e,base.STATE)==0


def test_world_readable_authority_is_rejected(private):
    e,folder,config=private;(folder/'authority.json').chmod(0o644)
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(ValueError,match='PRIVATE_OWNER_ONLY_FILE_REQUIRED'):loader(private)()


def test_capture_key_cannot_be_reused_as_execution_authority(private):
    e,folder,config=private;write(folder/'authority.json',dict(e['authority'],key=PIN['key']))
    config['authority_sha256']=sha((folder/'authority.json').read_bytes());write(folder/'context.json',config)
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(ValueError,match='INDEPENDENT_CANDIDATE_AUTHORITY_REQUIRED'):loader(private)()


def test_wrong_lease_cannot_assemble_context(private):
    e,folder,config=private;config['bridge_run_id']='other';write(folder/'context.json',config)
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(ValueError,match='CONTEXT_SOURCE_STORE_OR_LEASE_CHANGED'):loader(private)()


def test_missing_route_owner_is_not_auto_enrolled(private):
    e,folder,config=private
    with patch.object(port,'require_live_clearance',return_value=None):
        with pytest.raises(ValueError,match='EXPLICIT_ROUTE_ENROLLMENT_REQUIRED'):loader(private)()
    assert e['send'].call_count==0 and base.count(e,base.STATE)==0


def test_token_rotation_cannot_silently_switch_context(private):
    e,folder,config=private;enroll(e)
    with patch.object(port,'require_live_clearance',return_value=None):
        ctx=loader(private)();write(folder/'token',b'different-token')
        with pytest.raises(ValueError,match='BROKER_TOKEN_FILE_CHANGED'):ctx['adapter'].transport.token_provider()
    assert e['send'].call_count==0


def test_config_change_after_loading_blocks_fresh_capture(private):
    e,folder,config=private;enroll(e)
    with patch.object(port,'require_live_clearance',return_value=None):
        ctx=loader(private)();write(folder/'context.json',dict(config,seed_request_id='changed'))
        with pytest.raises(ValueError,match='APPROVED_PRIVATE_CONFIG_CHANGED'):ctx['providers']['entry']('first')
    assert e['send'].call_count==0


def test_private_loader_connects_factory_to_two_real_candidate_cycles(private):
    e,folder,config=private;enroll(e);factory=ExecutionSessionFactory(loader(private))
    with patch.object(port,'require_live_clearance',return_value=None),patch.object(port.HttpTransport,'check',return_value=None),\
         patch.object(port.HttpTransport,'send',side_effect=lambda aid,wire:e['send'](aid,wire)),\
         patch.object(LiveProviders,'account',side_effect=lambda:base.account(e)),\
         patch.object(LiveProviders,'entry_market',side_effect=lambda:base.market(e)),\
         patch.object(pc,'capture_owned',side_effect=lambda *args:base.market(e)),\
         patch.object(base,'poll',side_effect=lambda e,**kw:worker_poll(e['source'],e['path'],factory=factory)):
        base.finish(e);base.resume_and_signal(e);base.poll(e);base.poll(e);base.finish(e)
    assert base.read_state(e)['completed_cycles']==2 and e['send'].call_count==4
    assert base.count(e,base.ARCHIVES)==2


def owned_inputs(e):
    with e['store'].db() as db:plan=json.loads(db.execute('SELECT data FROM preparation_plans').fetchone()[0])
    return plan['evidence']['contract'],plan['quantity'],base.market(e)


def test_owned_collector_uses_exact_contract_without_funds_or_atm(flow):
    e=flow;contract,quantity,bundle=owned_inputs(e);calls=[]
    from market_lab.hilega_preparation_runtime_v1.evidence import dependencies
    rules,_=dependencies()
    class Market:
        def __init__(self,token):pass
        def get(self,kind,keys=None):
            calls.append((kind,keys))
            if kind=='market':return bundle['market_before']
            if kind=='contracts':return bundle['contracts']
            if kind=='quotes':return {contract['instrument_key']:bundle['quotes'][contract['instrument_key']]}
            raise AssertionError('No funds or unrelated read')
    import market_lab.hilega_production_account_adapter_v1 as account
    with patch('market_lab.hilega_preparation_runtime_v1.collect.collectors',return_value=(rules,SimpleNamespace(MarketClient=Market),None,None)),\
         patch.object(account.Client,'get',return_value={'profile':'synthetic'}) as get,patch.object(account,'matches',return_value='synthetic'):
        value=capture_owned('synthetic-token',PIN,contract,quantity,lambda:e['clock'][0])
    assert set(value['quotes'])=={contract['instrument_key']} and 'cash_capture' not in value
    assert calls==[('market',None),('contracts',None),('quotes',[contract['instrument_key']]),('market',None)]
    assert [c.args[0] for c in get.call_args_list]==['profile','profile']


def test_private_file_symlink_is_rejected(private):
    e,folder,config=private;alias=folder/'alias.json';alias.symlink_to(folder/'context.json')
    with pytest.raises(ValueError,match='PRIVATE_ABSOLUTE_REGULAR_PATH_REQUIRED'):pc.private_read(alias)


def test_authority_file_change_after_loading_blocks_new_capture(private):
    e,folder,config=private;enroll(e)
    with patch.object(port,'require_live_clearance',return_value=None):
        ctx=loader(private)();write(folder/'authority.json',dict(e['authority'],authority_id='other'))
        with pytest.raises(ValueError,match='PRIVATE_IDENTITY_FILE_CHANGED'):ctx['providers']['next']({'role':'ENTRY'})
    assert e['send'].call_count==0
