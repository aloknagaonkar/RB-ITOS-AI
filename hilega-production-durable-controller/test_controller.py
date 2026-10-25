"""VM-only tests. Local fixture venue, real SQLite locks/process interruptions."""
import multiprocessing as mp
import os
import threading
from datetime import datetime,timedelta
import pytest
from controller import Controller,Blocked
DAY='2026-10-26'
BEFORE=datetime.fromisoformat(DAY+'T09:24:59+05:30')
AT=BEFORE+timedelta(seconds=1)

@pytest.fixture
def env(tmp_path):
    clock=[BEFORE];c=Controller(tmp_path/'state.sqlite',session_date=DAY,clock=lambda:clock[0])
    c.funds('100000');version=c.resume('resume-1',1)['version'];clock[0]=AT
    return c,clock,version

def buy(e,key='entry'):
    c,clock,v=e;return c.entry(key,expected_version=v,signal_at=clock[0].isoformat())

def test_new_install_paused(tmp_path):
    c=Controller(tmp_path/'a.sqlite',session_date=DAY,clock=lambda:BEFORE)
    assert c.status()['control']['mode']=='PAUSED'
    with pytest.raises(Blocked):c.resume('r',1)

def test_reservation_and_intent_atomic_rollback(env):
    c,_,_=env
    class Stop(BaseException):pass
    def fail(stage):
        if stage=='IN_PREPARE_TRANSACTION':raise Stop()
    c.checkpoint=fail
    with pytest.raises(Stop):buy(env)
    assert c.status()['plans']==[] and c.status()['held_cents']==0
    assert c.status()['fixture_orders']==[]

def test_full_lifecycle_retains_then_releases(env):
    c,_,_=env;entry=buy(env)
    assert c.status()['held_cents']==660000
    c.venue.fill(entry['order_id'],65);c.reconcile();c.pause()
    assert len(c.status()['fixture_orders'])==1 and c.status()['held_cents']==660000
    sell=c.exit('entry');assert c.status()['held_cents']==660000
    c.venue.fill(sell['order_id'],65,'105');c.reconcile();c.reconcile()
    assert c.status()['held_cents']==0
    assert len([e for e in c.status()['events'] if e['type']=='TERMINAL_FLAT_RELEASE'])==1

def test_partial_pause_cleanup(env):
    c,_,_=env;entry=buy(env);c.venue.fill(entry['order_id'],20);c.reconcile();c.pause()
    sell=next(p for p in c.status()['plans'] if p['side']=='SELL')
    assert sell['quantity']==20 and c.status()['held_cents']==660000
    c.exit('entry');assert len(c.status()['fixture_orders'])==2
    c.venue.fill(sell['order_id'],20);c.reconcile();assert c.status()['held_cents']==0

def test_zero_fill_pause_release(env):
    c,_,_=env;buy(env);c.pause()
    assert c.status()['held_cents']==0 and c.status()['fixture_orders'][0]['status']=='CANCELLED'

def test_repeated_entry_never_dispatches_twice(env):
    c,_,_=env;first=buy(env);c.pause();again=buy(env)
    assert first['id']==again['id'] and len(c.status()['fixture_orders'])==1

def test_request_conflict(env):
    c,clock,v=env;buy(env)
    with pytest.raises(Blocked,match='REQUEST_ID_CONFLICT'):c.entry('entry',expected_version=v,signal_at=clock[0].isoformat(),ask='101')

def test_stale_resume_cannot_override_pause(env):
    c,_,v=env;c.pause()
    with pytest.raises(Blocked,match='STALE_CONTROL_VERSION'):c.resume('stale',v)
    assert c.status()['control']['mode']=='PAUSED'

def test_command_replay_returns_receipt_not_rearming(env):
    c,_,_=env;c.pause();result=c.resume('resume-1',1)
    assert result['mode']=='ARMED' # original command receipt
    assert c.status()['control']['mode']=='PAUSED' # authoritative current state

def test_command_id_cannot_change_version(env):
    c,_,_=env
    with pytest.raises(Blocked,match='COMMAND_ID_CONFLICT'):c.resume('resume-1',999)

def test_stale_funds_blocks_buy_but_exit_remains(env):
    c,clock,v=env;entry=buy(env);c.venue.fill(entry['order_id'],65);c.reconcile()
    clock[0]+=timedelta(seconds=40)
    assert c.exit('entry')['side']=='SELL'

def test_stale_funds_rejects_new_entry(env):
    c,clock,_=env;clock[0]+=timedelta(seconds=40)
    with pytest.raises(Blocked,match='FUNDS_STALE'):buy(env)
    assert c.status()['fixture_orders']==[]

def test_pre_resume_signal_rejected(env):
    c,_,v=env
    with pytest.raises(Blocked,match='SIGNAL_NOT_FRESH'):c.entry('old',expected_version=v,signal_at=BEFORE.isoformat())

def test_pending_exit_blocks_opposite_entry(env):
    c,_,v=env;entry=buy(env);c.venue.fill(entry['order_id'],65);c.reconcile();c.exit('entry')
    # Controller is paused; neither stale Resume nor BUY bypasses SELL.
    with pytest.raises(Blocked):c.resume('r2',c.status()['control']['version'])
    with pytest.raises(Blocked):buy(env,'opposite')
    assert len(c.status()['fixture_orders'])==2

def test_separate_client_does_not_auto_pause_or_arm(env):
    c,clock,_=env;before=c.status()['control']
    other=Controller(c.store.path,session_date=DAY,clock=lambda:clock[0])
    assert other.status()['control']==before

def test_session_pinned(env):
    c,_,_=env
    with pytest.raises(Blocked,match='SESSION_OR_SCOPE'):Controller(c.store.path,session_date='2026-10-27',clock=lambda:AT)

