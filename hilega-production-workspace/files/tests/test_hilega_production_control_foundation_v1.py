from datetime import datetime,timedelta
from pathlib import Path
import sys
import threading
import uuid
import pytest
from market_lab.hilega_production_foundation.core import Store,Service,SimBroker,Blocked,plan

def rid():return str(uuid.uuid4())
@pytest.fixture
def setup(tmp_path):
    clock=[datetime.fromisoformat('2026-10-25T10:00:00+05:30')]
    store=Store(tmp_path/'simulation.sqlite');broker=SimBroker(store)
    service=Service(store,broker,lambda:clock[0])
    return service,broker,store,clock

def cmd(s,action,**kw):
    c=s.status()['control']
    return s.command(action,request_id=kw.pop('request_id',rid()),expected_version=kw.pop('expected_version',c['version']),
        session_date=kw.pop('session_date',c['session_date']),actor='test-operator',**kw)

def arm(env):
    s,b,store,clock=env;cmd(s,'reconcile');cmd(s,'resume');clock[0]+=timedelta(seconds=1)

def buy(env,signal='signal-1'):
    s,b,store,clock=env
    return s.submit_entry(signal_id=signal,signal_at=clock[0].isoformat(),instrument='TEST|OPTION',quantity=65,price=100)

def filled(env):
    row=buy(env);env[1].fill(row['id'],65,100);cmd(env[0],'reconcile');return row

def test_new_install_paused(setup):
    assert setup[0].status()['control']['mode']=='PAUSED'
    assert setup[0].status()['production_execution_enabled'] is False

def test_paused_entry_blocked(setup):
    with pytest.raises(Blocked,match='TRADING_PAUSED'):buy(setup)
    assert setup[1].positions()=={}

def test_resume_needs_reconciliation(setup):
    with pytest.raises(Blocked,match='RECONCILIATION_REQUIRED'):cmd(setup[0],'resume')

def test_fresh_signal_entry_only(setup):
    arm(setup);assert buy(setup)['status']=='OPEN'

def test_pre_resume_signal_rejected(setup):
    old=setup[3][0];arm(setup)
    with pytest.raises(Blocked,match='PRE_RESUME'):setup[0].submit_entry(signal_id='old',signal_at=old.isoformat(),instrument='TEST',quantity=65,price=100)

def test_duplicate_signal_rejected(setup):
    arm(setup);buy(setup)
    with pytest.raises(Blocked,match='ALREADY_CONSUMED'):buy(setup)

def test_pause_cancels_unfilled(setup):
    arm(setup);buy(setup);cmd(setup[0],'pause')
    assert setup[0].status()['label']=='PAUSED_NO_PENDING_ENTRIES'
    assert setup[1].positions()['TEST|OPTION']==0

def test_partial_fill_during_cancel_is_flattened(setup):
    arm(setup);buy(setup);setup[1].fill_on_cancel=20;cmd(setup[0],'pause')
    assert setup[1].positions()['TEST|OPTION']==0
    sells=[i for i in setup[2].intents() if i['side']=='SELL']
    assert len(sells)==1 and sells[0]['quantity']==20

def test_partial_fill_before_cancel_is_flattened(setup):
    arm(setup);row=buy(setup);setup[1].fill(row['id'],30,100);cmd(setup[0],'pause')
    assert setup[1].positions()['TEST|OPTION']==0

def test_established_position_retained_on_pause(setup):
    arm(setup);filled(setup);cmd(setup[0],'pause')
    assert setup[1].positions()['TEST|OPTION']==65
    assert setup[0].status()['label']=='PAUSED_EXISTING_POSITION_OPEN'

def test_flatten_closes_established(setup):
    arm(setup);filled(setup);cmd(setup[0],'flatten')
    assert setup[1].positions()['TEST|OPTION']==0

def test_manual_exit_closes_once(setup):
    arm(setup);row=filled(setup);cmd(setup[0],'exit',position_id=row['id']);cmd(setup[0],'exit',position_id=row['id'])
    assert len([i for i in setup[2].intents() if i['side']=='SELL'])==1

def test_exit_partial_sell_stays_pending(setup):
    arm(setup);row=filled(setup);setup[1].auto_fill_sells=False
    cmd(setup[0],'exit',position_id=row['id'])
    assert setup[0].status()['label']=='STOPPING_CANCEL_OR_FLATTEN_PENDING'
    sell=next(i for i in setup[2].intents() if i['side']=='SELL')
    setup[1].fill(sell['id'],20,101);cmd(setup[0],'reconcile')
    assert setup[0].status()['ledger_remaining_quantity']==45
    assert len([i for i in setup[2].intents() if i['side']=='SELL'])==1

def test_timeout_never_resubmits(setup):
    arm(setup);setup[1].timeout_after_accept=True;row=buy(setup)
    assert row['status']=='UNKNOWN'
    assert setup[0].status()['control']['mode']=='PAUSED'
    cmd(setup[0],'reconcile') # Find accepted order, cancel it, no second BUY.
    assert len([i for i in setup[2].intents() if i['side']=='BUY'])==1
    assert setup[1].positions()['TEST|OPTION']==0

def test_missing_order_evidence_blocks(setup,monkeypatch):
    arm(setup);buy(setup)
    monkeypatch.setattr(setup[1],'find',lambda _:None)
    cmd(setup[0],'reconcile')
    assert setup[0].status()['label']=='BLOCKED_RECONCILIATION_REQUIRED'

def test_repeated_command_idempotent(setup):
    s=setup[0];key=rid();c=s.status()['control'];args=dict(request_id=key,expected_version=c['version'],actor='test',session_date=c['session_date'])
    first=s.command('pause',**args);second=s.command('pause',**args)
    assert second['idempotent_replay'] and first['status']==second['status']

