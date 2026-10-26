from datetime import datetime,timedelta
import json,uuid
import pytest
from market_lab.hilega_production_foundation.core import Store,Service,SimBroker,Blocked
from market_lab import hilega_sim_allocation_v1 as allocation
AT=datetime.fromisoformat('2026-10-26T09:25:00+05:30')
def cmd(s,action,rid=None,**kwargs):
    c=s.status()['control']
    return s.command(action,request_id=rid or str(uuid.uuid4()),expected_version=c['version'],session_date=c['session_date'],actor='integration-test',**kwargs)
@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY')
    monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')
    monkeypatch.setenv('HILEGA_PRODUCTION_BROKER_OBSERVE','0')
    clock=[AT-timedelta(seconds=1)];store=Store(tmp_path/'sim.sqlite');broker=SimBroker(store);s=Service(store,broker,lambda:clock[0])
    allocation.synthetic_funds(s,'100000');cmd(s,'reconcile');cmd(s,'resume');clock[0]=AT
    return s,broker,clock

def entry(env):return env[0].submit_entry(signal_id='fresh',signal_at=env[2][0].isoformat(),instrument='SIMULATOR|CE',quantity=65,price='100')
def payload(s,action='pause'):
    c=s.store.control()
    return dict(action=action,expected_version=c['version'],session_date=c['session_date'],actor='integration-test',position_id=None)

def test_atomic_intent_and_hold_visible_before_transport(env):
    s,b,_=env
    def before():
        rows=s.store.intents();holds=allocation.rows(s.store)
        assert len(rows)==len(holds)==1 and rows[0]['id']==holds[0]['id']
        assert rows[0]['status']=='REQUESTED' and holds[0]['held_cents']==660000
    b.before_accept=before;entry(env)

def test_atomic_failure_rolls_back_hold_and_intent(env,monkeypatch):
    s,b,_=env;original=allocation.encode
    def broken(value):
        if isinstance(value,dict) and value.get('signal_id')=='fresh':raise SystemExit('synthetic interruption inside transaction')
        return original(value)
    monkeypatch.setattr(allocation,'encode',broken)
    with pytest.raises(SystemExit):entry(env)
    assert not allocation.rows(s.store) and not s.store.intents() and not b.orders()

def test_durable_stop_vetoes_entry_without_waiting_for_handler(env):
    s,b,_=env;s.store.queue_stop(str(uuid.uuid4()),payload(s))
    with pytest.raises(Blocked,match='TRADING_PAUSED'):entry(env)
    assert not b.orders() and s.status()['durable_execution']['stop_requested']

def test_stop_after_atomic_prepare_cancels_without_transport(env,monkeypatch):
    s,b,_=env;original=s._submit
    def stop_then_submit(row):
        s.store.queue_stop(str(uuid.uuid4()),payload(s));return original(row)
    monkeypatch.setattr(s,'_submit',stop_then_submit);row=entry(env)
    assert row['not_submitted'] and row['status']=='CANCELLED' and not b.orders()
    assert allocation.summary(s.store,s.now())['held_total']=='0.00'
    assert s.status()['control']['mode']=='PAUSED'

def test_stop_during_acceptance_cleans_pending_order(env):
    s,b,_=env;b.before_accept=lambda:s.store.queue_stop(str(uuid.uuid4()),payload(s))
    row=entry(env)
    assert s.status()['control']['mode']=='PAUSED'
    assert next(i for i in s.store.intents() if i['id']==row['id'])['status']=='CANCELLED'
    assert allocation.summary(s.store,s.now())['held_total']=='0.00'

def test_duplicate_pause_command_does_not_leave_pending_stop(env):
    s,_,_=env;rid=str(uuid.uuid4());p=payload(s)
    s.command(request_id=rid,**p);first=s.store.stop_state()
    s.command(request_id=rid,**p)
    assert s.store.stop_state()==first and not first['pending']

def test_stop_request_id_conflict_rejected(env):
    s,_,_=env;rid=str(uuid.uuid4());p=payload(s);s.store.queue_stop(rid,p)
    with pytest.raises(Blocked):s.store.queue_stop(rid,dict(p,action='flatten'))

def test_restart_consumes_stop_without_auto_resume(env):
    s,b,clock=env;s.store.queue_stop(str(uuid.uuid4()),payload(s))
    other=Service(s.store,b,lambda:clock[0]);cmd(other,'reconcile')
    assert other.status()['control']['mode']=='PAUSED' and not other.store.stop_state()['pending']
    assert not b.orders()

def test_pause_established_holds_then_manual_exit_releases(env):
    s,b,_=env;row=entry(env);b.fill(row['id'],65,'100');cmd(s,'reconcile');cmd(s,'pause')
    assert allocation.summary(s.store,s.now())['held_total']=='6600.00'
    cmd(s,'exit',position_id=row['id'])
    assert allocation.summary(s.store,s.now())['held_total']=='0.00' and not any(b.positions().values())

def test_unknown_acceptance_hold_cannot_be_released_without_evidence(env,monkeypatch):
    s,b,_=env
    def interrupted(row):raise SystemExit('after atomic preparation')
    monkeypatch.setattr(s,'_submit',interrupted)
    with pytest.raises(SystemExit):entry(env)
    assert len(s.store.intents())==len(allocation.rows(s.store))==1
    cmd(s,'reconcile')
    assert not s.status()['control']['reconciled'] and allocation.summary(s.store,s.now())['held_total']=='6600.00'
    assert not b.orders()

def test_workspace_routes_expose_same_durable_controls(env,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from market_lab import hilega_production_workspace_v1 as workspace
    s,_,_=env;monkeypatch.setenv('HILEGA_PRODUCTION_CONTROL_TOKEN','x'*48);monkeypatch.delenv('HILEGA_PRODUCTION_CONTROL_TOKEN_FILE',raising=False)
    monkeypatch.setattr(workspace,'service',lambda:s)
    monkeypatch.setattr(workspace.broker_observation,'display',lambda:dict(status='DISABLED'))
    app=FastAPI();app.include_router(workspace.router)
    with TestClient(app) as client:
        headers={'Authorization':'Bearer '+'x'*48}
        before=client.get('/api/hilega-production/status',headers=headers).json()
        assert before['durable_execution']['atomic_reservation_intent'] is True
        c=before['control']
        r=client.post('/api/hilega-production/commands',headers=headers,json=dict(action='pause',request_id=str(uuid.uuid4()),expected_version=c['version'],session_date=c['session_date'],confirmation='SIMULATION_ONLY'))
        assert r.status_code==200 and r.json()['snapshot']['control']['mode']=='PAUSED'
        assert r.json()['snapshot']['durable_execution']['stop_requested'] is False
        assert r.json()['snapshot']['production_execution_enabled'] is False

def test_unacknowledged_flatten_request_survives_restart(env):
    s,b,clock=env;row=entry(env);b.fill(row['id'],65,'100');cmd(s,'reconcile')
    s.store.queue_stop(str(uuid.uuid4()),payload(s,'flatten'))
    other=Service(s.store,b,lambda:clock[0]);cmd(other,'reconcile')
    assert other.status()['control']['mode']=='PAUSED' and not any(b.positions().values())
    assert allocation.summary(s.store,s.now())['held_total']=='0.00'
