from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib
import json
from unittest.mock import Mock,patch
import pytest
from test_hilega_application_preparation_v1 import env,append,BULL
from test_hilega_atomic_disabled_binding_v1 import bound_env
from test_durable_closed_handoff_v1 import ready
from test_existing_request_attempt_v1 import case
from test_application_lifecycle_candidate_v1 import owned
from test_application_cycle_close_v1 import flat,next_review
from test_history_aware_preparation_v1 import run as prepare_next
from history_aware_attempt_v1 import submit_existing_candidate
from history_aware_lifecycle_v1 import record_position,submit_source_exit
from history_aware_cycle_close_v1 import record_closeout,retire_references,review_next_entry,ARCHIVES,CLOSEOUTS,ACTIVE
from hilega_application_preparation_fixtures import PIN,resign_cash
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign
from market_lab.hilega_production_simulator_bridge_v1 import verified_records
from market_lab.hilega_execution_port_v1 import adapter as port


@pytest.fixture
def second_ready(next_review):
    e=next_review
    with e['adapter_store'].tx() as db:
        e['first_broker']={t:list(db.execute('SELECT * FROM '+t+' ORDER BY 1')) for t in ('requests','attempts','receipts','candidate_existing_request_claims_v1')}
    e['second_key']=prepare_next(e)['request_id']
    return e


def full_account(e,*,buy_filled=65,sell_filled=0,sell_status='OPEN'):
    now=e['clock'][0];report=deepcopy(e['next_account'])
    report.pop('signature',None);report.update(generated_at=now.isoformat(),completed_at=now.isoformat(),snapshot_id='SYNTHETIC-TWO-CYCLE-'+str(now.timestamp()))
    rows=[r for r in e['adapter_store'].requests() if r['reservation_reference']==e['second_key'] and r.get('order_id')]
    remaining=0
    for r in rows:
        body=r['draft']['body'];side=body['transaction_type'];q=body['quantity'];filled=buy_filled if side=='BUY' else sell_filled
        status=('FILLED' if filled==q else 'PARTIAL' if filled else 'OPEN') if side=='BUY' else sell_status
        pending=q-filled if status in {'OPEN','PARTIAL'} else 0
        report['orders'].append(dict(order_id=r['order_id'],instrument=body['instrument_token'],product=body['product'],side=side,
            quantity=q,filled=filled,pending=pending,status=status,placed_at=r['draft']['created_at']))
        if filled:
            at=r['draft']['created_at'] if side=='SELL' else (timedelta(seconds=1)+datetime.fromisoformat(r['draft']['created_at'])).isoformat()
            report['trades'].append(dict(order_id=r['order_id'],trade_id='CYCLE2-'+side+'-TRADE',instrument=body['instrument_token'],
                product=body['product'],side=side,quantity=filled,price=str(body['price']),filled_at=at))
        remaining+=filled*(1 if side=='BUY' else -1)
    report['positions'][0]['quantity']=remaining
    report['signature']=sign(report,PIN);return report


def captures(e):
    account=full_account(e);market=deepcopy(e['next_market']);at=e['clock'][0].isoformat()
    market.update(started_at=at,completed_at=at,snapshot_id='SYNTHETIC-SECOND-MARKET')
    cash=market['cash_capture'];cash.update(started_at=at,completed_at=at,snapshot_id='SYNTHETIC-SECOND-CASH')
    for name in ('orders','trades','positions'):cash[name]=deepcopy(account[name])
    for q in market['quotes'].values():
        q['timestamp']=at
        if 'last_trade_time' in q:q['last_trade_time']=at
    resign_cash(market);return dict(account=account,market=market)


def run_buy(e,**kwargs):
    options=dict(journal=e['path'],request_id=e['second_key'],capture_provider=lambda:captures(e),
        clock=lambda:e['clock'][0],expected_version=e['store'].control()['version'],bridge_run_id='synthetic-lease')
    options.update(kwargs)
    return submit_existing_candidate(e['store'],e['adapter'],PIN,e['authority'],**options)


def ack(e,aid,wire):
    return dict(attempt_id=aid,wire_fingerprint=port.sha(wire),
        http_status=200,origin='LOCAL_HTTP_TRANSPORT',body=dict(status='success',data=dict(order_ids=[
            'SYNTHETIC-CYCLE2-'+wire['body']['transaction_type']+'-ORDER'])))