def test_request_id_cannot_change_action(setup):
    s=setup[0];key=rid();cmd(s,'pause',request_id=key)
    with pytest.raises(Blocked,match='REUSED'):cmd(s,'reconcile',request_id=key)

def test_stale_resume_cannot_undo_pause(setup):
    s=setup[0];cmd(s,'reconcile');old=s.status()['control']['version'];cmd(s,'pause')
    with pytest.raises(Blocked,match='STALE_STATE'):cmd(s,'resume',expected_version=old)

def test_new_session_unarmed(setup):
    arm(setup);setup[3][0]+=timedelta(days=1)
    assert setup[0].status()['control']['mode']=='PAUSED'

def test_restart_requires_recovery(setup):
    arm(setup);s,b,store,clock=setup
    restarted=Service(store,b,lambda:clock[0])
    assert restarted.status()['control']['mode']=='PAUSED'
    assert restarted.status()['control']['reconciled'] is False

def test_readonly_client_invocation_preserves_pause(setup):
    s,b,store,clock=setup;cmd(s,'pause')
    observer=Service(store,b,lambda:clock[0],worker_start=False)
    assert observer.status()['control']['mode']=='PAUSED'

def test_external_full_exit_blocks_without_fake_pnl(setup):
    arm(setup);filled(setup);setup[1].external_sell('TEST|OPTION',65,110);cmd(setup[0],'reconcile')
    status=setup[0].status()
    assert status['control']['mode']=='PAUSED'
    assert status['label']=='BLOCKED_RECONCILIATION_REQUIRED'
    assert status['positions'][0]['external_observed_quantity']==0
    assert not any(i['side']=='SELL' for i in setup[2].intents())

def test_external_partial_exit_does_not_oversell(setup):
    arm(setup);row=filled(setup);setup[1].external_sell('TEST|OPTION',20,110)
    cmd(setup[0],'exit',position_id=row['id'])
    assert setup[1].positions()['TEST|OPTION']==45
    assert not any(i['side']=='SELL' for i in setup[2].intents())

def test_broker_unavailable_pause_not_successful_flat(setup):
    arm(setup);buy(setup);setup[1].unavailable=True;cmd(setup[0],'pause')
    assert setup[0].status()['label']=='BLOCKED_RECONCILIATION_REQUIRED'
    assert setup[0].status()['control']['mode']=='PAUSED'

def test_stale_reconciliation_blocks_entry(setup):
    arm(setup);setup[3][0]+=timedelta(seconds=31)
    with pytest.raises(Blocked,match='RECONCILIATION_STALE'):buy(setup)

def test_second_entry_with_exposure_rejected(setup):
    arm(setup);filled(setup)
    with pytest.raises(Blocked,match='POSITION_ALREADY_OPEN'):buy(setup,'second')

def test_fill_regression_blocks(setup):
    arm(setup);row=filled(setup);latest=next(i for i in setup[2].intents() if i['id']==row['id'])
    e=setup[1].find(row['id']);e['filled']=20
    with pytest.raises(Blocked,match='FILL_REGRESSION'):setup[0]._apply(latest,e)

def test_pause_waits_for_inflight_submission_then_cancels(setup):
    arm(setup);s,b,store,clock=setup;entered=threading.Event();release=threading.Event();errors=[]
    def hook():
        entered.set()
        if not release.wait(3):raise RuntimeError('TEST_BARRIER_TIMEOUT')
    b.before_accept=hook
    def entry():
        try:buy(setup)
        except BaseException as e:errors.append(e)
    def pause():
        try:cmd(s,'pause')
        except BaseException as e:errors.append(e)
    t1=threading.Thread(target=entry);t1.start();assert entered.wait(2)
    t2=threading.Thread(target=pause);t2.start();release.set();t1.join(5);t2.join(5)
    assert not t1.is_alive() and not t2.is_alive() and not errors
    assert s.status()['control']['mode']=='PAUSED'
    assert b.positions()['TEST|OPTION']==0
    with pytest.raises(Blocked,match='TRADING_PAUSED'):buy(setup,'after-pause')

def test_two_clients_share_authoritative_state(setup):
    arm(setup);s,b,store,clock=setup
    other_store=Store(store.path);other=Service(other_store,SimBroker(other_store),lambda:clock[0],worker_start=False)
    old=other.status()['control']['version'];cmd(s,'pause')
    with pytest.raises(Blocked,match='STALE_STATE'):cmd(other,'resume',expected_version=old)

CONFIG=dict(strike_offsets=[0],lots_per_strike=1,allocation_fraction='0.5',daily_loss_limit=None)
CONTRACT=[dict(offset=0,instrument='TEST',lot_size=65,price=100,estimated_charges=10,buffer=100)]
def test_plan_one_lot_half_cash():
    r=plan(CONFIG,CONTRACT,20000);assert r['eligible'] and r['cap']=='10000.0'
    assert r['legs'][0]['quantity']==65 and not r['production_eligible']
def test_plan_over_budget_rejected():assert not plan(CONFIG,CONTRACT,10000)['eligible']
def test_duplicate_offsets_rejected():
    with pytest.raises(Blocked):plan(dict(CONFIG,strike_offsets=[0,0]),CONTRACT,20000)
def test_invalid_lots_rejected():
    with pytest.raises(Blocked):plan(dict(CONFIG,lots_per_strike=0),CONTRACT,20000)
def test_four_strikes_total_budget():
    contracts=[dict(CONTRACT[0],offset=n,instrument='TEST'+str(n)) for n in [-2,-1,0,1]]
    r=plan(dict(CONFIG,strike_offsets=[-2,-1,0,1]),contracts,60000)
    assert r['eligible'] and len(r['legs'])==4
