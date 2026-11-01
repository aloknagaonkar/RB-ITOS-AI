from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from unittest.mock import Mock
import pytest
from test_hilega_application_preparation_v1 import env
from test_hilega_atomic_disabled_binding_v1 import bound_env
from test_durable_closed_handoff_v1 import ready
from test_existing_request_attempt_v1 import case
from test_application_lifecycle_candidate_v1 import owned
from test_application_cycle_close_v1 import flat,next_review
from history_aware_preparation_v1 import prepare_next_disabled,ADMISSIONS
from application_cycle_close_v1 import ACTIVE,ARCHIVES
from hilega_application_preparation_fixtures import PIN,resign_cash
from market_lab.hilega_preparation_runtime_v1.cash_reservation import verify_row
from market_lab.hilega_production_simulator_bridge_v1 import verified_records,accepted

def run(e,**kwargs):
    options=dict(journal=e['path'],sequence=e['next_sequence'],
        account_capture=e['next_account'],market_bundle=e['next_market'],fee_buffer_cents=10000,
        clock=lambda:e['clock'][0],expected_version=e['next_version'],bridge_run_id='synthetic-lease')
    options.update(kwargs)
    return prepare_next_disabled(e['store'],e['adapter'],PIN,e['authority'],**options)

def count(e,table):
    with e['store'].db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():return 0
        return db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]

def assert_no_next(e):
    assert not any(count(e,t) for t in ACTIVE)
    assert count(e,ADMISSIONS)==0
    assert len(e['adapter_store'].requests())==2
    assert e['store'].control()['mode']=='ARMED'

def test_next_disabled_buy_preserves_closed_cycle_and_creates_one_hold(next_review):
    e=next_review;old=e['adapter_store'].requests()
    with e['adapter_store'].tx() as db:before=list(db.execute('SELECT id,data FROM receipts ORDER BY id'))
    result=run(e);key=result['request_id']
    assert result['new_preparation_created'] is True and result['new_buy_attempt_created'] is False
    assert result['production_execution_enabled'] is False
    rows=e['adapter_store'].requests();new=next(r for r in rows if r['request_id']==key)
    assert [r for r in rows if r['request_id']!=key]==old
    assert new['state']=='PREPARED' and new['order_id'] is None
    assert new['draft']['body']['transaction_type']=='BUY' and new['draft']['submission_enabled'] is False
    with e['store'].db() as db:
        reservation=json.loads(db.execute('SELECT data FROM preparation_cash_reservations WHERE id=?',(key,)).fetchone()[0])
        assert verify_row(reservation,PIN)['held_cents']==660000
    with e['adapter_store'].tx() as db:
        assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==2
        assert list(db.execute('SELECT id,data FROM receipts ORDER BY id'))==before
    assert count(e,ARCHIVES)==count(e,ADMISSIONS)==1
    assert all(count(e,t)==1 for t in ACTIVE)
    assert e['store'].control()['mode']=='PAUSED'

def test_same_call_replays_without_second_request_or_hold(next_review):
    first=run(next_review);second=run(next_review)
    assert first['request_id']==second['request_id'] and second['idempotent_replay'] is True
    assert len(next_review['adapter_store'].requests())==3 and count(next_review,ADMISSIONS)==1

def test_delayed_replay_does_not_recheck_current_clock(next_review):
    run(next_review)
    clock=Mock(side_effect=AssertionError('Historical replay must not collect/current-check'))
    assert run(next_review,clock=clock)['idempotent_replay'] is True
    clock.assert_not_called()

@pytest.mark.parametrize('point',['AFTER_NEXT_ACTIVE_REFERENCES','AFTER_NEXT_DISABLED_REQUEST','BEFORE_NEXT_PREPARATION_COMMIT'])
def test_interruption_rolls_back_both_databases_and_cursor(next_review,point):
    e=next_review
    with e['store'].db() as db:cursor=db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0]
    class Interrupted(BaseException):pass
    def stop(at):
        if at==point:raise Interrupted()
    with pytest.raises(Interrupted):run(e,checkpoint=stop)
    assert_no_next(e)
    with e['store'].db() as db:assert db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0]==cursor

def test_expiry_before_commit_rolls_back_everything(next_review):
    e=next_review;now=e['clock'][0]
    def stop(at):
        if at=='BEFORE_NEXT_PREPARATION_COMMIT':e['clock'][0]=now+timedelta(seconds=31)
    with pytest.raises(ValueError,match='NEXT_PREPARATION_EXPIRED_BEFORE_COMMIT'):run(e,checkpoint=stop)
    assert_no_next(e)

