"""Synthetic VM-only validation; never a claim of live controller/broker readiness."""
import copy
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from preparation import Preparation, Blocked, FLAGS
from scenarios import build, control
from market_lab.hilega_production_foundation.core import encode


@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY')
    monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')
    return build(tmp_path/'stage')


def counts(port):
    with port.store.db() as db:
        return tuple(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in (
            'staged_intents','staged_reservations','staged_adapter_requests','sim_orders','sim_fills'))


def rejected(env,reason,plan=None):
    port,_,original=env
    with pytest.raises((Blocked,ValueError),match=reason):
        port.prepare(**(plan if plan is not None else original))
    assert counts(port)==(0,0,0,0,0)


def test_atomic_real_format_preparation_no_transport(env):
    port,_,plan=env
    result=port.prepare(**plan)
    assert result['instrument']=='NSE_FO|12345' and result['quantity']==65
    assert result['reserved_cents']==660000
    assert counts(port)==(1,1,1,0,0)
    assert port.store.control()['mode']=='PAUSED'
    for key in FLAGS:assert result[key] is False
    with port.store.db() as db:
        intent=json.loads(db.execute('SELECT data FROM staged_intents').fetchone()[0])
        hold=json.loads(db.execute('SELECT data FROM staged_reservations').fetchone()[0])
        request=json.loads(db.execute('SELECT data FROM staged_adapter_requests').fetchone()[0])
        assert intent['id']==hold['id']==request['reservation_reference']==request['request_id']
        assert request['draft']['body']['instrument_token']==intent['instrument']==hold['instrument']
        assert request['draft']['submission_enabled'] is False
        assert request['transport_available'] is False
        assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('attempts','receipts')").fetchone()[0]==0


def test_bearish_maps_to_pe(env):
    port,_,plan=env
    plan['direction']='BEARISH';plan['contract']['instrument_type']='PE'
    assert port.prepare(**plan)['status']=='STAGED_PREPARED_UNSENT'


def test_duplicate_is_historical_only(env):
    port,_,plan=env;port.prepare(**plan)
    replay=port.prepare(**plan)
    assert replay['historical_only'] and replay['current_control_mode']=='PAUSED'
    assert counts(port)==(1,1,1,0,0)


def test_duplicate_changed_plan_conflicts(env):
    port,_,plan=env;port.prepare(**plan)
    plan['quote']['ask']='100.05'
    with pytest.raises(Blocked,match='SIGNAL_PAYLOAD_CONFLICT'):port.prepare(**plan)
    assert counts(port)==(1,1,1,0,0)


def test_second_signal_blocked(env):
    port,_,plan=env;port.prepare(**plan)
    plan['signal_id']='other';plan['expected_version']=port.store.control()['version']
    with pytest.raises(Blocked,match='TRADING_PAUSED_OR_STOP_PENDING'):port.prepare(**plan)


def test_pause_observed(env):
    control(env[0],'pause')
    env[2]['expected_version']=env[0].store.control()['version']
    rejected(env,'TRADING_PAUSED_OR_STOP_PENDING')


def test_stale_version(env):
    env[2]['expected_version']-=1
    rejected(env,'STALE_CONTROL_VERSION')


def test_wrong_session(env):
    env[2]['session_date']='2026-10-25'
    rejected(env,'SESSION_MISMATCH')


def test_pre_resume_signal(env):
    env[2]['signal_at']=(env[1][0]-timedelta(seconds=1)).isoformat()
    rejected(env,'PRE_RESUME_SIGNAL_NOT_ELIGIBLE')


@pytest.mark.parametrize('seconds',[-61,1])
def test_stale_or_future_signal(env,seconds):
    env[2]['signal_at']=(env[1][0]+timedelta(seconds=seconds)).isoformat()
    rejected(env,'SIGNAL_STALE_FUTURE_OR_WRONG_SESSION')


