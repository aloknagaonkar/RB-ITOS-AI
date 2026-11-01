from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from unittest.mock import Mock,patch
import pytest
from test_hilega_application_preparation_v1 import env,append,BULL,counts
from test_hilega_atomic_disabled_binding_v1 import bound_env
from test_durable_closed_handoff_v1 import ready
from test_existing_request_attempt_v1 import case,run as buy,intercept,receipt as buy_receipt
from application_lifecycle_candidate_v1 import record_position,submit_source_exit,POSITIONS,ADOPTIONS,CLAIMS
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import MODEL,LIVE,sign
from hilega_application_preparation_fixtures import PIN,resign

EXIT='STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'
BEAR='ENTRY_BEARISH_ROUTE_B_STRUCTURAL'

@pytest.fixture
def owned(case):
    e=case
    with intercept(e),patch.object(e['transport'],'send',side_effect=lambda aid,wire:buy_receipt(e,aid,wire)):
        buy(e)
    e['buy_at']=e['clock'][0];e['entry_signal']=e['adapter_store'].requests()[0]['signal_at']
    e['clock'][0]+=timedelta(seconds=2)
    return e


def snapshot(e,*,sell_filled=0,sell_status='OPEN',buy_filled=None,position_missing=False):
    now=e['clock'][0];rows=e['adapter_store'].requests()
    parent=next(r for r in rows if r['request_id']==e['key']);body=parent['draft']['body'];q=body['quantity']
    bfilled=q if buy_filled is None else buy_filled
    orders=[dict(order_id=parent['order_id'],instrument=body['instrument_token'],product=body['product'],side='BUY',
        quantity=q,filled=bfilled,pending=q-bfilled,status='FILLED' if bfilled==q else 'PARTIAL' if bfilled else 'OPEN',placed_at=e['buy_at'].isoformat())]
    trades=[]
    if bfilled:trades.append(dict(order_id=parent['order_id'],trade_id='BUY-TRADE',instrument=body['instrument_token'],
        product=body['product'],side='BUY',quantity=bfilled,price=str(body['price']),filled_at=(e['buy_at']+timedelta(seconds=1)).isoformat()))
    sellers=[r for r in rows if r['draft']['body']['transaction_type']=='SELL' and r.get('order_id')]
    if sellers:
        sell=sellers[0];placed=sell['draft']['created_at']
        pending=q-sell_filled if sell_status in {'OPEN','PARTIAL'} else 0
        orders.append(dict(order_id=sell['order_id'],instrument=body['instrument_token'],product=body['product'],side='SELL',
            quantity=q,filled=sell_filled,pending=pending,status=sell_status,placed_at=placed))
        if sell_filled:trades.append(dict(order_id=sell['order_id'],trade_id='SELL-TRADE',instrument=body['instrument_token'],
            product=body['product'],side='SELL',quantity=sell_filled,price=str(sell['draft']['body']['price']),filled_at=placed))
    report=dict(model=MODEL,evidence_mode=LIVE,account_scope=PIN['scope'],snapshot_id='SYNTHETIC-LIFECYCLE-'+str(now.timestamp()),
        generated_at=now.isoformat(),completed_at=now.isoformat(),session_date=now.date().isoformat(),
        status='READ_ONLY_CAPTURED',account_identity_verified=True,profile_verified_before_and_after=True,
        account_position_rows_complete=True,source_atomic=False,position_fill_linkage_verified=False,live_pnl=None,
        production_execution_enabled=False,entry_permission=False,orders_sent=False,diagnostics=dict(issues=[]),
        orders=orders,trades=trades,positions=[] if position_missing else [dict(instrument=body['instrument_token'],product=body['product'],quantity=bfilled-sell_filled)])
    report['signature']=sign(report,PIN);return report


def observe(e,report=None,**kwargs):
    return record_position(e['store'],e['adapter'],PIN,e['authority'],entry_id=e['key'],
        capture_provider=lambda:deepcopy(report if report is not None else snapshot(e)),clock=lambda:e['clock'][0],**kwargs)


def source_exit(e,*,reversal=False,at=None):
    now=at or (e['buy_at']+timedelta(minutes=5)).replace(second=0,microsecond=0)
    e['clock'][0]=now+timedelta(seconds=3)
    append(e['path'],[EXIT,BEAR] if reversal else [EXIT],at=now.isoformat())
    records=[json.loads(line) for line in e['path'].read_text().splitlines()]
    for detail in records[-1]['payload']['event_details']:
        if detail['event_type']==EXIT:detail['entry_time']=e['entry_signal']
    row=records[-1];core={k:v for k,v in row.items() if k!='record_hash'}
    row['record_hash']=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
    e['path'].write_text(''.join(json.dumps(r)+'\n' for r in records))
    e['source'].run_source_once(e['path'])
    e['exit_seq']=len(records);return e