def test_concurrent_callers_create_one_next_preparation(next_review):
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run(next_review),range(2)))
    assert sorted(r['idempotent_replay'] for r in results)==[False,True]
    assert len(next_review['adapter_store'].requests())==3 and count(next_review,ADMISSIONS)==1

def test_changed_input_cannot_rewrite_committed_preparation(next_review):
    run(next_review)
    with pytest.raises(ValueError,match='IMMUTABLE_HISTORY_PREPARATION_CONFLICT'):run(next_review,fee_buffer_cents=20000)
    assert len(next_review['adapter_store'].requests())==3

def test_fresh_cash_shortfall_blocks_without_using_old_capacity(next_review):
    e=next_review;market=deepcopy(e['next_market'])
    for funds in (market['cash_before_market'],market['cash_after_market'],
                  market['cash_capture']['funds_before'],market['cash_capture']['funds_after']):
        funds['cash_available_to_trade']='100'
    resign_cash(market)
    with pytest.raises(ValueError):run(e,market_bundle=market)
    assert_no_next(e)

def test_forged_bundle_cannot_create_next_preparation(next_review):
    market=deepcopy(next_review['next_market']);market['signature']='changed'
    with pytest.raises(ValueError,match='BUNDLE_SIGNATURE_INVALID'):run(next_review,market_bundle=market)
    assert_no_next(next_review)

def test_changed_controller_version_blocks_new_preparation(next_review):
    with pytest.raises(ValueError,match='REENTRY_CURRENT_CONTROLLER_REQUIRED'):
        run(next_review,expected_version=next_review['next_version']-1)
    assert_no_next(next_review)

def test_old_consumed_signal_cannot_create_next_request(next_review):
    with pytest.raises(ValueError,match='OLD_OR_CONSUMED_REENTRY_SIGNAL'):run(next_review,sequence=1)
    assert_no_next(next_review)

def test_unattributed_adapter_request_is_not_ignored(next_review):
    e=next_review
    with e['adapter_store'].tx() as db:
        row=db.execute('SELECT fingerprint,data FROM requests LIMIT 1').fetchone()
        db.execute('INSERT INTO requests VALUES(?,?,?)',('UNATTRIBUTED',row[0],row[1]))
    with pytest.raises(ValueError,match='UNATTRIBUTED_OR_CHANGED_ADAPTER_HISTORY'):run(e)
    assert not any(count(e,t) for t in ACTIVE)

def test_changed_admission_signature_blocks_replay(next_review):
    run(next_review)
    with next_review['store'].db() as db:
        row=json.loads(db.execute('SELECT data FROM '+ADMISSIONS).fetchone()[0]);row['signature']='changed'
        db.execute('UPDATE '+ADMISSIONS+' SET data=?',(json.dumps(row),))
    with pytest.raises(ValueError,match='CLOSED_CYCLE_SIGNATURE_INVALID'):run(next_review)

def test_next_request_still_hits_installed_hard_gate(next_review):
    result=run(next_review)
    assert next_review['adapter'].submit(result['request_id'])['status']=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE'
    next_review['token'].assert_not_called()
    with next_review['adapter_store'].tx() as db:assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==2

def test_fresh_bearish_confirmation_creates_disabled_pe(next_review):
    e=next_review;records=[json.loads(line) for line in e['path'].read_text().splitlines()]
    row=records[-1];name='ENTRY_BEARISH_ROUTE_B_STRUCTURAL'
    row['payload']['accepted_events']=[name];row['payload']['event_details'][0]['event_type']=name
    core={k:v for k,v in row.items() if k!='record_hash'}
    row['record_hash']=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
    e['path'].write_text(''.join(json.dumps(r)+'\n' for r in records))
    result=run(e);request=next(r for r in e['adapter_store'].requests() if r['request_id']==result['request_id'])
    assert request['direction']=='BEARISH'
    with e['store'].db() as db:
        plan=json.loads(db.execute('SELECT data FROM preparation_plans').fetchone()[0])
        assert plan['evidence']['contract']['instrument_type']=='PE'

def test_source_cursor_and_consumed_event_advance_once(next_review):
    e=next_review;result=run(e)
    with e['store'].db() as db:
        cursor=json.loads(db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0])
        assert cursor['sequence']==e['next_sequence']
        assert cursor['hash']==verified_records(e['path'])[-1]['record_hash']
        assert db.execute('SELECT COUNT(*) FROM preparation_consumed WHERE id=?',(result['request_id'],)).fetchone()[0]==1
