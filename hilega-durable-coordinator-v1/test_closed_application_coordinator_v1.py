"""VM-only behavior checks. Every positive transport is intercepted."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock,patch
import pytest
from test_hilega_application_preparation_v1 import env,append,BULL
from test_hilega_atomic_disabled_binding_v1 import bound_env
from test_durable_closed_handoff_v1 import ready
from test_existing_request_attempt_v1 import case
from hilega_application_preparation_fixtures import PIN,resign_cash
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import MODEL,LIVE,sign
from market_lab.hilega_production_simulator_bridge_v1 import verified_records
from market_lab.hilega_execution_port_v1 import adapter as port
from closed_application_coordinator_v1 import CandidateSession,worker_tick,STATE
from history_aware_cycle_close_v1 import ARCHIVES,CLOSEOUTS,ACTIVE

EXIT='STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'
BEAR='ENTRY_BEARISH_ROUTE_B_STRUCTURAL'


def read_state(e):
    with e['store'].db() as db:
        return json.loads(db.execute('SELECT data FROM '+STATE+' WHERE id=1').fetchone()[0])


def count(e,table):
    with e['store'].db() as db:
        if not db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():return 0
        return db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]


def account(e):
    now=e['clock'][0];orders=[];trades=[];positions={}
    for r in e['adapter_store'].requests():
        if not r.get('order_id'):continue
        b=r['draft']['body'];oid=r['order_id'];q=b['quantity'];filled=e['fills'].get(oid,0)
        status=e['statuses'].get(oid,'FILLED' if filled==q else 'PARTIAL' if filled else 'OPEN')
        orders.append(dict(order_id=oid,instrument=b['instrument_token'],product=b['product'],side=b['transaction_type'],
            quantity=q,filled=filled,pending=q-filled if status in {'OPEN','PARTIAL'} else 0,status=status,placed_at=r['draft']['created_at']))
        if filled:
            trades.append(dict(order_id=oid,trade_id='TRADE-'+oid,instrument=b['instrument_token'],product=b['product'],
                side=b['transaction_type'],quantity=filled,price=str(b['price']),filled_at=r['draft']['created_at']))
        key=(b['instrument_token'],b['product']);positions[key]=positions.get(key,0)+filled*(1 if b['transaction_type']=='BUY' else -1)
    row=dict(model=MODEL,evidence_mode=LIVE,account_scope=PIN['scope'],snapshot_id='COORD-ACCOUNT-'+str(now.timestamp()),
        generated_at=now.isoformat(),completed_at=now.isoformat(),session_date=now.date().isoformat(),
        status='READ_ONLY_CAPTURED',account_identity_verified=True,profile_verified_before_and_after=True,
        account_position_rows_complete=True,source_atomic=False,position_fill_linkage_verified=False,live_pnl=None,
        production_execution_enabled=False,entry_permission=False,orders_sent=False,diagnostics=dict(issues=[]),
        orders=orders,trades=trades,positions=[dict(instrument=k[0],product=k[1],quantity=v) for k,v in positions.items()])
    row['signature']=sign(row,PIN);return row


def market(e):
    row=deepcopy(e['data']);at=e['clock'][0].isoformat()
    row.update(started_at=at,completed_at=at,snapshot_id='COORD-MARKET-'+at)
    cash=row['cash_capture'];cash.update(started_at=at,completed_at=at,snapshot_id='COORD-CASH-'+at)
    current=account(e)
    for key in ('orders','trades','positions'):cash[key]=deepcopy(current[key])
    for q in row['quotes'].values():
        q['timestamp']=at
        if 'last_trade_time' in q:q['last_trade_time']=at
    resign_cash(row);return row


def session(e,**kwargs):
    options=dict(journal=e['path'],seed_request_id=e['key'],bridge_run_id='synthetic-lease',
        providers=e['providers'],clock=lambda:e['clock'][0])
    options.update(kwargs)
    return CandidateSession(e['store'],e['adapter'],e['source'],PIN,e['authority'],**options)


@pytest.fixture
def flow(case):
    e=case;e['fills']={};e['statuses']={}
    def captures():return dict(account=account(e),market=market(e))
    e['providers']={
        'entry':Mock(side_effect=lambda kind:market(e) if kind=='first' else captures()),
        'account':Mock(side_effect=lambda:account(e)),
        'exit':Mock(side_effect=captures),'next':Mock(side_effect=lambda event:captures())}
    def receipt(aid,wire):
        return dict(attempt_id=aid,wire_fingerprint=port.sha(wire),http_status=200,origin='LOCAL_HTTP_TRANSPORT',
            body=dict(status='success',data=dict(order_ids=['COORD-'+aid])))
    with patch.object(e['transport'],'check',return_value=None),patch.object(e['transport'],'send',side_effect=receipt) as send:
        e['send']=send;yield e
    e['token'].assert_not_called()


def poll(e,**kwargs):return worker_tick(session(e,**kwargs))


def fill(e,side,quantity=None):
    key=read_state(e)['entry_id']
    rows=[r for r in e['adapter_store'].requests() if r['reservation_reference']==key and r['draft']['body']['transaction_type']==side]
    assert len(rows)==1 and rows[0].get('order_id')
    e['fills'][rows[0]['order_id']]=rows[0]['draft']['body']['quantity'] if quantity is None else quantity
    e['clock'][0]+=timedelta(seconds=1)
    return rows[0]


def to_wait_exit(e):
    assert poll(e)['phase']=='ENTRY_REVIEW'
    fill(e,'BUY');assert poll(e)['phase']=='WAIT_EXIT'


def emit_exit(e,*,reversal=False):
    now=(e['clock'][0]+timedelta(minutes=5)).replace(second=0,microsecond=0)
    e['clock'][0]=now+timedelta(seconds=3)
    append(e['path'],[EXIT,BEAR] if reversal else [EXIT],at=now.isoformat())
    records=[json.loads(x) for x in e['path'].read_text().splitlines()]
    parent=next(r for r in e['adapter_store'].requests() if r['request_id']==read_state(e)['entry_id'])
    for detail in records[-1]['payload']['event_details']:
        if detail['event_type']==EXIT:detail['entry_time']=parent['signal_at']
    core={k:v for k,v in records[-1].items() if k!='record_hash'}
    records[-1]['record_hash']=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
    e['path'].write_text(''.join(json.dumps(r)+'\n' for r in records))
    assert poll(e)['phase']=='SELL_PENDING'


def to_exit_review(e):
    to_wait_exit(e);emit_exit(e);assert poll(e)['phase']=='EXIT_REVIEW'


def to_closeout(e):
    to_exit_review(e);fill(e,'SELL');assert poll(e)['phase']=='CLOSEOUT_PENDING'


def finish(e):
    to_closeout(e);assert poll(e)['phase']=='RETIRE_PENDING';assert poll(e)['phase']=='WAIT_NEXT'


def resume_and_signal(e):
    # Only temporary synthetic controller rows are edited; no service commands.
    now=(e['clock'][0]+timedelta(minutes=5-e['clock'][0].minute%5)).replace(second=0,microsecond=0);e['clock'][0]=now
    with e['store'].db() as db:
        c=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        c.update(mode='ARMED',version=c['version']+1,reconciled=True,resumed_at=(now-timedelta(seconds=1)).isoformat(),last_reconciled_at=now.isoformat())
        db.execute('UPDATE control SET data=? WHERE id=1',(json.dumps(c),))
        h=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
        h.update(heartbeat_at=now.isoformat(),source_at=now.isoformat(),phase='RUNNING')
        db.execute('UPDATE sim_bridge_health SET data=? WHERE id=1',(json.dumps(h),))
    append(e['path'],[BULL],at=now.isoformat())


def interrupt(point):
    def stop(at):
        if at==point:raise RuntimeError('synthetic worker interruption')
    return stop


def test_default_tick_does_not_open_database_or_load_modules():
    with patch('builtins.open',side_effect=AssertionError('No file access')):
        row=worker_tick()
    assert row['status']=='EXECUTION_COORDINATOR_CLOSED_IN_CODE'
    assert row['application_database_opened'] is False and row['token_loaded'] is False


def test_unknown_session_type_is_rejected():
    with pytest.raises(ValueError,match='EXACT_CANDIDATE_SESSION_REQUIRED'):worker_tick(object())


@pytest.mark.parametrize('args',[['--once'],['--watch','--interval','1','--max-ticks','2']])
def test_cli_stays_closed_without_application_imports(tmp_path,args):
    script=Path(__file__).with_name('closed_application_coordinator_v1.py')
    environment=dict(os.environ,PYTHONPATH='',HILEGA_PRODUCTION_EXECUTION_ENABLED='1')
    run=subprocess.run([sys.executable,'-I',str(script),*args],cwd=tmp_path,env=environment,capture_output=True,text=True,timeout=10)
    assert run.returncode==0,run.stderr
    rows=[json.loads(x) for x in run.stdout.splitlines()]
    assert len(rows)==(1 if '--once' in args else 2)
    assert all(r['production_execution_enabled'] is False and r['application_database_opened'] is False for r in rows)
    assert not list(tmp_path.iterdir())


def test_actual_gate_precedes_state_and_capture(case):
    e=case;providers={k:Mock(side_effect=AssertionError('No closed capture')) for k in ('entry','account','exit','next')}
    output=worker_tick(session(dict(e,providers=providers)))
    assert output['status']=='EXECUTION_COORDINATOR_CLOSED_IN_CODE' and count(e,STATE)==0
    for provider in providers.values():provider.assert_not_called()
    e['token'].assert_not_called()


@pytest.mark.parametrize('quantity',[0,20])
def test_working_buy_does_not_advance_to_sell(flow,quantity):
    e=flow;assert poll(e)['phase']=='ENTRY_REVIEW'
    if quantity:fill(e,'BUY',quantity)
    assert poll(e)['status']=='WORKER_ENTRY_FILL_PENDING'
    assert read_state(e)['phase']=='ENTRY_REVIEW' and e['send'].call_count==1


def test_two_complete_worker_cycles_and_third_disabled_preparation(flow):
    e=flow;finish(e)
    assert read_state(e)['completed_cycles']==1 and count(e,ARCHIVES)==1
    resume_and_signal(e)
    assert poll(e)['phase']=='PREPARE_PENDING'
    assert poll(e)['phase']=='BUY_PENDING'
    finish(e)
    assert read_state(e)['completed_cycles']==2 and count(e,ARCHIVES)==count(e,CLOSEOUTS)==2
    assert not any(count(e,t) for t in ACTIVE)
    resume_and_signal(e);assert poll(e)['phase']=='PREPARE_PENDING';assert poll(e)['phase']=='BUY_PENDING'
    assert len(e['adapter_store'].requests())==5 and e['send'].call_count==4


@pytest.mark.parametrize('side',['BUY','SELL'])
def test_unknown_outcome_never_resubmits(flow,side):
    e=flow
    if side=='SELL':to_wait_exit(e);emit_exit(e)
    before=e['send'].call_count
    with patch.object(e['transport'],'send',side_effect=TimeoutError('Synthetic lost response')) as lost:
        first=poll(e);again=poll(e)
    expected='ENTRY_UNKNOWN' if side=='BUY' else 'EXIT_UNKNOWN'
    assert first['phase']==again['phase']==expected and lost.call_count==1
    provider=e['providers']['entry' if side=='BUY' else 'exit'];assert provider.call_count==1
    assert e['send'].call_count==before


def test_partial_exit_holds_remaining_quantity_without_new_order(flow):
    e=flow;to_exit_review(e);order=fill(e,'SELL',20)
    first=poll(e);second=poll(e)
    assert first['phase']==second['phase']=='EXIT_REVIEW'
    assert e['send'].call_count==2 and count(e,CLOSEOUTS)==0
    assert account(e)['positions'][0]['quantity']==45
    e['statuses'][order['order_id']]='CANCELLED'
    assert poll(e)['phase']=='EXIT_REVIEW' and e['send'].call_count==2


@pytest.mark.parametrize('point,phase',[
    ('AFTER_BUY_ACTION_BEFORE_STATE','ENTRY_REVIEW'),
    ('AFTER_SELL_ACTION_BEFORE_STATE','EXIT_REVIEW'),
    ('AFTER_CLOSEOUT_ACTION_BEFORE_STATE','RETIRE_PENDING'),
    ('AFTER_RETIREMENT_ACTION_BEFORE_STATE','WAIT_NEXT')])
def test_committed_action_recovers_after_worker_state_interruption(flow,point,phase):
    e=flow
    if 'SELL' in point:to_wait_exit(e);emit_exit(e)
    elif 'CLOSEOUT' in point:to_closeout(e)
    elif 'RETIREMENT' in point:to_closeout(e);poll(e)
    with pytest.raises(RuntimeError,match='synthetic worker interruption'):poll(e,checkpoint=interrupt(point))
    sends=e['send'].call_count
    for provider in e['providers'].values():provider.side_effect=AssertionError('No replay capture')
    with patch.object(e['transport'],'send',side_effect=AssertionError('No replay send')):
        recovered=poll(e)
    assert recovered['phase']==phase and e['send'].call_count==sends
    if phase=='WAIT_NEXT':assert recovered['completed_cycles']==1 and count(e,ARCHIVES)==1


def test_preparation_restart_uses_exact_cached_inputs(flow):
    e=flow;finish(e);resume_and_signal(e);assert poll(e)['phase']=='PREPARE_PENDING'
    with pytest.raises(RuntimeError):poll(e,checkpoint=interrupt('AFTER_NEXT_PREPARATION_ACTION_BEFORE_STATE'))
    e['clock'][0]+=timedelta(hours=2)
    for provider in e['providers'].values():provider.side_effect=AssertionError('No replay capture')
    assert poll(e)['phase']=='BUY_PENDING' and len(e['adapter_store'].requests())==3
    assert e['send'].call_count==2


def test_concurrent_pollers_submit_buy_once(flow):
    e=flow
    with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(lambda _:poll(e),range(2)))
    assert e['send'].call_count==1 and read_state(e)['phase']=='ENTRY_REVIEW'
    assert all(r['production_execution_enabled'] is False for r in rows)


def test_tampered_worker_state_blocks_before_capture(flow):
    e=flow;poll(e)
    with e['store'].db() as db:
        row=read_state(e);row['completed_cycles']=99
        db.execute('UPDATE '+STATE+' SET data=?',(json.dumps(row),))
    for p in e['providers'].values():p.reset_mock()
    with pytest.raises(ValueError,match='COORDINATOR_STATE_SIGNATURE_INVALID'):poll(e)
    for p in e['providers'].values():p.assert_not_called()
    assert e['send'].call_count==1


def test_journal_truncation_cannot_rebaseline(flow):
    e=flow;poll(e);e['path'].write_text('')
    with pytest.raises(ValueError):poll(e)
    assert e['send'].call_count==1


def test_flat_worker_waits_for_explicit_resume_without_capture(flow):
    e=flow;finish(e)
    now=(e['clock'][0]+timedelta(minutes=5-e['clock'][0].minute%5)).replace(second=0,microsecond=0);e['clock'][0]=now
    append(e['path'],[BULL],at=now.isoformat())
    result=poll(e)
    assert result['status']=='WORKER_WAITING_FOR_EXPLICIT_RESUME'
    e['providers']['next'].assert_not_called()
    assert e['store'].control()['mode']=='PAUSED' and e['send'].call_count==2


def test_reversal_exits_first_without_opposite_buy(flow):
    e=flow;to_wait_exit(e);emit_exit(e,reversal=True);assert poll(e)['phase']=='EXIT_REVIEW'
    fill(e,'SELL');poll(e);poll(e);assert poll(e)['phase']=='WAIT_NEXT'
    assert e['send'].call_count==2 and len(e['adapter_store'].requests())==2
    assert poll(e)['status']=='WORKER_WAITING_FOR_FRESH_SIGNAL'


@pytest.mark.parametrize('side',['BUY','SELL'])
def test_gate_closing_between_poll_and_action_keeps_pending_phase(flow,side):
    e=flow
    if side=='SELL':to_wait_exit(e);emit_exit(e)
    before=e['send'].call_count
    with patch.object(e['transport'],'check',side_effect=[None,port.GateClosed('PRODUCTION_MUTATIONS_CLOSED_IN_CODE')]):
        output=poll(e)
    assert output['phase']==('BUY_PENDING' if side=='BUY' else 'SELL_PENDING')
    assert e['send'].call_count==before


def test_missing_state_row_is_not_automatically_recreated(flow):
    e=flow;poll(e)
    with e['store'].db() as db:db.execute('DELETE FROM '+STATE)
    with pytest.raises(ValueError,match='COORDINATOR_STATE_MISSING_NO_REBASELINE'):poll(e)
    assert e['send'].call_count==1


def test_old_entry_is_audited_without_buy_then_fresh_entry_can_prepare(flow):
    e=flow;finish(e);resume_and_signal(e)
    e['clock'][0]+=timedelta(seconds=61)
    output=poll(e)
    assert output['status']=='WORKER_OLD_SIGNAL_NOT_ELIGIBLE' and output['phase']=='WAIT_NEXT'
    e['providers']['next'].assert_not_called();assert e['send'].call_count==2
    resume_and_signal(e)
    assert poll(e)['phase']=='PREPARE_PENDING' and poll(e)['phase']=='BUY_PENDING'
