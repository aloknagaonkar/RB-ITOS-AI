from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import Mock
import pytest
from durable_closed_handoff_v1 import record_closed_handoff, TABLE
from test_hilega_application_preparation_v1 import env, process, counts
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN, resign_cash

@pytest.fixture
def ready(bound_env):
    e=bound_env;process(e)
    e['key']=e['adapter_store'].requests()[0]['request_id']
    e['version']=e['store'].control()['version']
    return e

def run(e,**kwargs):
    options=dict(journal=e['path'],request_id=e['key'],
        capture_provider=lambda:deepcopy(e['data']),clock=lambda:e['clock'][0],
        expected_version=e['version'],bridge_run_id='synthetic-lease')
    options.update(kwargs)
    return record_closed_handoff(e['store'],e['adapter_store'].path,PIN,**options)

def receipt_count(e):
    with e['store'].db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(TABLE,)).fetchone():return 0
        return db.execute('SELECT COUNT(*) FROM '+TABLE).fetchone()[0]

def assert_original(e):
    assert counts(e)==(1,1,1,0,0,0)
    assert len(e['adapter_store'].requests())==1
    with e['adapter_store'].tx() as db:
        assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0]==0

def test_committed_application_preparation_gets_one_closed_receipt(ready):
    result=run(ready)
    assert receipt_count(ready)==1
    assert result['current_checks_reexecuted'] is True
    assert result['record']['execution_permission']=='CLOSED_IN_CODE'
    assert result['record']['production_execution_enabled'] is False
    assert_original(ready)

def test_delayed_replay_needs_no_new_capture(ready):
    first=run(ready)
    provider=Mock(side_effect=AssertionError('No capture on durable replay'))
    later=run(ready,capture_provider=provider,clock=lambda:ready['clock'][0]+timedelta(hours=2))
    assert later['record']==first['record'] and later['idempotent_replay'] is True
    assert later['current_checks_reexecuted'] is False
    provider.assert_not_called();assert_original(ready)

@pytest.mark.parametrize('point',['AFTER_HANDOFF_INSERT','BEFORE_HANDOFF_COMMIT'])
def test_interruption_rolls_back_closed_receipt_only(ready,point):
    class Interrupted(BaseException):pass
    def stop(at):
        if at==point:raise Interrupted()
    with pytest.raises(Interrupted):run(ready,checkpoint=stop)
    assert receipt_count(ready)==0;assert_original(ready)
    assert run(ready)['idempotent_replay'] is False

def test_concurrent_callers_commit_one_receipt(ready):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:run(ready),range(2)))
    assert sorted(r['idempotent_replay'] for r in results)==[False,True]
    assert receipt_count(ready)==1;assert_original(ready)

@pytest.mark.parametrize('mutation,reason',[
 ('version','HANDOFF_CONTROL_VERSION_CHANGED'),
 ('manual_pause','PREPARATION_REVIEW_PAUSE_REQUIRED'),
 ('stop','HANDOFF_STOP_PENDING'),
 ('lease','HANDOFF_BRIDGE_NOT_CURRENT'),
])
def test_current_controller_change_blocks(ready,mutation,reason):
    with ready['store'].db() as db:
        if mutation=='stop':db.execute('UPDATE sim_stop_state SET generation=generation+1 WHERE id=1')
        elif mutation=='lease':
            row=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
            row['run_id']='other';db.execute('UPDATE sim_bridge_health SET data=? WHERE id=1',(json.dumps(row),))
        else:
            row=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
            if mutation=='version':row['version']+=1
            else:row['reason']='MANUAL_PAUSE'
            db.execute('UPDATE control SET data=? WHERE id=1',(json.dumps(row),))
    with pytest.raises(ValueError,match=reason):run(ready)
    assert receipt_count(ready)==0;assert_original(ready)

def test_changed_control_during_capture_is_seen(ready):
    def provider():
        with ready['store'].db() as db:
            row=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0]);row['version']+=1
            db.execute('UPDATE control SET data=? WHERE id=1',(json.dumps(row),))
        return deepcopy(ready['data'])
    with pytest.raises(ValueError,match='HANDOFF_CONTROL_VERSION_CHANGED'):run(ready,capture_provider=provider)
    assert receipt_count(ready)==0

def test_forged_fresh_capture_cannot_create_receipt(ready):
    bundle=deepcopy(ready['data']);bundle['spot_initial']=1
    with pytest.raises(ValueError,match='BUNDLE_SIGNATURE_INVALID'):run(ready,capture_provider=lambda:bundle)
    assert receipt_count(ready)==0

