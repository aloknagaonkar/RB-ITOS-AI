from contextlib import asynccontextmanager
from pathlib import Path
import uuid
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from market_lab import hilega_production_workspace_v1 as w

TOKEN='test-control-token-01234567890123456789'
HEAD={'Authorization':'Bearer '+TOKEN}
@pytest.fixture
def env(monkeypatch,tmp_path):
    monkeypatch.setenv('HILEGA_PRODUCTION_CONTROL_TOKEN',TOKEN)
    monkeypatch.delenv('HILEGA_PRODUCTION_CONTROL_TOKEN_FILE',raising=False)
    monkeypatch.setenv('HILEGA_PRODUCTION_SIM_DB',str(tmp_path/'simulation.sqlite'))
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY')
    return monkeypatch

def client():
    app=FastAPI();app.include_router(w.router);return TestClient(app)

def command(c,action,**kw):
    return c.post('/api/hilega-production/commands',headers=HEAD,json=dict(action=action,
        request_id=kw.pop('request_id',str(uuid.uuid4())),confirmation='SIMULATION_ONLY',**kw))

def test_unauthenticated_status_denied(env):
    assert client().get('/api/hilega-production/status').status_code==401

def test_unauthenticated_pause_denied(env):
    assert client().post('/api/hilega-production/commands',json={}).status_code==401

def test_unconfigured_key_no_state_read(env):
    env.delenv('HILEGA_PRODUCTION_CONTROL_TOKEN')
    assert client().get('/api/hilega-production/status',headers=HEAD).status_code==503

def test_disabled_never_controls_worker(env):
    env.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','DISABLED')
    c=client();v=c.get('/api/hilega-production/status',headers=HEAD).json()
    assert v['workspace_mode']=='DISABLED' and not v['strategy_worker_controlled']
    assert command(c,'pause').status_code==409

def test_no_live_mode(env):
    env.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','LIVE')
    assert client().get('/api/hilega-production/status',headers=HEAD).status_code==503

def test_no_fabricated_cash_or_pnl(env):
    v=client().get('/api/hilega-production/status',headers=HEAD).json()
    assert v['available_cash'] is None and v['live_pnl'] is None
    assert v['production_execution_enabled'] is False and v['positions']==[]
    assert all(r['status']=='NOT_VALIDATED' for r in v['readiness_checks'])

def test_pause_reflected_in_same_status(env):
    c=client();assert command(c,'pause').status_code==200
    v=c.get('/api/hilega-production/status',headers=HEAD).json()
    assert v['control']['mode']=='PAUSED'

def test_resume_stale_version_rejected(env):
    c=client();v=c.get('/api/hilega-production/status',headers=HEAD).json()['control']
    command(c,'reconcile');command(c,'pause')
    assert command(c,'resume',expected_version=v['version'],session_date=v['session_date']).status_code==409

def test_cross_origin_control_rejected(env):
    r=client().get('/api/hilega-production/status',headers={**HEAD,'Origin':'https://another.example'})
    assert r.status_code==403

def test_token_file_supported(env,tmp_path):
    p=tmp_path/'control.token';p.write_text(TOKEN)
    env.setenv('HILEGA_PRODUCTION_CONTROL_TOKEN_FILE',str(p))
    assert client().get('/api/hilega-production/status',headers=HEAD).status_code==200

def test_confirmation_required(env):
    r=client().post('/api/hilega-production/commands',headers=HEAD,json=dict(action='pause',request_id=str(uuid.uuid4()),confirmation='LIVE'))
    assert r.status_code==400

def test_no_fake_external_close(env):
    s=w.service()
    # API must not claim to have reconciled a live account from the fake broker.
    r=client().get('/api/hilega-production/status',headers=HEAD).json()
    assert not r['broker_connected'] and r['source']=='SIMULATOR_ONLY'

def test_lifespan_recovery_pauses_previously_armed(env):
    @asynccontextmanager
    async def life(app):
        async with w.workspace_lifespan():yield
    s=w.service()
    with s.store.lock():
        s._reconcile();c=s.store.control();c['mode']='ARMED';s.store.save_control(c)
    app=FastAPI(lifespan=life);app.include_router(w.router)
    with TestClient(app) as c:
        state=c.get('/api/hilega-production/status',headers=HEAD).json()
        assert state['control']['mode']=='PAUSED'