def market(e):
    bundle=deepcopy(e['data']);at=e['clock'][0].isoformat()
    bundle.update(started_at=at,completed_at=at,snapshot_id='SYNTHETIC-OWNED-MARKET')
    for quote in bundle['quotes'].values():
        quote['timestamp']=at
        if 'last_trade_time' in quote:quote['last_trade_time']=at
    resign(bundle);return bundle


def exit_run(e,**kwargs):
    options=dict(entry_id=e['key'],journal=e['path'],exit_sequence=e['exit_seq'],
        capture_provider=lambda:dict(account=snapshot(e),market=market(e)),
        clock=lambda:e['clock'][0],expected_version=e['store'].control()['version'])
    options.update(kwargs)
    return submit_source_exit(e['store'],e['adapter'],PIN,e['authority'],**options)


def sell_receipt(e,aid,wire):
    result=buy_receipt(e,aid,wire);result['body']['data']['order_ids']=['SYNTHETIC-SELL-ORDER'];return result


def sell(e):
    with intercept(e),patch.object(e['transport'],'send',side_effect=lambda aid,wire:sell_receipt(e,aid,wire)) as send:
        result=exit_run(e)
    send.assert_called_once();e['token'].assert_not_called();return result


def attempt_count(e):
    with e['adapter_store'].tx() as db:return db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]


def test_adopted_buy_signed_fill_records_quantity(owned):
    result=observe(owned)['report']
    assert result['status']=='ENTRY_FILLED_REFERENCE' and result['remaining_quantity']==65
    assert result['production_execution_enabled'] is False
    assert attempt_count(owned)==1


def test_actual_source_exit_then_bid_sell_then_signed_flat(owned):
    observe(owned);source_exit(owned);result=sell(owned)
    assert result['adapter_result']['state']=='ACKNOWLEDGED_NOT_FILLED'
    owned['clock'][0]+=timedelta(seconds=1)
    report=observe(owned,snapshot(owned,sell_filled=65,sell_status='FILLED'))['report']
    assert report['status']=='FLAT_CONFIRMED_REFERENCE' and report['remaining_quantity']==0
    assert report['fees_complete'] is False and report['reservation_release_permission'] is False
    assert counts(owned)==(1,1,1,0,0,0) and attempt_count(owned)==2


def test_real_exit_gate_precedes_capture_and_new_request(owned):
    source_exit(owned)
    provider=Mock(side_effect=AssertionError('No exit capture behind actual gate'))
    result=exit_run(owned,capture_provider=provider)
    assert result['status']=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE'
    provider.assert_not_called();assert attempt_count(owned)==1
    assert len(owned['adapter_store'].requests())==1


@pytest.mark.parametrize('quantity',[0,20])
def test_unfilled_or_partial_buy_cannot_sell(owned,quantity):
    source_exit(owned)
    with intercept(owned):
        with pytest.raises(ValueError,match='FULL_TERMINAL_BUY_REQUIRED'):
            exit_run(owned,capture_provider=lambda:dict(account=snapshot(owned,buy_filled=quantity),market=market(owned)))
    assert attempt_count(owned)==1


def test_missing_position_is_not_flat_or_owned(owned):
    with pytest.raises(ValueError,match='MISSING_POSITION_ROW_IS_NOT_FLAT'):
        observe(owned,snapshot(owned,position_missing=True))


def test_forged_account_signature_blocks(owned):
    report=snapshot(owned);report['signature']='changed'
    with pytest.raises(ValueError,match='SNAPSHOT_SIGNATURE_INVALID'):observe(owned,report)


def test_unrelated_position_exposure_blocks(owned):
    report=snapshot(owned);report['positions'].append(dict(instrument='NSE_FO|999',product='I',quantity=1))
    report.pop('signature');report['signature']=sign(report,PIN)
    with pytest.raises(ValueError,match='OWNED_POSITION_QUANTITY_MISMATCH'):observe(owned,report)