def test_fresh_cash_shortfall_does_not_change_existing_hold(ready):
    bundle=deepcopy(ready['data'])
    for funds in (bundle['cash_before_market'],bundle['cash_after_market'],
                  bundle['cash_capture']['funds_before'],bundle['cash_capture']['funds_after']):
        funds['cash_available_to_trade']='1'
    resign_cash(bundle)
    with pytest.raises(ValueError):run(ready,capture_provider=lambda:bundle)
    assert receipt_count(ready)==0;assert_original(ready)

def test_stale_clock_blocks_new_review(ready):
    with pytest.raises(ValueError):run(ready,clock=lambda:ready['clock'][0]+timedelta(minutes=2))
    assert receipt_count(ready)==0

def test_expiry_before_commit_rolls_back(ready):
    now=ready['clock'][0]
    def checkpoint(at):
        if at=='BEFORE_HANDOFF_COMMIT':ready['clock'][0]=now+timedelta(minutes=2)
    with pytest.raises(ValueError):run(ready,checkpoint=checkpoint)
    assert receipt_count(ready)==0;assert_original(ready)

def test_tampered_persisted_receipt_blocks_replay(ready):
    run(ready)
    with ready['store'].db() as db:
        row=json.loads(db.execute('SELECT data FROM '+TABLE).fetchone()[0]);row['signature']='changed'
        db.execute('UPDATE '+TABLE+' SET data=?',(json.dumps(row),))
    with pytest.raises(ValueError,match='HANDOFF_RECEIPT_SIGNATURE_INVALID'):run(ready)
    assert_original(ready)

def test_unknown_request_is_not_replaced(ready):
    with ready['adapter_store'].tx() as db:
        row=json.loads(db.execute('SELECT data FROM requests').fetchone()[0]);row['state']='UNKNOWN'
        db.execute('UPDATE requests SET data=?',(json.dumps(row),))
    with pytest.raises(ValueError,match='BOUND_REQUEST_CHANGED_OR_ALREADY_ATTEMPTED'):run(ready)
    assert receipt_count(ready)==0;assert_original(ready)

def test_closed_exit_is_not_adopted(ready):
    with ready['store'].db() as db:
        db.execute('CREATE TABLE preparation_exit_dispatch(id TEXT,data TEXT)')
        db.execute('INSERT INTO preparation_exit_dispatch VALUES(?,?)',('exit','{}'))
    with pytest.raises(ValueError,match='HANDOFF_CLOSED_EXIT_REQUIRES_REVIEW'):run(ready)
    assert receipt_count(ready)==0;assert_original(ready)

def test_new_signed_capture_is_bound_to_receipt(ready):
    from hilega_application_preparation_fixtures import resign
    now=ready['clock'][0]+timedelta(seconds=5)
    bundle=deepcopy(ready['data'])
    bundle.update(started_at=now.isoformat(),completed_at=now.isoformat(),snapshot_id='fresh-handoff-bundle')
    bundle['cash_capture'].update(started_at=now.isoformat(),completed_at=now.isoformat(),snapshot_id='fresh-handoff-cash')
    for q in bundle['quotes'].values():
        q['timestamp']=now.isoformat()
        if 'last_trade_time' in q:q['last_trade_time']=now.isoformat()
    resign_cash(bundle)
    result=run(ready,capture_provider=lambda:bundle,clock=lambda:now)
    assert result['record']['current_review']['reviewed_at']==now.isoformat()
    assert receipt_count(ready)==1;assert_original(ready)

def test_current_ask_above_original_limit_blocks(ready):
    from hilega_application_preparation_fixtures import resign
    bundle=deepcopy(ready['data'])
    for q in bundle['quotes'].values():
        if 'depth' in q:q['depth']['sell'][0]['price']=100.05
    resign(bundle)
    with pytest.raises(ValueError,match='HANDOFF_CURRENT_ASK_EXCEEDS_EXISTING_LIMIT'):
        run(ready,capture_provider=lambda:bundle)
    assert receipt_count(ready)==0;assert_original(ready)

def test_receipt_does_not_open_actual_order_gate(ready):
    from market_lab.hilega_execution_port_v1.adapter import Adapter, HttpTransport
    run(ready)
    token=Mock(side_effect=AssertionError('No token access'))
    adapter=Adapter(ready['adapter_store'],HttpTransport(token))
    result=adapter.submit(ready['key'])
    assert result['status']=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE'
    token.assert_not_called();assert_original(ready)
