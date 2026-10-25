import sys,copy
from pathlib import Path
from datetime import datetime,timedelta
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from adapter import Store,Adapter,FakeTransport,Blocked,TransportTimeout
AT='2026-10-26T09:25:00+05:30'
@pytest.fixture
def env(tmp_path):
    clock=[datetime.fromisoformat(AT)-timedelta(seconds=1)];store=Store(tmp_path/'contract.sqlite');transport=FakeTransport(store,lambda:clock[0]);a=Adapter(store,transport,lambda:clock[0])
    a.resume();clock[0]=datetime.fromisoformat(AT);return a,transport,clock

def buy(env,key='entry1',instrument='FIXTURE|CE'):
    return env[0].buy(key,instrument=instrument,quantity=65,limit_price='100',signal_at=env[2][0].isoformat())
def fills(env):return env[0].store.rows('fake_fills')
def orders(env):return env[0].store.rows('fake_orders')
def test_durable_before_transport(env):
    def inspect(row):
        # Read durable DB directly: do NOT re-enter adapter.status control lock.
        persisted=env[0].store.rows('intents');assert persisted[0]['status']=='IN_FLIGHT'
        assert persisted[0]['request_id']==row['request_id']
    env[1].before_place=inspect;buy(env)
    assert env[0].store.rows('audit')[1]['type']=='INTENT_DURABLE_BEFORE_TRANSPORT'
def test_duplicate_request_one_post(env):
    buy(env);assert buy(env)['idempotent_replay'] and len(orders(env))==1

def test_request_conflict_rejected(env):
    buy(env)
    with pytest.raises(Blocked):buy(env,instrument='FIXTURE|PE')
def test_accepted_timeout_reconciles_original_order(env):
    env[1].timeout_after_accept=True;assert buy(env)['status']=='UNKNOWN'
    assert buy(env)['idempotent_replay'] and len(orders(env))==1
    env[0].reconcile();assert env[0].status()['intents'][0]['status']=='OPEN'
    assert env[0].status()['control']['mode']=='PAUSED'
def test_timeout_without_acceptance_never_retries(env):
    env[1].timeout_before_accept=True;buy(env);buy(env)
    assert not orders(env)
    with pytest.raises(Blocked,match='ACCEPTANCE_UNRESOLVED'):env[0].reconcile()
def test_partial_fills_reconcile_incrementally(env):
    row=buy(env);env[1].fill(row['order_id'],20,'100');env[0].reconcile();assert env[0].status()['intents'][0]['filled']==20
    env[1].fill(row['order_id'],65,'101');env[0].reconcile()
    assert sum(x['quantity'] for x in fills(env))==65 and len(fills(env))==2

def test_duplicate_execution_not_recounted(env):
    row=buy(env);env[1].fill(row['order_id'],65,'100');env[0].reconcile();env[0].reconcile()
    assert len(fills(env))==1

def test_fill_regression_rejected(env):
    row=buy(env);env[1].fill(row['order_id'],20,'100');env[0].reconcile();s=env[1].snapshot();s['generation']+=1;s['orders'][0]['filled']=10
    with pytest.raises(Blocked):env[0].reconcile(s)
def test_position_mismatch_rejected(env):
    buy(env);s=env[1].snapshot();s['generation']+=1;s['positions'][0]['quantity']=10
    with pytest.raises(Blocked):env[0].reconcile(s)
def test_missing_fill_rejected(env):
    row=buy(env);env[1].fill(row['order_id'],20,'100');env[0].reconcile();s=env[1].snapshot();s['generation']+=1;s['fills']=[]
    with pytest.raises(Blocked):env[0].reconcile(s)
def test_partial_fill_during_pause_cancel_flattened(env):
    buy(env);env[1].fill_on_cancel=20;env[0].pause()
    assert [f['side'] for f in fills(env)]==['BUY','SELL']
    assert env[1].snapshot()['positions'][0]['quantity']==0 and env[0].status()['control']['mode']=='PAUSED'