def test_tampered_buy_receipt_provenance_blocks(owned):
    with owned['adapter_store'].tx() as db:
        key,raw=db.execute('SELECT id,data FROM receipts').fetchone();row=json.loads(raw);row['wire_fingerprint']='changed'
        db.execute('UPDATE receipts SET data=? WHERE id=?',(json.dumps(row),key))
    with pytest.raises(ValueError,match='RECEIPT_PROVENANCE_MISMATCH'):observe(owned)


def test_unknown_buy_outcome_cannot_establish_owned_quantity(owned):
    with owned['adapter_store'].tx() as db:
        key,raw=db.execute('SELECT id,data FROM requests').fetchone();row=json.loads(raw);row['state']='UNKNOWN'
        db.execute('UPDATE requests SET data=? WHERE id=?',(json.dumps(row),key))
    with pytest.raises(ValueError,match='ENTRY_OUTCOME_REQUIRES_RECONCILIATION'):observe(owned)


def test_exit_first_reversal_does_not_submit_opposite_buy(owned):
    source_exit(owned,reversal=True);result=sell(owned)
    assert result['opposite_buy_submitted'] is False
    assert sum(r['draft']['body']['transaction_type']=='BUY' for r in owned['adapter_store'].requests())==1


@pytest.mark.parametrize('point',['AFTER_EXIT_CLAIM','AFTER_EXIT_ATTEMPT_INSERT'])
def test_sell_claim_request_attempt_roll_back_together(owned,point):
    source_exit(owned)
    class Interrupted(BaseException):pass
    def stop(at):
        if at==point:raise Interrupted()
    with intercept(owned):
        with pytest.raises(Interrupted):exit_run(owned,checkpoint=stop)
    assert attempt_count(owned)==1 and len(owned['adapter_store'].requests())==1
    sell(owned);assert attempt_count(owned)==2


@pytest.mark.parametrize('point',['AFTER_EXIT_ATTEMPT_COMMIT','AFTER_EXIT_TRANSPORT_BEFORE_RECEIPT','AFTER_EXIT_RECEIPT_COMMIT'])
def test_sell_restart_never_collects_or_resends(owned,point):
    source_exit(owned)
    class Interrupted(BaseException):pass
    def stop(at):
        if at==point:raise Interrupted()
    with intercept(owned),patch.object(owned['transport'],'send',side_effect=lambda aid,wire:sell_receipt(owned,aid,wire)):
        with pytest.raises(Interrupted):exit_run(owned,checkpoint=stop)
    provider=Mock(side_effect=AssertionError('No recovery capture'))
    with patch.object(owned['transport'],'send',side_effect=AssertionError('No repeated SELL')):
        result=exit_run(owned,capture_provider=provider,clock=lambda:owned['clock'][0]+timedelta(hours=2))
    assert result['recovery_only'] is True and attempt_count(owned)==2
    provider.assert_not_called()


def test_lost_sell_response_remains_unknown_without_repeat(owned):
    source_exit(owned)
    with intercept(owned),patch.object(owned['transport'],'send',side_effect=TimeoutError('synthetic response lost')) as send:
        first=exit_run(owned);second=exit_run(owned,capture_provider=Mock(side_effect=AssertionError('No new capture')))
    assert first['status']=='SELL_UNKNOWN_NO_RESUBMISSION'
    assert second['adapter_result']['state']=='UNKNOWN';send.assert_called_once()


def test_concurrent_exit_callers_submit_one_sell(owned):
    source_exit(owned)
    with intercept(owned),patch.object(owned['transport'],'send',side_effect=lambda aid,wire:sell_receipt(owned,aid,wire)) as send:
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:exit_run(owned),range(2)))
    assert attempt_count(owned)==2;send.assert_called_once()
    assert sum(r['recovery_only'] for r in results)==1


def test_working_and_partial_sell_observations_preserve_remaining(owned):
    source_exit(owned);sell(owned)
    assert observe(owned)['report']['status']=='EXIT_WORKING'
    owned['clock'][0]+=timedelta(seconds=1)
    report=observe(owned,snapshot(owned,sell_filled=20,sell_status='PARTIAL'))['report']
    assert report['status']=='EXIT_PARTIAL_PENDING'
    assert report['remaining_quantity']==report['pending_exit_quantity']==45
    assert attempt_count(owned)==2


def test_cancelled_partial_sell_requires_review_without_residual_order(owned):
    source_exit(owned);sell(owned)
    report=observe(owned,snapshot(owned,sell_filled=20,sell_status='CANCELLED'))['report']
    assert report['status']=='EXIT_TERMINAL_RESIDUAL_REVIEW_REQUIRED' and report['remaining_quantity']==45
    exit_run(owned,capture_provider=Mock(side_effect=AssertionError('No residual capture/send')))
    assert attempt_count(owned)==2


