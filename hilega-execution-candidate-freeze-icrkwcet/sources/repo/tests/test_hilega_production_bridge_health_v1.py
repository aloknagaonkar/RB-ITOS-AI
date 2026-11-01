"""Offline heartbeat, control-gate and watchdog tests. No broker requests."""
from datetime import datetime,timedelta
import json,os,uuid
import pytest
from market_lab.hilega_production_foundation.core import Store,Service,SimBroker,Blocked
from market_lab.hilega_production_simulator_bridge_v1 import Bridge,POLICY,VERSION
from market_lab import hilega_production_bridge_health_v1 as h

@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')
    monkeypatch.setenv('HILEGA_PRODUCTION_BROKER_OBSERVE','0')
@pytest.fixture
def env(tmp_path):
    clock=[datetime.fromisoformat('2026-10-25T09:24:59+05:30')]
    store=Store(tmp_path/'sim.sqlite');s=Service(store,SimBroker(store),lambda:clock[0])
    return s,clock,tmp_path

def cmd(s,name,**kw):
    c=s.status()['control'];return s.command(name,request_id=str(uuid.uuid4()),expected_version=c['version'],session_date=c['session_date'],actor='fixture-operator',**kw)
def ready(env):
    s,clock,path=env;run=h.claim(s);h.heartbeat(s,run,source_at=clock[0].isoformat())
    cmd(s,'reconcile');cmd(s,'resume');clock[0]+=timedelta(seconds=1)
    return run

def buy(env,run):
    s,clock,path=env
    return s.submit_entry(signal_id='fresh-'+str(uuid.uuid4()),signal_at=clock[0].isoformat(),instrument='SIMULATOR|CE',quantity=65,price=100,bridge_run_id=run)

def test_default_disabled_preserves_existing_simulator(env):
    assert h.summary(env[0].store,env[0].now())['required'] is False

def test_enabled_without_worker_blocks_resume(env,monkeypatch):
    s,clock,path=env;monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','1');cmd(s,'reconcile')
    with pytest.raises(Blocked,match='SIM_BRIDGE_NOT_STARTED'):cmd(s,'resume')
def test_starting_lease_cannot_resume(env):
    s,clock,path=env;h.claim(s);cmd(s,'reconcile')
    with pytest.raises(Blocked,match='SIM_BRIDGE_STARTING'):cmd(s,'resume')
def test_missing_source_blocks_resume(env):
    s,clock,path=env;run=h.claim(s);h.heartbeat(s,run,source_at=None);cmd(s,'reconcile')
    with pytest.raises(Blocked,match='SIM_BRIDGE_SOURCE_NOT_READY'):cmd(s,'resume')
def test_healthy_lease_allows_explicit_resume_and_owner_entry(env):
    run=ready(env);r=buy(env,run)
    assert r['status']=='OPEN' and env[0].status()['bridge_health']['healthy']
def test_no_lease_id_cannot_bypass_required_guard(env):
    ready(env)
    with pytest.raises(Blocked,match='SIM_BRIDGE_LEASE_MISMATCH'):buy(env,None)
    assert env[0].broker.orders()==[] and env[0].status()['control']['mode']=='PAUSED'
def test_wrong_lease_id_cannot_submit(env):
    ready(env)
    with pytest.raises(Blocked,match='SIM_BRIDGE_LEASE_MISMATCH'):buy(env,'wrong-owner')
    assert env[0].broker.orders()==[]
def test_required_state_survives_environment_flag_off(env,monkeypatch):
    ready(env);monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')
    assert h.summary(env[0].store,env[0].now())['required'] is True

def test_stale_heartbeat_gate_blocks_before_watchdog_poll(env):
    run=ready(env);env[1][0]+=timedelta(seconds=16)
    with pytest.raises(Blocked,match='SIM_BRIDGE_HEARTBEAT_STALE'):buy(env,run)
    assert not env[0].broker.orders() and env[0].status()['control']['mode']=='PAUSED'
def test_watchdog_durably_pauses_without_browser(env):
    ready(env);env[1][0]+=timedelta(seconds=16);env[0].watch_bridge_health()
    assert env[0].status()['control']['mode']=='PAUSED'
    assert env[0].status()['control']['reason']=='SIM_BRIDGE_HEARTBEAT_STALE'
