"""Application-facing integration with synthetic signed inputs; VM only."""
import copy
import hashlib
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import pytest
from market_lab.hilega_production_foundation.core import Store,SimBroker,Service,Blocked,encode
from market_lab.hilega_preparation_runtime_v1 import summary,ensure_route
from market_lab.hilega_preparation_runtime_v1.source import Source
from market_lab.hilega_preparation_runtime_v1.evidence import Blocked as EvidenceBlocked
from market_lab.hilega_production_simulator_bridge_v1 import POLICY,VERSION
from hilega_application_preparation_fixtures import bundle,PIN,T,ts,resign,resign_cash

BULL='ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21'
ARM='PATH1_ARMED_RSI_CROSS_EMA3_UP'


def append(path,names,*,at=None,policy=POLICY,version=VERSION,reconstructed=False):
    old=[json.loads(x) for x in path.read_text().splitlines() if x]
    at=at or ts()
    row=dict(sequence=len(old)+1,previous_hash=old[-1]['record_hash'] if old else None,
        stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(policy_id=policy,strategy_version=version,
        reconstructed=reconstructed,decision_timestamp=at,accepted_events=names,
        event_details=[dict(event_type=n,event_time=at,entry_time=at,qualified_signal_time=None) for n in names]))
    row['record_hash']=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
    with path.open('a') as f:f.write(json.dumps(row)+'\n')


def command(s,action):
    c=s.status()['control']
    return s.command(action,request_id=str(uuid.uuid4()),expected_version=c['version'],
        session_date=c['session_date'],actor='APPLICATION_INTEGRATION_FIXTURE')


@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_EXECUTION_ROUTE','PREPARATION_ONLY')
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY')
    monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')
    clock=[T-timedelta(seconds=1)]
    store=Store(tmp_path/'application.sqlite');s=Service(store,SimBroker(store),lambda:clock[0])
    from market_lab.hilega_production_bridge_health_v1 import MODEL
    health=dict(model=MODEL,required=True,run_id='synthetic-lease',pid=1,phase='RUNNING',
                heartbeat_at=ts(-1),source_at=ts(-1),session_date='2026-10-26')
    with store.db() as db:db.execute('INSERT INTO sim_bridge_health VALUES(1,?)',(encode(health),))
    command(s,'reconcile');command(s,'resume');clock[0]=T+timedelta(seconds=3)
    health.update(heartbeat_at=ts(2),source_at=ts())
    with store.db() as db:db.execute('UPDATE sim_bridge_health SET data=? WHERE id=1',(encode(health),))
    adapter=tmp_path/'adapter.sqlite'
    with sqlite3.connect(adapter) as db:
        db.executescript('CREATE TABLE meta(id INTEGER PRIMARY KEY,data TEXT); CREATE TABLE requests(id TEXT); CREATE TABLE attempts(id TEXT); CREATE TABLE receipts(id TEXT);')
        db.execute('INSERT INTO meta VALUES(1,?)',(encode(dict(scope=PIN['scope'],mode='LIVE_CLOSED')),))
    monkeypatch.setenv('HILEGA_PREPARATION_ADAPTER_DB',str(adapter))
    monkeypatch.setenv('HILEGA_PRODUCTION_SIM_DB',str(store.path))
    data=bundle();calls=[]
    def provider():calls.append(1);return copy.deepcopy(data),PIN
    source=Source(s,run_id='synthetic-lease',provider=provider)
    path=tmp_path/'strategy.jsonl';path.write_text('')
    source.run_source_once(path)
    return dict(s=s,store=store,source=source,path=path,data=data,clock=clock,provider=provider,calls=calls)


def counts(env):
    with env['store'].db() as db:
        return tuple(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in (
            'preparation_plans','preparation_shadow_holds','preparation_outbox','intents','sim_orders','sim_fills'))


def process(env):
    append(env['path'],[BULL]);return env['source'].run_source_once(env['path'])


def test_actual_source_dispatch_persists_application_plan(env):
    process(env)
    assert counts(env)==(1,1,1,0,0,0)
    assert env['store'].control()['mode']=='PAUSED'
    result=summary(env['store'])
    assert result['unresolved_preparation_count']==1 and result['shadow_held_cents']==660000
    assert result['orders_sent'] is False and result['production_execution_enabled'] is False
    with env['store'].db() as db:
        plan=json.loads(db.execute('SELECT data FROM preparation_plans').fetchone()[0])
        out=json.loads(db.execute('SELECT data FROM preparation_outbox').fetchone()[0])
        assert plan['source_record_hash'] and plan['evidence']['bundle_fingerprint']
        assert out['id']==plan['id'] and out['request_body'] is None
        assert out['status']=='NON_EXECUTABLE_PRICING_POLICY_PENDING'


def test_replay_and_repeated_event_no_second_hold(env):
    process(env);env['source'].run_source_once(env['path'])
    append(env['path'],[BULL]);env['source'].run_source_once(env['path'])
    assert counts(env)==(1,1,1,0,0,0) and len(env['calls'])==1