def test_exit_fill_regression_is_rejected(owned):
    source_exit(owned);sell(owned)
    observe(owned,snapshot(owned,sell_filled=20,sell_status='PARTIAL'))
    owned['clock'][0]+=timedelta(seconds=1)
    with pytest.raises(ValueError,match='POSITION_FILL_OR_CAPTURE_REGRESSION'):
        observe(owned,snapshot(owned,sell_filled=10,sell_status='PARTIAL'))


def test_position_record_replay_is_idempotent(owned):
    first=observe(owned);second=observe(owned)
    assert second['idempotent_replay'] is True and first['report']==second['report']


def test_position_review_interruption_rolls_back(owned):
    def stop(at):raise RuntimeError('SYNTHETIC_POSITION_INTERRUPTION')
    with pytest.raises(RuntimeError,match='POSITION_INTERRUPTION'):observe(owned,checkpoint=stop)
    with owned['store'].db() as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(POSITIONS,)).fetchone()
        assert not exists


def test_stale_owned_quote_cannot_create_sell(owned):
    source_exit(owned);bundle=market(owned)
    for q in bundle['quotes'].values():q['timestamp']=(owned['clock'][0]-timedelta(seconds=11)).isoformat()
    resign(bundle)
    with intercept(owned):
        with pytest.raises(ValueError,match='EXIT_QUOTE_QUALITY'):
            exit_run(owned,capture_provider=lambda:dict(account=snapshot(owned),market=bundle))
    assert attempt_count(owned)==1


def test_exit_claim_expiry_rolls_back(owned):
    source_exit(owned);now=owned['clock'][0]
    def stop(at):
        if at=='AFTER_EXIT_CLAIM':owned['clock'][0]=now+timedelta(seconds=10)
    with intercept(owned):
        with pytest.raises(ValueError,match='EXIT_CANDIDATE_EXPIRED'):exit_run(owned,checkpoint=stop)
    assert attempt_count(owned)==1


def test_tampered_closed_dispatch_is_not_adopted(owned):
    source_exit(owned)
    with owned['store'].db() as db:
        key,raw=db.execute('SELECT id,data FROM preparation_exit_dispatch').fetchone();row=json.loads(raw)
        row['automatic_execution_eligible']=True
        db.execute('UPDATE preparation_exit_dispatch SET data=? WHERE id=?',(json.dumps(row),key))
    with pytest.raises(ValueError,match='APPLICATION_CLOSED_EXIT_REFERENCE_CHANGED'):exit_run(owned)
    assert attempt_count(owned)==1


def test_flat_still_requires_explicit_position_row(owned):
    source_exit(owned);sell(owned)
    with pytest.raises(ValueError,match='MISSING_POSITION_ROW_IS_NOT_FLAT'):
        observe(owned,snapshot(owned,sell_filled=65,sell_status='FILLED',position_missing=True))


def test_protective_sell_uses_owned_quote_without_cash_or_atm(owned):
    source_exit(owned);bundle=market(owned)
    for key in ('cash_capture','cash_before_market','cash_after_market','spot_initial'):bundle.pop(key,None)
    bundle['quotes']={k:q for k,q in bundle['quotes'].items() if q['instrument_token'].startswith('NSE_FO|')}
    resign(bundle)
    with intercept(owned),patch.object(owned['transport'],'send',side_effect=lambda aid,wire:sell_receipt(owned,aid,wire)):
        result=exit_run(owned,capture_provider=lambda:dict(account=snapshot(owned),market=bundle))
    assert result['status']=='APPLICATION_EXIT_CANDIDATE_ACKNOWLEDGED'


def test_exit_is_not_restricted_by_entry_clock_or_entry_signal_age(owned):
    at=owned['buy_at'].replace(hour=14,minute=55,second=0,microsecond=0)
    source_exit(owned,at=at)
    assert sell(owned)['status']=='APPLICATION_EXIT_CANDIDATE_ACKNOWLEDGED'


def test_working_partial_exit_can_be_observed_after_long_wait(owned):
    source_exit(owned);sell(owned)
    observe(owned,snapshot(owned,sell_filled=20,sell_status='PARTIAL'))
    owned['clock'][0]+=timedelta(hours=2)
    report=observe(owned,snapshot(owned,sell_filled=30,sell_status='PARTIAL'))['report']
    assert report['remaining_quantity']==35 and attempt_count(owned)==2