def test_watchdog_cancels_pending_buy(env):
    run=ready(env);r=buy(env,run);env[1][0]+=timedelta(seconds=16);env[0].watch_bridge_health()
    assert env[0].broker.find(r['id'])['status']=='CANCELLED'
    assert env[0].broker.positions()['SIMULATOR|CE']==0

def test_watchdog_retains_established_position(env):
    run=ready(env);r=buy(env,run);env[0].broker.fill(r['id'],65,100);cmd(env[0],'reconcile')
    env[1][0]+=timedelta(seconds=16);env[0].watch_bridge_health()
    assert env[0].broker.positions()['SIMULATOR|CE']==65 and env[0].status()['control']['mode']=='PAUSED'
def test_fill_during_watchdog_cancel_flattened(env):
    run=ready(env);r=buy(env,run);env[0].broker.fill_on_cancel=20
    env[1][0]+=timedelta(seconds=16);env[0].watch_bridge_health()
    assert env[0].broker.positions()['SIMULATOR|CE']==0
    sells=[i for i in env[0].store.intents() if i['side']=='SELL'];assert len(sells)==1 and sells[0]['quantity']==20

def test_heartbeat_recovery_does_not_resume(env):
    run=ready(env);env[1][0]+=timedelta(seconds=16);env[0].watch_bridge_health()
    h.heartbeat(env[0],run,source_at=env[0].now().isoformat())
    assert env[0].status()['bridge_health']['healthy'] and env[0].status()['control']['mode']=='PAUSED'
def test_explicit_resume_after_recovery_required(env):
    run=ready(env);env[1][0]+=timedelta(seconds=16);env[0].watch_bridge_health()
    h.heartbeat(env[0],run,source_at=env[0].now().isoformat());cmd(env[0],'reconcile');cmd(env[0],'resume')
    env[1][0]+=timedelta(seconds=1);assert buy(env,run)['status']=='OPEN'
def test_repeated_watchdog_does_not_bump_versions(env):
    ready(env);env[1][0]+=timedelta(seconds=16);env[0].watch_bridge_health();v=env[0].status()['control']['version']
    env[0].watch_bridge_health();assert env[0].status()['control']['version']==v

def test_manual_pause_reason_is_not_overwritten(env):
    ready(env);cmd(env[0],'pause');env[1][0]+=timedelta(seconds=16);env[0].watch_bridge_health()
    assert env[0].status()['control']['reason']=='OPERATOR_PAUSE'
def test_live_worker_with_stale_market_source_blocks(env):
    run=ready(env);source=env[0].now().isoformat();env[1][0]+=timedelta(seconds=391)
    state=h.heartbeat(env[0],run,source_at=source)
    assert state['status']=='SOURCE_STALE_OR_FUTURE';env[0].watch_bridge_health()
    assert env[0].status()['control']['mode']=='PAUSED'
def test_future_source_is_not_healthy(env):
    run=ready(env);state=h.heartbeat(env[0],run,source_at=(env[0].now()+timedelta(seconds=1)).isoformat())
    assert state['status']=='SOURCE_STALE_OR_FUTURE'
def test_future_heartbeat_clock_change_blocks(env):
    ready(env);env[1][0]-=timedelta(seconds=2)
    assert env[0].status()['bridge_health']['status']=='CLOCK_OR_FUTURE_HEARTBEAT'
def test_new_session_needs_new_claim_and_explicit_resume(env):
    run=ready(env);env[1][0]+=timedelta(days=1);h.heartbeat(env[0],run,source_at=env[0].now().isoformat())
    assert env[0].status()['control']['mode']=='PAUSED'
    assert env[0].status()['bridge_health']['status']=='SESSION_MISMATCH'

def test_stale_process_cannot_overwrite_new_owner(env):
    first=ready(env);second=h.claim(env[0]);h.heartbeat(env[0],second,source_at=env[0].now().isoformat())
    with pytest.raises(h.HealthBlocked,match='LEASE_REPLACED'):h.heartbeat(env[0],first,source_at=env[0].now().isoformat())
    assert h.finish(env[0],first) is False
    assert env[0].status()['bridge_health']['instance']==second[:8]
