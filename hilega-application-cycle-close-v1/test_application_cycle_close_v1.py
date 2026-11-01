from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import Mock
import pytest
from test_hilega_application_preparation_v1 import env,append,BULL
from test_hilega_atomic_disabled_binding_v1 import bound_env
from test_durable_closed_handoff_v1 import ready
from test_existing_request_attempt_v1 import case
from test_application_lifecycle_candidate_v1 import owned,source_exit,sell,snapshot,observe
from application_cycle_close_v1 import (
    record_closeout,retire_references,review_next_entry,CLOSEOUTS,ARCHIVES,RETIREMENTS,ACTIVE,
)
from hilega_application_preparation_fixtures import PIN,resign_cash
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign
from market_lab.hilega_production_simulator_bridge_v1 import verified_records

@pytest.fixture
def flat(owned):
    e=owned;source_exit(e);sell(e);e['clock'][0]+=timedelta(seconds=1)
    e['flat']=snapshot(e,sell_filled=65,sell_status='FILLED')
    observe(e,e['flat']);return e


def close(e,**kwargs):
    options=dict(entry_id=e['key'],journal=e['path'],exit_sequence=e['exit_seq'],
        capture_provider=lambda:deepcopy(e['flat']),clock=lambda:e['clock'][0])
    options.update(kwargs)
    return record_closeout(e['store'],e['adapter'],PIN,e['authority'],**options)


def retire(e,**kwargs):
    options=dict(entry_id=e['key'],capture_provider=lambda:deepcopy(e['flat']),clock=lambda:e['clock'][0])
    options.update(kwargs)
    return retire_references(e['store'],e['adapter'],PIN,e['authority'],**options)


def count(e,table):
    with e['store'].db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():return 0
        return db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]


def test_terminal_flat_records_gross_without_fabricating_fees_or_release(flat):
    row=close(flat)['record']
    assert row['realized_gross_pnl_paise']==-325
    assert row['fees_complete'] is False and row['realized_net_pnl_paise'] is None
    assert row['financial_closeout_complete'] is False and row['reservation_release_permission'] is False
    assert all(count(flat,t)==1 for t in ACTIVE)


def test_closeout_replay_needs_no_capture_or_current_time(flat):
    first=close(flat)
    provider=Mock(side_effect=AssertionError('No replay capture'))
    second=close(flat,capture_provider=provider,clock=lambda:flat['clock'][0]+timedelta(hours=2))
    assert first['record']==second['record'] and second['idempotent_replay'] is True
    assert count(flat,CLOSEOUTS)==1;provider.assert_not_called()


@pytest.mark.parametrize('point',['AFTER_CYCLE_CLOSEOUT_INSERT','BEFORE_CYCLE_CLOSEOUT_COMMIT'])
def test_closeout_interruption_rolls_back(flat,point):
    class Interrupted(BaseException):pass
    def stop(at):
        if at==point:raise Interrupted()
    with pytest.raises(Interrupted):close(flat,checkpoint=stop)
    assert count(flat,CLOSEOUTS)==0 and all(count(flat,t)==1 for t in ACTIVE)


def test_open_sell_cannot_closeout(flat):
    open_snapshot=snapshot(flat,sell_filled=0,sell_status='OPEN')
    with pytest.raises(ValueError,match='TERMINAL_FLAT_CLOSEOUT_REQUIRED'):
        close(flat,capture_provider=lambda:open_snapshot)
    assert count(flat,CLOSEOUTS)==0


def test_closeout_expiry_before_commit_rolls_back(flat):
    now=flat['clock'][0]
    def stop(at):
        if at=='BEFORE_CYCLE_CLOSEOUT_COMMIT':flat['clock'][0]=now+timedelta(seconds=31)
    with pytest.raises(ValueError):close(flat,checkpoint=stop)
    assert count(flat,CLOSEOUTS)==0


def test_retirement_preserves_every_broker_record_and_signed_evidence(flat):
    close(flat);before=flat['adapter_store'].path.read_bytes()
    with flat['store'].db() as db:evidence=list(db.execute('SELECT digest,data FROM preparation_evidence'))
    result=retire(flat)
    assert result['local_references_retired'] is True and result['broker_cash_release_assessed'] is False
    assert not any(count(flat,t) for t in ACTIVE)
    assert flat['adapter_store'].path.read_bytes()==before
    with flat['store'].db() as db:assert list(db.execute('SELECT digest,data FROM preparation_evidence'))==evidence
    assert count(flat,ARCHIVES)==count(flat,RETIREMENTS)==count(flat,CLOSEOUTS)==1