def positive_buy(e,**kwargs):
    with patch.object(e['transport'],'check',return_value=None),patch.object(e['transport'],'send',side_effect=lambda aid,wire:ack(e,aid,wire)) as send:
        result=run_buy(e,**kwargs)
    send.assert_called_once();e['token'].assert_not_called();return result


@pytest.fixture
def second_owned(second_ready):
    e=second_ready;positive_buy(e);e['clock'][0]+=timedelta(seconds=2);return e


def first_preserved(e):
    with e['adapter_store'].tx() as db:
        for table,rows in e['first_broker'].items():
            current={r[0]:r for r in db.execute('SELECT * FROM '+table)}
            assert all(current[row[0]]==row for row in rows)


def attempt_count(e):
    with e['adapter_store'].tx() as db:return db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]


def observe(e,report=None):
    return record_position(e['store'],e['adapter'],PIN,e['authority'],entry_id=e['second_key'],
        capture_provider=lambda:report if report is not None else full_account(e),clock=lambda:e['clock'][0])


def source_exit(e):
    now=(e['clock'][0]+timedelta(minutes=5)).replace(second=0,microsecond=0)
    e['clock'][0]=now+timedelta(seconds=3)
    append(e['path'],['STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'],at=now.isoformat())
    records=[json.loads(line) for line in e['path'].read_text().splitlines()]
    parent=next(r for r in e['adapter_store'].requests() if r['request_id']==e['second_key'])
    records[-1]['payload']['event_details'][0]['entry_time']=parent['signal_at']
    core={k:v for k,v in records[-1].items() if k!='record_hash'}
    records[-1]['record_hash']=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
    e['path'].write_text(''.join(json.dumps(r)+'\n' for r in records))
    e['source'].run_source_once(e['path']);e['second_exit_seq']=len(records)


def run_sell(e,**kwargs):
    options=dict(entry_id=e['second_key'],journal=e['path'],exit_sequence=e['second_exit_seq'],capture_provider=lambda:captures(e),
        clock=lambda:e['clock'][0],expected_version=e['store'].control()['version'])
    options.update(kwargs)
    return submit_source_exit(e['store'],e['adapter'],PIN,e['authority'],**options)


def positive_sell(e):
    with patch.object(e['transport'],'check',return_value=None),patch.object(e['transport'],'send',side_effect=lambda aid,wire:ack(e,aid,wire)) as send:
        result=run_sell(e)
    send.assert_called_once();return result


def test_second_buy_reuses_new_preparation_without_touching_closed_cycle(second_ready):
    e=second_ready;result=positive_buy(e)
    assert result['adapter_result']['state']=='ACKNOWLEDGED_NOT_FILLED'
    assert attempt_count(e)==3 and len(e['adapter_store'].requests())==3
    first_preserved(e)


def test_real_gate_stops_second_buy_before_capture(second_ready):
    provider=Mock(side_effect=AssertionError('No current capture behind gate'))
    assert run_buy(second_ready,capture_provider=provider)['status']=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE'
    provider.assert_not_called();assert attempt_count(second_ready)==2
    first_preserved(second_ready)


@pytest.mark.parametrize('point',['AFTER_AUTHORIZATION_CLAIM','AFTER_ATTEMPT_INSERT'])
def test_second_buy_claim_rollback_preserves_first_cycle(second_ready,point):
    e=second_ready
    class Interrupted(BaseException):pass
    def stop(at):
        if at==point:raise Interrupted()
    with patch.object(e['transport'],'check',return_value=None):
        with pytest.raises(Interrupted):run_buy(e,checkpoint=stop)
    assert attempt_count(e)==2;first_preserved(e)


@pytest.mark.parametrize('point',['AFTER_ATTEMPT_COMMIT','AFTER_TRANSPORT_BEFORE_RECEIPT','AFTER_RECEIPT_COMMIT'])
def test_second_buy_restart_recovers_only_current_request(second_ready,point):
    e=second_ready
    class Interrupted(BaseException):pass
    def stop(at):
        if at==point:raise Interrupted()
    with patch.object(e['transport'],'check',return_value=None),patch.object(e['transport'],'send',side_effect=lambda aid,wire:ack(e,aid,wire)):
        with pytest.raises(Interrupted):run_buy(e,checkpoint=stop)
    provider=Mock(side_effect=AssertionError('No recovery capture'))
    result=run_buy(e,capture_provider=provider,clock=lambda:e['clock'][0]+timedelta(hours=2))
    assert result['recovery_only'] is True and attempt_count(e)==3
    provider.assert_not_called();first_preserved(e)