def test_stale_contract(env):
    env[2]['contract_at']=(env[1][0]-timedelta(seconds=31)).isoformat()
    rejected(env,'CONTRACT_STALE_FUTURE_OR_WRONG_SESSION')


def test_stale_quote(env):
    env[2]['quote']['at']=(env[1][0]-timedelta(seconds=6)).isoformat()
    rejected(env,'QUOTE_STALE_FUTURE_OR_WRONG_SESSION')


def test_quote_instrument_mismatch(env):
    env[2]['quote']['instrument']='NSE_FO|999'
    rejected(env,'QUOTE_INSTRUMENT_MISMATCH')


def test_simulator_instrument_rejected(env):
    env[2]['contract']['instrument_key']='SIMULATOR|CE'
    rejected(env,'EXACT_BROKER_INSTRUMENT_REQUIRED')


def test_wrong_direction(env):
    env[2]['contract']['instrument_type']='PE'
    rejected(env,'CONTRACT_DIRECTION_MISMATCH')


def test_expired_contract(env):
    env[2]['contract']['expiry']='2026-10-25'
    rejected(env,'CONTRACT_EXPIRED')


@pytest.mark.parametrize('field,value,reason',[
    ('ask','0','INVALID_QUOTE_OR_TICK'),('bid','101','INVALID_QUOTE_OR_TICK'),
    ('bid','90','STAGED_SPREAD_LIMIT_EXCEEDED'),('tick_rupees','0','INVALID_QUOTE_OR_TICK'),
    ('evidence_mode','LIVE_PINNED','STAGED_QUOTE_EVIDENCE_REQUIRED')])
def test_quote_quality(env,field,value,reason):
    env[2]['quote'][field]=value
    rejected(env,reason)


def test_tick_rounding_is_in_reservation(env):
    port,_,plan=env;plan['quote']['ask']='100.01'
    result=port.prepare(**plan)
    assert result['reserved_cents']==660325


def test_half_cash_cap(env):
    port,_,_=env
    with port.store.db() as db:
        config=json.loads(db.execute('SELECT data FROM sim_allocation_config WHERE id=1').fetchone()[0])
        config['funds']['cash']='1000'
        db.execute('UPDATE sim_allocation_config SET data=? WHERE id=1',(encode(config),))
    rejected(env,'STAGED_HALF_CASH_CAP_EXCEEDED')


def test_funds_stale(env):
    port,clock,_=env
    with port.store.db() as db:
        config=json.loads(db.execute('SELECT data FROM sim_allocation_config WHERE id=1').fetchone()[0])
        config['funds']['at']=(clock[0]-timedelta(seconds=31)).isoformat()
        db.execute('UPDATE sim_allocation_config SET data=? WHERE id=1',(encode(config),))
    rejected(env,'FUNDS_STALE_FUTURE_OR_WRONG_SESSION')


def test_wrong_worker_lease(env):
    env[2]['bridge_run_id']='wrong'
    rejected(env,'SIM_BRIDGE_LEASE_MISMATCH')


def test_stale_worker(env):
    port,clock,_=env
    with port.store.db() as db:
        row=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
        row['heartbeat_at']=(clock[0]-timedelta(seconds=16)).isoformat()
        db.execute('UPDATE sim_bridge_health SET data=? WHERE id=1',(encode(row),))
    rejected(env,'STAGED_BRIDGE_HEALTH_REQUIRED')


@pytest.mark.parametrize('stage',['AFTER_INTENT_INSERT','AFTER_RESERVATION_INSERT','BEFORE_COMMIT'])
def test_interruption_rolls_back_whole_plan(env,stage):
    port,_,plan=env
    class Interrupted(BaseException):pass
    def crash(at):
        if at==stage:raise Interrupted()
    port.checkpoint=crash
    with pytest.raises(Interrupted):port.prepare(**plan)
    assert counts(port)==(0,0,0,0,0)
    assert port.store.control()['mode']=='ARMED'


