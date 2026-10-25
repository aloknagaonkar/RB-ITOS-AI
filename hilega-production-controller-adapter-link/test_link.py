import json
from datetime import timedelta
import pytest
from fixtures import build,command,AT
from link import LinkBlocked,Link
from market_lab.hilega_sim_allocation_v1 import rows as holds
@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY');monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')
    return build(tmp_path/'fixture')
def dispatch(env):return env[3].dispatch_prepared(env[4]['id'],env[5],as_of=AT)

def test_link_requires_committed_intent_and_hold(env):
    s,b,_,link,entry,_=env
    assert len(s.store.intents())==len(holds(s.store))==1 and not b.orders()
    result=dispatch(env)
    assert result['reservation_link_verified_against_simulator']
    assert result['real_funds_reservation_verified'] is False
    assert result['adapter_result']['state']=='ACKNOWLEDGED_NOT_FILLED'
    assert s.status()['control']['mode']=='PAUSED' and s.status()['allocation']['held_total']=='6600.00'

def test_closed_boundary_never_sends_and_releases_known_unsent(env,tmp_path):
    e=build(tmp_path/'closed',closed=True);result=dispatch(e)
    assert result['adapter_result']['status']=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE'
    assert not e[1].orders() and not e[3].adapter.status()['attempts']
    assert e[0].status()['allocation']['held_total']=='0.00' and e[0].status()['control']['mode']=='PAUSED'

def test_stop_before_link_blocks_adapter(env):
    s,_,_,link,_,_=env;c=s.store.control()
    s.store.queue_stop('00000000-0000-4000-8000-000000000001',dict(action='pause',expected_version=c['version'],actor='test',position_id=None,session_date=c['session_date']))
    with pytest.raises(LinkBlocked,match='STOP_REQUESTED'):dispatch(env)
    assert not link.adapter.status()['attempts']

def test_stale_funds_and_signal_block(env):
    env[2][0]+=timedelta(seconds=61)
    with pytest.raises(Exception):dispatch(env)
    assert not env[3].adapter.status()['attempts']

def test_missing_reservation_blocks(env):
    with env[0].store.db() as d:d.execute('DELETE FROM sim_allocation_reservations')
    with pytest.raises(LinkBlocked,match='HELD_RESERVATION'):dispatch(env)
    assert not env[3].adapter.status()['attempts']

def test_wrong_reserved_quantity_blocks(env):
    s=env[0];h=holds(s.store)[0];h['quantity']=130
    with s.store.db() as d:d.execute('UPDATE sim_allocation_reservations SET data=? WHERE id=?',(json.dumps(h),h['id']))
    with pytest.raises(LinkBlocked,match='HELD_RESERVATION'):dispatch(env)

def test_wrong_contract_direction_blocks(env):
    env[5]['instrument_type']='PE'
    with pytest.raises(LinkBlocked,match='DIRECTIONAL_MAPPING'):dispatch(env)
    assert not env[3].adapter.status()['attempts']

def test_unknown_acceptance_pauses_and_retains_hold(env):
    env[3].adapter.transport.timeout_after=True;dispatch(env)
    assert env[0].status()['control']['mode']=='PAUSED' and env[0].status()['allocation']['held_total']=='6600.00'
    with pytest.raises(LinkBlocked):dispatch(env)
    assert len(env[3].adapter.transport.orders())==1

def test_partial_cancel_cannot_release_controller_hold(env):
    dispatch(env);link=env[3];oid=link.adapter.status()['requests'][0]['order_id']
    link.adapter.transport.fill(oid,20);link.cancel_fixture(env[4]['id']);link.adapter.reconcile_fixture()
    assert link.adapter.status()['requests'][0]['filled']==20
    assert env[0].status()['allocation']['held_total']=='6600.00'
    assert not env[1].orders() # fixture evidence has not become a SimBroker fill

def test_restart_does_not_translate_ack_into_controller_fill(env):
    dispatch(env);s,b,clock,link,_,_=env
    from market_lab.hilega_production_foundation.core import Service
    recovered=Service(s.store,b,lambda:clock[0]);command(recovered,'reconcile')
    link.adapter.recover()
    assert recovered.status()['control']['mode']=='PAUSED' and recovered.status()['allocation']['held_total']=='6600.00'
    assert not b.fills()

def test_active_workspace_without_isolation_marker_rejected(env):
    (env[0].store.path.parent/'ISOLATED_LINK_VALIDATION.json').unlink()
    with pytest.raises(LinkBlocked,match='ISOLATED_CONTROLLER'):Link(env[0],env[3].adapter,(env[3].module,env[3].mapping))