def test_single_worker_lifetime_lock(tmp_path):
    path=tmp_path/'sim.sqlite'
    with h.worker_lock(path):
        with pytest.raises(h.HealthBlocked,match='ALREADY_RUNNING'):
            with h.worker_lock(path):pass
    with h.worker_lock(path):pass

def test_graceful_finish_immediately_blocks_and_cancels(env):
    run=ready(env);r=buy(env,run);assert h.finish(env[0],run)
    assert env[0].broker.find(r['id'])['status']=='CANCELLED'
    assert env[0].status()['bridge_health']['status']=='STOPPED'
    with pytest.raises(Blocked):cmd(env[0],'resume')
def test_exits_remain_available_with_stale_bridge(env):
    run=ready(env);r=buy(env,run);env[0].broker.fill(r['id'],65,100);cmd(env[0],'reconcile')
    env[1][0]+=timedelta(seconds=16);env[0].watch_bridge_health();cmd(env[0],'exit',position_id=r['id'])
    assert env[0].broker.positions()['SIMULATOR|CE']==0

def test_full_owner_token_not_exposed_in_status_or_events(env):
    run=ready(env);s=env[0];assert run not in json.dumps(s.status()) and run not in json.dumps(s.store.events())
def test_unreadable_health_evidence_fails_closed(env):
    s,clock,path=env
    with s.store.db() as d:d.execute('INSERT INTO sim_bridge_health VALUES(1,?)',('{invalid',))
    assert s.status()['bridge_health']['required'] and not s.status()['bridge_health']['healthy']
    cmd(s,'reconcile')
    with pytest.raises(Blocked):cmd(s,'resume')

def test_bridge_uses_current_lease_at_submission(env):
    run=ready(env);s,clock,path=env;bridge=Bridge(s,path/'ownership.sqlite',auto_fill_entries=True,run_id=run)
    at=clock[0].replace(second=0,microsecond=0).isoformat();clock[0]=datetime.fromisoformat(at)
    rec=dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(policy_id=POLICY,strategy_version=VERSION,reconstructed=False,
        decision_timestamp=at,accepted_events=['ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21'],event_details=[dict(
        event_type='ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21',event_time=at,entry_time=at)]))
    out=bridge.process(rec);assert out['ownership_status']['positions'][0]['entry_filled']==65

def test_source_error_records_do_not_keep_source_healthy():
    records=[dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(policy_id=POLICY,strategy_version=VERSION,reconstructed=False,decision_timestamp='2026-10-25T09:20:00+05:30')),
        dict(stage='DIRECTIONAL_DECISION',status='WAITING',event_time='2026-10-25T09:30:00+05:30',payload=dict(policy_id=POLICY,strategy_version=VERSION,decision_timestamp='2026-10-25T09:30:00+05:30'))]
    assert h.source_timestamp(records,POLICY,VERSION)=='2026-10-25T09:20:00+05:30'
def test_reconstructed_records_do_not_refresh_source():
    r=dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(policy_id=POLICY,strategy_version=VERSION,reconstructed=True,decision_timestamp='2026-10-25T09:30:00+05:30'))
    assert h.source_timestamp([r],POLICY,VERSION) is None

def test_api_background_watchdog_needs_no_browser_requests(env,monkeypatch):
    import asyncio,time
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from market_lab import hilega_production_workspace_v1 as w
    run=ready(env);s,clock,path=env
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY')
    monkeypatch.setattr(w,'service',lambda:s)
    original=asyncio.sleep
    async def fast_sleep(delay):await original(0.01 if delay==5 else delay)
    monkeypatch.setattr(w.asyncio,'sleep',fast_sleep)
    @asynccontextmanager
    async def life(app):
        async with w.workspace_lifespan():yield
    with TestClient(FastAPI(lifespan=life)):
        cmd(s,'reconcile');cmd(s,'resume');clock[0]+=timedelta(seconds=16)
        deadline=time.monotonic()+2
        while s.status()['control']['mode']!='PAUSED' and time.monotonic()<deadline:time.sleep(.01)
        assert s.status()['control']['mode']=='PAUSED'
        assert s.status()['control']['reason']=='SIM_BRIDGE_HEARTBEAT_STALE'