def test_armed_candidate_not_entry(env):
    append(env['path'],[ARM]);env['source'].run_source_once(env['path'])
    assert counts(env)==(0,0,0,0,0,0) and not env['calls']


def test_first_scan_baselines_existing_history(env):
    with env['store'].db() as db:db.execute('DELETE FROM preparation_source')
    append(env['path'],[BULL]);result=env['source'].run_source_once(env['path'])
    assert result['status']=='BASELINED_WAIT_NEXT_CONFIRMED_SIGNAL'
    assert counts(env)==(0,0,0,0,0,0)


def test_pause_before_signal_no_account_reads(env):
    command(env['s'],'pause');process(env)
    assert counts(env)==(0,0,0,0,0,0) and not env['calls']


def test_pause_during_slow_evidence_collection(env):
    def provider():command(env['s'],'pause');return copy.deepcopy(env['data']),PIN
    env['source'].provider=provider;process(env)
    assert counts(env)==(0,0,0,0,0,0)
    assert 'CONTROLLER_PAUSED' in summary(env['store'])['last_outcome']['reasons']


def test_zero_real_cash_no_synthetic_fallback(env):
    b=env['data']
    for f in (b['cash_before_market'],b['cash_after_market'],b['cash_capture']['funds_before'],b['cash_capture']['funds_after']):f['cash_available_to_trade']='0'
    resign_cash(b);process(env)
    assert counts(env)==(0,0,0,0,0,0)
    assert 'NO_CASH_CAPACITY' in summary(env['store'])['last_outcome']['reasons']
    assert env['store'].control()['mode']=='PAUSED'


def test_stale_evidence_blocks_and_consumes_event(env):
    env['clock'][0]=T+timedelta(seconds=31);process(env)
    assert counts(env)==(0,0,0,0,0,0)
    assert env['store'].control()['mode']=='PAUSED'
    assert summary(env['store'])['last_outcome']['status']=='BLOCKED'


def test_invalid_signature_never_creates_intent(env):
    env['data']['spot_initial']=24999;process(env)
    assert counts(env)==(0,0,0,0,0,0)
    assert summary(env['store'])['last_outcome']['reasons']==['BUNDLE_SIGNATURE_INVALID']


def test_provider_failure_never_submits(env):
    def failure():raise RuntimeError('private details must not be logged')
    env['source'].provider=failure;process(env)
    outcome=summary(env['store'])['last_outcome']
    assert outcome['reasons']==['EVIDENCE_PROVIDER_UNAVAILABLE']
    assert counts(env)==(0,0,0,0,0,0)


@pytest.mark.parametrize('stage',['AFTER_PLAN_INSERT','BEFORE_COMMIT'])
def test_interruption_atomic_plan_hold_cursor(env,stage):
    class Interrupted(BaseException):pass
    def crash(at):
        if at==stage:raise Interrupted()
    env['source'].checkpoint=crash
    with pytest.raises(Interrupted):process(env)
    assert counts(env)==(0,0,0,0,0,0)
    with env['store'].db() as db:
        assert json.loads(db.execute('SELECT data FROM preparation_source').fetchone()[0])['sequence']==0


def test_lost_commit_response_restart_retains_plan_and_pauses(env):
    class Lost(BaseException):pass
    def crash(at):
        if at=='AFTER_COMMIT':raise Lost()
    env['source'].checkpoint=crash
    with pytest.raises(Lost):process(env)
    s=Service(Store(env['store'].path),SimBroker(env['store']),lambda:env['clock'][0])
    source=Source(s,run_id='synthetic-lease',provider=env['provider'])
    source.run_source_once(env['path'])
    assert counts(env)==(1,1,1,0,0,0) and s.store.control()['mode']=='PAUSED'
    with pytest.raises(Blocked,match='UNSENT_PREPARATION_REQUIRES_REVIEW'):command(s,'resume')


def test_existing_service_cannot_bypass_route_to_simulator(env):
    with pytest.raises(Blocked,match='CONFIRMED_PREPARATION_SOURCE_REQUIRED'):
        env['s'].submit_entry(signal_id='direct',signal_at=ts(),instrument='SIMULATOR|CE',quantity=65,price='100')
    assert counts(env)==(0,0,0,0,0,0)