def test_pause_request_before_dispatch_prevents_order(env):
    c,_,_=env
    def hook(stage):
        if stage=='AFTER_PREPARE_COMMIT':c.request_pause()
    c.checkpoint=hook;row=buy(env)
    assert row['state']=='CANCELLED' and c.status()['held_cents']==0
    assert c.status()['fixture_orders']==[] and c.status()['pause_requested']

def test_pause_during_submission_cleanup(env):
    c,_,_=env;reached=threading.Event();release=threading.Event();errors=[]
    def hook(stage):
        if stage=='AFTER_FIXTURE_ACCEPT_BEFORE_ACK':
            reached.set()
            if not release.wait(10):raise RuntimeError('TEST_SYNC_TIMEOUT')
    c.checkpoint=hook
    def worker():
        try:buy(env)
        except BaseException as exc:errors.append(str(exc))
    thread=threading.Thread(target=worker);thread.start()
    assert reached.wait(10)
    c.request_pause();assert c.status()['pause_requested'];release.set();thread.join(10)
    assert not thread.is_alive() and not errors
    assert c.status()['control']['mode']=='PAUSED'
    assert c.status()['held_cents']==0 and len(c.status()['fixture_orders'])==1
    assert c.status()['fixture_orders'][0]['status']=='CANCELLED'

def crash_child(path,version,stage):
    c=Controller(path,session_date=DAY,clock=lambda:AT)
    def fault(point):
        if point==stage:os._exit(70)
    c.checkpoint=fault
    c.entry('crash-entry',expected_version=version,signal_at=AT.isoformat())

@pytest.mark.parametrize('stage',['AFTER_PREPARE_COMMIT','AFTER_IN_FLIGHT_COMMIT','AFTER_FIXTURE_ACCEPT_BEFORE_ACK'])
def test_actual_process_kill_recovery(env,stage):
    c,_,v=env;ctx=mp.get_context('fork');p=ctx.Process(target=crash_child,args=(c.store.path,v,stage));p.start();p.join(15)
    if p.is_alive():p.kill();p.join();pytest.fail('Child timed out')
    assert p.exitcode==70
    state=c.recover();assert state['control']['mode']=='PAUSED' and state['held_cents']==660000
    count=len(state['fixture_orders'])
    assert count==(1 if stage=='AFTER_FIXTURE_ACCEPT_BEFORE_ACK' else 0)
    again=c.entry('crash-entry',expected_version=v,signal_at=AT.isoformat())
    assert len(c.status()['fixture_orders'])==count
    assert again['id']=='crash-entry'
    if stage=='AFTER_IN_FLIGHT_COMMIT':
        with pytest.raises(Blocked):c.pause()
        assert c.status()['held_cents']==660000 # absence is not rejection proof
    else:
        c.pause();assert c.status()['held_cents']==0

def compete(path,version,key,barrier,queue):
    c=Controller(path,session_date=DAY,clock=lambda:AT)
    barrier.wait(10)
    try:c.entry(key,expected_version=version,signal_at=AT.isoformat());queue.put('ACCEPTED')
    except Blocked:queue.put('BLOCKED')

def test_two_actual_processes_only_one_entry(env):
    c,_,v=env;ctx=mp.get_context('fork');barrier=ctx.Barrier(2);queue=ctx.Queue()
    ps=[ctx.Process(target=compete,args=(c.store.path,v,key,barrier,queue)) for key in ['one','two']]
    for p in ps:p.start()
    for p in ps:
        p.join(15)
        if p.is_alive():p.kill();p.join();pytest.fail('Competing child timed out')
        assert p.exitcode==0
    assert sorted([queue.get(timeout=3),queue.get(timeout=3)])==['ACCEPTED','BLOCKED']
    assert len(c.status()['fixture_orders'])==1 and c.status()['held_cents']==660000

def test_fill_arrives_during_cancel_cleanup_sells_actual_quantity(env):
    c,_,_=env;entry=buy(env);original=c.venue.cancel
    def fill_then_cancel(oid):
        c.venue.fill(oid,20);original(oid)
    c.venue.cancel=fill_then_cancel;c.pause()
    sell=next(p for p in c.status()['plans'] if p['side']=='SELL')
    assert sell['quantity']==20 and c.status()['held_cents']==660000
    c.venue.fill(sell['order_id'],20);c.reconcile()
    assert c.status()['held_cents']==0

def test_release_transaction_failure_retains_hold_until_retry(env):
    c,_,_=env;entry=buy(env);c.venue.fill(entry['order_id'],65);c.reconcile()
    sell=c.exit('entry');c.venue.fill(sell['order_id'],65)
    class Stop(BaseException):pass
    def fail(stage):
        if stage=='BEFORE_FLAT_RELEASE_COMMIT':raise Stop()
    c.checkpoint=fail
    with pytest.raises(Stop):c.reconcile()
    assert c.status()['held_cents']==660000
    c.checkpoint=lambda stage:None;c.recover()
    assert c.status()['held_cents']==0 and c.status()['control']['mode']=='PAUSED'

def test_ack_durable_before_reconciliation_recovery(env):
    c,_,v=env;ctx=mp.get_context('fork');p=ctx.Process(target=crash_child,args=(c.store.path,v,'AFTER_ACK_COMMIT'))
    p.start();p.join(15)
    if p.is_alive():p.kill();p.join();pytest.fail('Child timed out')
    assert p.exitcode==70
    state=c.recover()
    assert state['plans'][0]['order_id'] and len(state['fixture_orders'])==1
    c.pause();assert c.status()['held_cents']==0