def test_second_buy_concurrency_submits_once(second_ready):
    e=second_ready
    with patch.object(e['transport'],'check',return_value=None),patch.object(e['transport'],'send',side_effect=lambda aid,wire:ack(e,aid,wire)) as send:
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run_buy(e),range(2)))
    send.assert_called_once();assert attempt_count(e)==3
    first_preserved(e)


def test_second_buy_lost_response_never_resends(second_ready):
    e=second_ready
    with patch.object(e['transport'],'check',return_value=None),patch.object(e['transport'],'send',side_effect=TimeoutError('SYNTHETIC RESPONSE LOST')) as send:
        run_buy(e);result=run_buy(e,capture_provider=Mock(side_effect=AssertionError('No repeat capture')))
    assert result['recovery_only'] is True and attempt_count(e)==3
    send.assert_called_once();first_preserved(e)


def test_second_buy_rejects_tampered_history_account_rows(second_ready):
    e=second_ready;supplied=captures(e)
    supplied['account']['trades'][0]['price']='101';supplied['account'].pop('signature')
    supplied['account']['signature']=sign(supplied['account'],PIN)
    with patch.object(e['transport'],'check',return_value=None):
        with pytest.raises(ValueError,match='HISTORICAL_ACCOUNT_TRADE_CHANGED'):
            run_buy(e,capture_provider=lambda:supplied)
    assert attempt_count(e)==2


def test_second_buy_rejects_changed_old_broker_receipt(second_ready):
    e=second_ready
    with e['adapter_store'].tx() as db:
        key,raw=db.execute('SELECT id,data FROM receipts LIMIT 1').fetchone();row=json.loads(raw);row['http_status']=201
        db.execute('UPDATE receipts SET data=? WHERE id=?',(json.dumps(row),key))
    with patch.object(e['transport'],'check',return_value=None):
        with pytest.raises(ValueError,match='HISTORICAL_ADAPTER_EVIDENCE_CHANGED'):run_buy(e)
    assert attempt_count(e)==2


def test_full_original_capture_is_preserved_during_second_position_review(second_owned):
    e=second_owned;account=full_account(e);before=deepcopy(account)
    result=observe(e,account)['report']
    assert account==before and result['remaining_quantity']==65
    assert len(account['orders'])==3 and len(account['trades'])==3
    first_preserved(e)


def test_second_sell_gate_stops_before_capture(second_owned):
    e=second_owned;source_exit(e);provider=Mock(side_effect=AssertionError('No capture'))
    assert run_sell(e,capture_provider=provider)['status']=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE'
    provider.assert_not_called();assert attempt_count(e)==3;first_preserved(e)


def test_second_cycle_partial_sell_keeps_correct_remaining_quantity(second_owned):
    e=second_owned;source_exit(e);positive_sell(e)
    result=observe(e,full_account(e,sell_filled=20,sell_status='PARTIAL'))['report']
    assert result['remaining_quantity']==result['pending_exit_quantity']==45
    assert attempt_count(e)==4;first_preserved(e)


@pytest.mark.parametrize('point',['AFTER_EXIT_ATTEMPT_COMMIT','AFTER_EXIT_RECEIPT_COMMIT'])
def test_second_sell_restart_does_not_touch_first_cycle(second_owned,point):
    e=second_owned;source_exit(e)
    class Interrupted(BaseException):pass
    def stop(at):
        if at==point:raise Interrupted()
    with patch.object(e['transport'],'check',return_value=None),patch.object(e['transport'],'send',side_effect=lambda aid,wire:ack(e,aid,wire)):
        with pytest.raises(Interrupted):run_sell(e,checkpoint=stop)
    result=run_sell(e,capture_provider=Mock(side_effect=AssertionError('No recovery capture')))
    assert result['recovery_only'] is True and attempt_count(e)==4;first_preserved(e)


@pytest.fixture
def second_closed(second_owned):
    e=second_owned;observe(e);source_exit(e);positive_sell(e);e['clock'][0]+=timedelta(seconds=1)
    e['second_flat']=full_account(e,sell_filled=65,sell_status='FILLED')
    observe(e,e['second_flat'])
    e['second_closeout']=record_closeout(e['store'],e['adapter'],PIN,e['authority'],entry_id=e['second_key'],journal=e['path'],
        exit_sequence=e['second_exit_seq'],capture_provider=lambda:e['second_flat'],clock=lambda:e['clock'][0])
    retire_references(e['store'],e['adapter'],PIN,e['authority'],entry_id=e['second_key'],
        capture_provider=lambda:e['second_flat'],clock=lambda:e['clock'][0])
    return e