def test_environment_cannot_downgrade_persisted_route(env,monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_EXECUTION_ROUTE','SIMULATOR')
    with pytest.raises(ValueError,match='PERSISTED_EXECUTION_ROUTE_MISMATCH'):
        Service(Store(env['store'].path),SimBroker(env['store']))


def test_pending_plan_blocks_service_reconcile_and_resume(env):
    process(env)
    assert env['s']._reconcile() is False
    with pytest.raises(Blocked,match='UNSENT_PREPARATION_REQUIRES_REVIEW'):command(env['s'],'resume')
    assert summary(env['store'])['shadow_held_cents']==660000


def test_corrupted_source_rejected(env):
    append(env['path'],[BULL]);rows=env['path'].read_text().replace('PROCESSED','CHANGED')
    env['path'].write_text(rows)
    with pytest.raises(Blocked,match='SOURCE_CHAIN_INVALID'):env['source'].run_source_once(env['path'])
    assert counts(env)==(0,0,0,0,0,0)


def test_reconstructed_signal_ignored(env):
    append(env['path'],[BULL],reconstructed=True);env['source'].run_source_once(env['path'])
    assert counts(env)==(0,0,0,0,0,0) and not env['calls']


def test_two_workers_one_plan(env):
    append(env['path'],[BULL])
    second=Source(env['s'],run_id='synthetic-lease',provider=env['provider'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda source:source.run_source_once(env['path']),[env['source'],second]))
    assert counts(env)==(1,1,1,0,0,0)


def test_authenticated_application_status_has_preparation_state(env,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from market_lab.hilega_production_workspace_v1 import router
    monkeypatch.setenv('HILEGA_PRODUCTION_CONTROL_TOKEN','x'*40)
    monkeypatch.delenv('HILEGA_PRODUCTION_CONTROL_TOKEN_FILE',raising=False)
    process(env)
    app=FastAPI();app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/api/hilega-production/execution-preparation').status_code==401
        response=client.get('/api/hilega-production/execution-preparation',headers={'Authorization':'Bearer '+'x'*40})
        assert response.status_code==200
        assert response.json()['unresolved_preparation_count']==1
        assert PIN['scope'] not in response.text and PIN['key'] not in response.text
        assert response.json()['production_execution_enabled'] is False


def test_stop_queued_just_before_commit_rolls_back(env):
    def stop(at):
        if at=='BEFORE_TRANSACTION':env['store'].queue_stop(str(uuid.uuid4()),dict(action='pause'))
    env['source'].checkpoint=stop
    with pytest.raises(EvidenceBlocked,match='CONTROL_CHANGED_OR_STOP_PENDING'):process(env)
    assert counts(env)==(0,0,0,0,0,0)


def test_short_commit_delay_revalidates_without_false_fingerprint_conflict(env):
    def advance(at):
        if at=='BEFORE_TRANSACTION':env['clock'][0]+=timedelta(milliseconds=10)
    env['source'].checkpoint=advance;process(env)
    assert counts(env)==(1,1,1,0,0,0)


def test_quote_expires_before_transaction_no_plan(env):
    def advance(at):
        if at=='BEFORE_TRANSACTION':env['clock'][0]+=timedelta(seconds=11)
    env['source'].checkpoint=advance
    with pytest.raises(EvidenceBlocked,match='EVIDENCE_CHANGED_OR_STALE_BEFORE_COMMIT'):process(env)
    assert counts(env)==(0,0,0,0,0,0)


def test_adapter_changes_before_commit_no_plan(env,monkeypatch):
    import os
    def change(at):
        if at=='BEFORE_TRANSACTION':
            with sqlite3.connect(os.environ['HILEGA_PREPARATION_ADAPTER_DB']) as db:
                db.execute("INSERT INTO requests VALUES('synthetic-new-activity')")
    env['source'].checkpoint=change
    with pytest.raises(EvidenceBlocked,match='ADAPTER_ACTIVITY_CHANGED_BEFORE_COMMIT'):process(env)
    assert counts(env)==(0,0,0,0,0,0)


def test_next_session_does_not_clear_plan_or_shadow_hold(env):
    process(env);env['clock'][0]+=timedelta(days=1)
    s=Service(Store(env['store'].path),SimBroker(env['store']),lambda:env['clock'][0])
    assert s.status()['control']['mode']=='PAUSED'
    assert counts(env)==(1,1,1,0,0,0)
    with pytest.raises(Blocked,match='UNSENT_PREPARATION_REQUIRES_REVIEW'):command(s,'resume')


def test_exit_is_not_misreported_as_real_flat(env):
    with pytest.raises(Blocked,match='LIVE_EXIT_NOT_IMPLEMENTED'):command(env['s'],'flatten')
    assert counts(env)==(0,0,0,0,0,0)


def test_status_remains_json_serializable(env):
    status=env['s'].status()
    assert isinstance(status['pending_entry_orders'],bool)
    json.dumps(status)


def test_application_report_exposes_actual_preparation_route(env,monkeypatch):
    from market_lab import hilega_production_workspace_v1 as workspace
    process(env)
    result=workspace.report()
    assert result['source']=='EVIDENCE_PREPARATION_ONLY'
    assert result['broker_execution_port']['active_execution_route']=='APPLICATION_PREPARATION_ONLY'
    assert result['application_preparation']['unresolved_preparation_count']==1
    assert result['positions']==[] and result['orders']==[]
    json.dumps(result)
