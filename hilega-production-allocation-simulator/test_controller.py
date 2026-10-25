import sys,uuid
from pathlib import Path
from datetime import datetime,timedelta
import pytest
sys.path.insert(0,str(Path(__file__).parent))
import journal_support as j
from controller import Controller,AllocationBlocked
from market_lab.hilega_production_foundation.core import Store,Service,SimBroker,Blocked
DAY='2026-10-26';AT=DAY+'T09:25:00+05:30'
def leg():return dict(instrument='SIMULATOR|CE',side='CE',offset=0,lot_size=65,lots=1,quantity=65,ask='100',buffer='100')
@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')
    clock=[datetime.fromisoformat(AT)-timedelta(seconds=1)]
    store=Store(tmp_path/'sim.sqlite');broker=SimBroker(store);s=Service(store,broker,lambda:clock[0])
    c=Controller(s,tmp_path/'allocation.sqlite');c.funds('f1','100000')
    j.command(s,'reconcile');j.command(s,'resume');clock[0]=datetime.fromisoformat(AT)
    return c,s,broker,clock

def submit(env,signal='s1',plan=None):return env[0].submit(signal_id=signal,signal_at=env[3][0].isoformat(),snapshot_id='f1',legs=plan or [leg()])
def held(env):return env[0].ledger.status()['held_total']
def test_reserve_before_order_transport(env):
    env[2].before_accept=lambda: held(env)=='6600.00' or pytest.fail('No prior reservation')
    submit(env);assert held(env)=='6600.00' and len(env[2].orders())==1

def test_insufficient_allocation_sends_nothing(env):
    env[0].funds('f2','100')
    with pytest.raises(AllocationBlocked):env[0].submit(signal_id='s1',signal_at=AT,snapshot_id='f2',legs=[leg()])
    assert not env[2].orders() and not env[1].store.intents()
def test_paused_never_reserves_or_submits(env):
    j.command(env[1],'pause')
    with pytest.raises(Blocked):submit(env)
    assert held(env)=='0.00' and not env[2].orders()
def test_duplicate_no_resubmission(env):
    submit(env);r=submit(env)
    assert r['status']=='ALREADY_CONSUMED_NO_RESUBMISSION' and len(env[2].orders())==1 and held(env)=='6600.00'
def test_plan_conflict(env):
    submit(env);p=leg();p['ask']='101'
    with pytest.raises(AllocationBlocked):submit(env,plan=[p])
def test_partial_fill_cancel_and_cleanup_release(env):
    row=submit(env);env[2].fill(row['id'],20,'100');env[0].sync()
    assert held(env)=='6600.00'
    j.command(env[1],'pause');env[0].sync()
    assert held(env)=='0.00' and not any(env[2].positions().values())
def test_full_entry_fill_retains_until_strategy_exit(env):
    row=submit(env);env[2].fill(row['id'],65,'100');env[0].sync()
    assert held(env)=='6600.00'
    env[1].strategy_exit(position_id=row['id'],exit_id='exit1',price='100');env[0].sync()
    assert held(env)=='0.00'
def test_pending_exit_keeps_hold(env):
    row=submit(env);env[2].fill(row['id'],65,'100');env[0].sync();env[2].auto_fill_sells=False
    env[1].strategy_exit(position_id=row['id'],exit_id='exit1',price='100');env[0].sync()
    assert held(env)=='6600.00'
    env[2].fill('exit1',65,'100');env[0].sync();assert held(env)=='0.00'
def test_timeout_accepted_never_duplicates(env):
    env[2].timeout_after_accept=True;submit(env);submit(env)
    assert len(env[2].orders())==1 and held(env)=='0.00' and env[1].status()['control']['mode']=='PAUSED'
    assert env[2].orders()[0]['status']=='CANCELLED' # reconciled terminal zero-fill proof
def test_restart_retains_hold(env):
    submit(env);again=Controller(env[1],env[0].ledger.path);again.sync();assert again.ledger.status()['held_total']=='6600.00'
def test_reservation_crash_before_intent_holds_unknown(env,monkeypatch):
    def crash(**kw):raise SystemExit('fixture crash')
    monkeypatch.setattr(env[1],'submit_entry',crash)
    with pytest.raises(SystemExit):submit(env)
    env[0].sync()
    assert held(env)=='6600.00' and env[0].ledger.status()['reservations'][0]['state']=='UNKNOWN'
    assert not env[2].orders() and env[1].status()['control']['mode']=='PAUSED'
def test_pause_between_reserve_and_service_gate(env,monkeypatch):
    original=env[1].submit_entry
    def pause_first(**kw):j.command(env[1],'pause');return original(**kw)
    monkeypatch.setattr(env[1],'submit_entry',pause_first)
    with pytest.raises(Blocked):submit(env)
    assert held(env)=='0.00' and not env[2].orders()
def test_pause_retains_established_position_hold(env):
    row=submit(env);env[2].fill(row['id'],65,'100');env[0].sync();j.command(env[1],'pause');env[0].sync()
    assert held(env)=='6600.00' and env[2].positions()['SIMULATOR|CE']==65

def test_reversal_cannot_buy_until_sell_complete(env):
    row=submit(env);env[2].fill(row['id'],65,'100');env[0].sync();env[2].auto_fill_sells=False
    env[1].strategy_exit(position_id=row['id'],exit_id='exit1',price='100');env[0].sync()
    p=leg();p.update(instrument='SIMULATOR|PE',side='PE')
    with pytest.raises(Blocked):submit(env,'s2',[p])
    assert len([x for x in env[2].orders() if x['side']=='BUY'])==1
    env[2].fill('exit1',65,'100');env[0].sync()
    # Failed signal is consumed. A later fresh signal can reserve after flat.
    env[3][0]+=timedelta(seconds=1);env[0].submit(signal_id='s3',signal_at=env[3][0].isoformat(),snapshot_id='f1',legs=[p])
    assert [x['side'] for x in env[2].fills()]==['BUY','SELL']
    assert len([x for x in env[2].orders() if x['side']=='BUY'])==2

def test_multi_leg_explicitly_unsupported_no_orders(env):
    p=leg();p.update(instrument='SIMULATOR|CE2',offset=1)
    with pytest.raises(AllocationBlocked,match='SINGLE_LEG'):submit(env,plan=[leg(),p])
    assert held(env)=='0.00' and not env[2].orders()
def test_installed_simulator_dependencies():j.installed()

def test_unknown_with_broker_unavailable_retains_hold(env):
    env[2].timeout_after_accept=True
    env[2].before_accept=lambda:setattr(env[2],'unavailable',True)
    submit(env)
    assert held(env)=='6600.00' and env[0].ledger.status()['reservations'][0]['state']=='UNKNOWN'
    env[2].before_accept=None;env[2].unavailable=False;env[0].sync()
    assert held(env)=='0.00' and env[2].orders()[0]['status']=='CANCELLED'