def test_two_complete_cycles_archive_without_double_counting_pnl(second_closed):
    e=second_closed
    with e['store'].db() as db:
        rows=[json.loads(raw) for raw, in db.execute('SELECT data FROM '+CLOSEOUTS)]
        assert len(rows)==2 and sum(r['realized_gross_pnl_paise'] for r in rows)==-650
        assert all(r['realized_gross_pnl_paise']==-325 and r['fees_complete'] is False for r in rows)
        assert db.execute('SELECT COUNT(*) FROM '+ARCHIVES).fetchone()[0]==2
        assert not any(db.execute('SELECT 1 FROM '+t+' LIMIT 1').fetchone() for t in ACTIVE)
    assert attempt_count(e)==4 and len(e['adapter_store'].requests())==4;first_preserved(e)


def test_second_closeout_replays_after_retirement_without_capture(second_closed):
    e=second_closed;provider=Mock(side_effect=AssertionError('No closeout replay capture'))
    result=record_closeout(e['store'],e['adapter'],PIN,e['authority'],entry_id=e['second_key'],journal=e['path'],
        exit_sequence=e['second_exit_seq'],capture_provider=provider,clock=lambda:e['clock'][0]+timedelta(hours=2))
    assert result['idempotent_replay'] is True;provider.assert_not_called();first_preserved(e)


def test_third_fresh_signal_review_attributes_both_complete_cycles(second_closed):
    e=second_closed;now=(e['clock'][0]+timedelta(minutes=5)).replace(second=0,microsecond=0);e['clock'][0]=now
    with e['store'].db() as db:
        control=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        control.update(mode='ARMED',version=control['version']+1,reconciled=True,resumed_at=(now-timedelta(seconds=1)).isoformat(),last_reconciled_at=now.isoformat())
        db.execute('UPDATE control SET data=? WHERE id=1',(json.dumps(control),))
        health=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0]);health.update(heartbeat_at=now.isoformat(),source_at=now.isoformat(),phase='RUNNING')
        db.execute('UPDATE sim_bridge_health SET data=? WHERE id=1',(json.dumps(health),))
    append(e['path'],[BULL],at=now.isoformat());account=full_account(e,sell_filled=65,sell_status='FILLED')
    supplied=captures(e);market=supplied['market']
    for name in ('orders','trades','positions'):market['cash_capture'][name]=deepcopy(account[name])
    resign_cash(market)
    result=review_next_entry(e['store'],e['adapter'],PIN,e['authority'],journal=e['path'],sequence=len(verified_records(e['path'])),
        account_capture=account,market_bundle=market,fee_buffer_cents=10000,clock=lambda:now,
        expected_version=control['version'],bridge_run_id='synthetic-lease')
    assert result['matched_closed_cycles']==2 and result['entry_permission'] is False
    assert len(e['adapter_store'].requests())==4;first_preserved(e)


def test_second_buy_expiry_after_attempt_insert_rolls_back(second_ready):
    e=second_ready;now=e['clock'][0]
    def stop(at):
        if at=='AFTER_ATTEMPT_INSERT':e['clock'][0]=now+timedelta(seconds=10)
    with patch.object(e['transport'],'check',return_value=None):
        with pytest.raises(ValueError,match='CANDIDATE_GRANT_EXPIRED_OR_FUTURE'):
            run_buy(e,checkpoint=stop)
    assert attempt_count(e)==2;first_preserved(e)

def test_second_buy_quote_stale_at_final_commit_rolls_back(second_ready):
    e=second_ready;now=e['clock'][0];supplied=captures(e)
    for q in supplied['market']['quotes'].values():
        q['timestamp']=(now-timedelta(seconds=9)).isoformat()
    resign_cash(supplied['market'])
    def stop(at):
        if at=='AFTER_ATTEMPT_INSERT':e['clock'][0]=now+timedelta(seconds=2)
    with patch.object(e['transport'],'check',return_value=None):
        with pytest.raises(ValueError,match='HISTORY_CURRENT_EVIDENCE_REJECTED'):
            run_buy(e,capture_provider=lambda:supplied,checkpoint=stop)
    assert attempt_count(e)==2;first_preserved(e)