def test_response_lost_after_commit_restart_does_not_repeat(env):
    port,clock,plan=env
    class Lost(BaseException):pass
    def crash(stage):
        if stage=='AFTER_COMMIT':raise Lost()
    port.checkpoint=crash
    with pytest.raises(Lost):port.prepare(**plan)
    reopened=Preparation(port.directory,clock=lambda:clock[0],reopen=True)
    assert reopened.store.control()['mode']=='PAUSED'
    assert reopened.prepare(**plan)['historical_only']
    assert counts(reopened)==(1,1,1,0,0)
    with pytest.raises(Blocked,match='STAGED_PREPARATION_REMAINS_UNRESOLVED'):control(reopened,'resume')


def test_stop_arrives_before_transaction(env):
    port,_,plan=env
    def stop(stage):
        if stage=='BEFORE_ATOMIC_TRANSACTION':
            port.store.queue_stop(str(uuid.uuid4()),dict(action='pause'))
    port.checkpoint=stop
    rejected(env,'CONTROL_CHANGED_OR_STOP_PENDING')


def test_time_advances_before_commit(env):
    port,clock,_=env
    def advance(stage):
        if stage=='BEFORE_ATOMIC_TRANSACTION':clock[0]+=timedelta(seconds=6)
    port.checkpoint=advance
    rejected(env,'QUOTE_STALE_FUTURE_OR_WRONG_SESSION')


def test_concurrent_same_signal_one_reservation(env):
    port,_,plan=env
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:port.prepare(**copy.deepcopy(plan)),range(2)))
    assert sorted(r['historical_only'] for r in results)==[False,True]
    assert counts(port)==(1,1,1,0,0)


def test_existing_workspace_directory_rejected(env):
    with pytest.raises(Blocked,match='FRESH_STAGE_DIRECTORY_REQUIRED'):
        Preparation(env[0].directory)


def test_submit_and_cancel_disabled(env):
    for action in ('submit','cancel'):
        with pytest.raises(Blocked):getattr(env[0],action)('anything')
    assert counts(env[0])==(0,0,0,0,0)


def test_changed_funds_during_preparation_blocked(env):
    port,_,_=env
    def change(stage):
        if stage=='BEFORE_ATOMIC_TRANSACTION':
            with port.store.db() as db:
                config=json.loads(db.execute('SELECT data FROM sim_allocation_config WHERE id=1').fetchone()[0])
                config['funds']['cash']='0'
                db.execute('UPDATE sim_allocation_config SET data=? WHERE id=1',(encode(config),))
    port.checkpoint=change
    rejected(env,'FUNDS_EVIDENCE_CHANGED')


def test_legacy_execution_state_cannot_mix(env):
    port,_,_=env
    port.store.put(dict(id='legacy',side='BUY',instrument='SIMULATOR|CE',quantity=65,
                        status='REQUESTED',filled=0,price='100'))
    rejected(env,'LEGACY_SIMULATOR_STATE_CANNOT_MIX')


def test_naive_signal_rejected(env):
    env[2]['signal_at']='2026-10-26T09:25:00'
    rejected(env,'AWARE_TIMESTAMP_REQUIRED')


def test_unresolved_stage_blocks_reconcile(env):
    port,_,plan=env;port.prepare(**plan)
    with pytest.raises(Blocked,match='STAGED_PREPARATION_REMAINS_UNRESOLVED'):control(port,'reconcile')
    assert counts(port)==(1,1,1,0,0)


def test_next_session_retains_stage_and_hold(env):
    port,clock,plan=env;port.prepare(**plan)
    clock[0]+=timedelta(days=1)
    reopened=Preparation(port.directory,clock=lambda:clock[0],reopen=True)
    assert reopened.store.control()['mode']=='PAUSED'
    assert counts(reopened)==(1,1,1,0,0)
    with pytest.raises(Blocked,match='STAGED_PREPARATION_REMAINS_UNRESOLVED'):control(reopened,'resume')