def test_retirement_replay_does_not_capture(flat):
    close(flat);retire(flat)
    provider=Mock(side_effect=AssertionError('No retirement replay capture'))
    result=retire(flat,capture_provider=provider,clock=lambda:flat['clock'][0]+timedelta(hours=2))
    assert result['idempotent_replay'] is True
    assert count(flat,ARCHIVES)==1;provider.assert_not_called()


@pytest.mark.parametrize('point',['AFTER_CYCLE_ARCHIVE_INSERT','AFTER_CYCLE_REFERENCES_RETIRED','BEFORE_CYCLE_RETIREMENT_COMMIT'])
def test_retirement_interruption_restores_all_active_references(flat,point):
    close(flat)
    class Interrupted(BaseException):pass
    def stop(at):
        if at==point:raise Interrupted()
    with pytest.raises(Interrupted):retire(flat,checkpoint=stop)
    assert count(flat,ARCHIVES)==count(flat,RETIREMENTS)==0
    assert all(count(flat,t)==1 for t in ACTIVE)


def test_retirement_expiry_rolls_back(flat):
    close(flat);now=flat['clock'][0]
    def stop(at):
        if at=='BEFORE_CYCLE_RETIREMENT_COMMIT':flat['clock'][0]=now+timedelta(seconds=31)
    with pytest.raises(ValueError):retire(flat,checkpoint=stop)
    assert count(flat,RETIREMENTS)==0 and all(count(flat,t)==1 for t in ACTIVE)


def test_changed_local_reference_after_closeout_blocks_retirement(flat):
    close(flat)
    with flat['store'].db() as db:
        raw=db.execute('SELECT data FROM preparation_shadow_holds').fetchone()[0];row=json.loads(raw);row['held_cents']+=1
        db.execute('UPDATE preparation_shadow_holds SET data=?',(json.dumps(row),))
    with pytest.raises(ValueError,match='CYCLE_SOURCE_CHANGED_AFTER_CLOSEOUT'):retire(flat)
    assert all(count(flat,t)==1 for t in ACTIVE)


def test_tampered_closeout_signature_blocks_retirement(flat):
    close(flat)
    with flat['store'].db() as db:
        row=json.loads(db.execute('SELECT data FROM '+CLOSEOUTS).fetchone()[0]);row['signature']='changed'
        db.execute('UPDATE '+CLOSEOUTS+' SET data=?',(json.dumps(row),))
    with pytest.raises(ValueError,match='CLOSED_CYCLE_SIGNATURE_INVALID'):retire(flat)


def test_concurrent_retirement_records_one_archive(flat):
    close(flat)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:retire(flat),range(2)))
    assert sorted(r['idempotent_replay'] for r in results)==[False,True]
    assert count(flat,ARCHIVES)==1


@pytest.fixture
def next_review(flat):
    e=flat;close(e);retire(e)
    now=(e['clock'][0]+timedelta(minutes=5)).replace(second=0,microsecond=0)
    e['clock'][0]=now
    with e['store'].db() as db:
        control=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        control.update(mode='ARMED',version=control['version']+1,reconciled=True,
            resumed_at=(now-timedelta(seconds=1)).isoformat(),last_reconciled_at=now.isoformat())
        db.execute('UPDATE control SET data=? WHERE id=1',(json.dumps(control),))
        health=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
        health.update(heartbeat_at=now.isoformat(),source_at=now.isoformat(),phase='RUNNING')
        db.execute('UPDATE sim_bridge_health SET data=? WHERE id=1',(json.dumps(health),))
    append(e['path'],[BULL],at=now.isoformat())
    e['next_sequence']=len(verified_records(e['path']));e['next_version']=control['version']
    e['next_account']=snapshot(e,sell_filled=65,sell_status='FILLED')
    market=deepcopy(e['data']);market.update(started_at=now.isoformat(),completed_at=now.isoformat(),snapshot_id='SYNTHETIC-REENTRY-MARKET')
    cash=market['cash_capture'];cash.update(started_at=now.isoformat(),completed_at=now.isoformat(),snapshot_id='SYNTHETIC-REENTRY-CASH')
    for k in ('orders','trades','positions'):cash[k]=deepcopy(e['next_account'][k])
    for quote in market['quotes'].values():
        quote['timestamp']=now.isoformat()
        if 'last_trade_time' in quote:quote['last_trade_time']=now.isoformat()
    resign_cash(market);e['next_market']=market;return e