def test_established_fill_retained_on_pause(env):
    row=buy(env);env[1].fill(row['order_id'],65,'100');env[0].reconcile();env[0].pause()
    assert len(orders(env))==1 and env[1].snapshot()['positions'][0]['quantity']==65

def test_manual_exit_closes_once(env):
    row=buy(env);env[1].fill(row['order_id'],65,'100');env[0].reconcile();env[0].exit('entry1');env[0].exit('entry1')
    assert len(orders(env))==2 and env[1].snapshot()['positions'][0]['quantity']==0

def test_reversal_sell_pending_blocks_opposite_buy(env):
    row=buy(env);env[1].fill(row['order_id'],65,'100');env[0].reconcile();env[1].auto_sell_fill=False
    sell=env[0].exit('entry1',manual=False)
    with pytest.raises(Blocked):buy(env,'entry2','FIXTURE|PE')
    env[1].fill(sell['order_id'],65,'100');env[0].reconcile();env[2][0]+=timedelta(seconds=1)
    buy(env,'entry3','FIXTURE|PE');assert [o['side'] for o in orders(env)]==['BUY','SELL','BUY']

def test_partial_cancelled_exit_requires_review_no_second_sell(env):
    row=buy(env);env[1].fill(row['order_id'],65,'100');env[0].reconcile();env[1].auto_sell_fill=False
    sell=env[0].exit('entry1');env[1].fill(sell['order_id'],20,'100');env[1].cancel(sell['order_id']);env[0].reconcile()
    with pytest.raises(Blocked):env[0].exit('entry1')
    assert len(orders(env))==2 and env[1].snapshot()['positions'][0]['quantity']==45

def test_cancel_timeout_blocks_without_guessing(env):
    buy(env);env[1].cancel_timeout=True
    with pytest.raises(TransportTimeout):env[0].pause()
    assert env[0].status()['control']['mode']=='PAUSED'
    env[1].cancel_timeout=False;env[0].reconcile();assert env[0].status()['intents'][0]['status']=='CANCELLED'
def test_restart_pauses_and_recovers_known_original(env):
    env[1].timeout_after_accept=True;buy(env);a=Adapter(env[0].store,env[1],lambda:env[2][0]);a.reconcile()
    assert a.status()['control']['mode']=='PAUSED' and len(orders(env))==1

def test_crash_before_acceptance_retains_unresolved_intent(env):
    def crash(row):raise SystemExit('fixture crash')
    env[1].before_place=crash
    with pytest.raises(SystemExit):buy(env)
    assert env[0].store.rows('intents')[0]['status']=='IN_FLIGHT' and not orders(env)
    with pytest.raises(Blocked):env[0].reconcile()
def test_snapshot_scope_mismatch(env):
    s=env[1].snapshot();s['account_scope']='OTHER'
    with pytest.raises(Blocked):env[0].reconcile(s)
def test_stale_snapshot(env):
    s=env[1].snapshot();env[2][0]+=timedelta(seconds=31)
    with pytest.raises(Blocked):env[0].reconcile(s)
def test_same_generation_changed_payload(env):
    env[0].reconcile();s=env[1].snapshot();s['orders']=[{}]
    with pytest.raises(Blocked,match='SAME_GENERATION'):env[0].reconcile(s)
def test_unmapped_order_not_adopted(env):
    env[1].place(dict(request_id='external',instrument='FIXTURE|OTHER',product='I',side='BUY',quantity=65,price='100'))
    with pytest.raises(Blocked,match='UNMAPPED'):env[0].reconcile()
def test_live_transport_impossible(env):
    class RealLike:pass
    with pytest.raises(Blocked):Adapter(env[0].store,RealLike(),lambda:env[2][0])
def test_paused_entry_does_not_create_intent(env):
    env[0].pause()
    with pytest.raises(Blocked):buy(env)
    assert not orders(env) and not env[0].store.rows('intents')

def test_explicit_rejection_is_terminal_not_unknown(env):
    env[1].reject_next=True;row=buy(env)
    assert row['status']=='REJECTED' and row['filled']==0
    assert buy(env)['idempotent_replay'] and len(orders(env))==1