def reentry(e,**kwargs):
    options=dict(journal=e['path'],sequence=e['next_sequence'],account_capture=e['next_account'],
        market_bundle=e['next_market'],fee_buffer_cents=10000,clock=lambda:e['clock'][0],
        expected_version=e['next_version'],bridge_run_id='synthetic-lease')
    options.update(kwargs)
    return review_next_entry(e['store'],e['adapter'],PIN,e['authority'],**options)


def test_fresh_signal_and_attributed_history_pass_review_without_preparing(next_review):
    e=next_review;before=e['adapter_store'].requests();result=reentry(e)
    assert result['status']=='CLOSED_HISTORY_REENTRY_REVIEW_ELIGIBLE'
    assert result['matched_closed_cycles']==1 and result['proposed_budget_cents']==660000
    assert result['application_source_reentry_integrated'] is False and result['entry_permission'] is False
    assert result['new_preparation_created'] is False and e['adapter_store'].requests()==before
    assert not any(count(e,t) for t in ACTIVE)


def test_reentry_uses_fresh_lower_cash_not_old_capacity(next_review):
    e=next_review;market=deepcopy(e['next_market'])
    for funds in (market['cash_before_market'],market['cash_after_market'],
                  market['cash_capture']['funds_before'],market['cash_capture']['funds_after']):
        funds['cash_available_to_trade']='100'
    resign_cash(market)
    with pytest.raises(ValueError):reentry(e,market_bundle=market)
    assert not any(count(e,t) for t in ACTIVE)


def test_old_consumed_signal_cannot_reenter(next_review):
    with pytest.raises(ValueError,match='OLD_OR_CONSUMED_REENTRY_SIGNAL'):reentry(next_review,sequence=1)


def test_pre_resume_signal_cannot_reenter(next_review):
    e=next_review
    with e['store'].db() as db:
        row=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0]);row['resumed_at']=e['clock'][0].isoformat()
        db.execute('UPDATE control SET data=? WHERE id=1',(json.dumps(row),))
    with pytest.raises(ValueError,match='FRESH_POST_RESUME_REENTRY_REQUIRED'):reentry(e)


def test_unrelated_account_order_is_not_absorbed_as_history(next_review):
    e=next_review;account=deepcopy(e['next_account'])
    order=deepcopy(account['orders'][0]);order.update(order_id='UNRELATED',filled=0,pending=0,status='REJECTED')
    account['orders'].append(order);account.pop('signature');account['signature']=sign(account,PIN)
    with pytest.raises(ValueError,match='UNATTRIBUTED_OR_CHANGED_ACCOUNT_ORDER'):reentry(e,account_capture=account)


def test_missing_zero_position_blocks_reentry(next_review):
    e=next_review;account=deepcopy(e['next_account']);account['positions']=[]
    account.pop('signature');account['signature']=sign(account,PIN)
    with pytest.raises(ValueError,match='EXPLICIT_FLAT_REENTRY_POSITION_REQUIRED'):reentry(e,account_capture=account)


def test_tampered_archive_blocks_reentry(next_review):
    e=next_review
    with e['store'].db() as db:
        row=json.loads(db.execute('SELECT data FROM '+ARCHIVES).fetchone()[0]);row['signature']='changed'
        db.execute('UPDATE '+ARCHIVES+' SET data=?',(json.dumps(row),))
    with pytest.raises(ValueError,match='CLOSED_CYCLE_SIGNATURE_INVALID'):reentry(e)


def test_reappeared_active_reference_blocks_reentry(next_review):
    e=next_review
    with e['store'].db() as db:db.execute('INSERT INTO preparation_plans VALUES(?,?)',('unexpected','{}'))
    with pytest.raises(ValueError,match='ACTIVE_CYCLE_BLOCKS_REENTRY'):reentry(e)


def test_cash_capture_cannot_omit_historical_account_rows(next_review):
    e=next_review;market=deepcopy(e['next_market']);market['cash_capture']['orders']=[];market['cash_capture']['trades']=[]
    resign_cash(market)
    with pytest.raises(ValueError,match='REENTRY_CASH_ACCOUNT_ROWS_DIFFER'):reentry(e,market_bundle=market)


def test_stale_reentry_capture_is_rejected(next_review):
    with pytest.raises(ValueError):reentry(next_review,clock=lambda:next_review['clock'][0]+timedelta(seconds=31))
