"""Offline integration tests. Synthetic option prices; never broker requests."""
from datetime import datetime,timedelta
import copy,hashlib,json,uuid
import pytest
from market_lab.hilega_production_foundation.core import Store,Service,SimBroker,Blocked
from market_lab import hilega_production_simulator_bridge_v1 as b

DAY='2026-10-25'
BULL='ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21'
BEAR='ENTRY_BEARISH_ROUTE_B_STRUCTURAL'
BX='STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'
SX='STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21'
def stamp(t):return DAY+'T'+t+':00+05:30'
def record(t='09:25',names=None,ref='09:25'):
    names=names if names is not None else [BULL]
    return dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(policy_id=b.POLICY,strategy_version=b.VERSION,
        reconstructed=False,decision_timestamp=stamp(t),accepted_events=names,event_details=[dict(event_type=n,event_time=stamp(t),
        entry_time=stamp(t) if n in b.ENTRIES else stamp(ref),qualified_signal_time=stamp('09:20')) for n in names]))
def command(s,action,**kw):
    c=s.status()['control'];return s.command(action,request_id=str(uuid.uuid4()),expected_version=c['version'],
        session_date=c['session_date'],actor='fixture-operator',**kw)
@pytest.fixture
def env(tmp_path):
    clock=[datetime.fromisoformat(stamp('09:24'))+timedelta(seconds=59)]
    store=Store(tmp_path/'sim.sqlite');broker=SimBroker(store);s=Service(store,broker,lambda:clock[0])
    bridge=b.Bridge(s,tmp_path/'ownership-fixture.sqlite',auto_fill_entries=True)
    command(s,'reconcile');command(s,'resume');clock[0]=datetime.fromisoformat(stamp('09:25'))
    return s,broker,bridge,clock

def buys(env):return [o for o in env[1].orders() if o['side']=='BUY']
def sells(env):return [o for o in env[1].orders() if o['side']=='SELL']
def entry(env):return env[2].process(record())
def move(env,t):env[3][0]=datetime.fromisoformat(stamp(t))
def test_current_policy_version_is_pinned():
    from market_lab.hilega_combined_policy_v1 import POLICY_ID,VERSION
    assert (b.POLICY,b.VERSION)==(POLICY_ID,VERSION)
def test_armed_event_does_not_buy(env):
    r=env[2].process(record(names=['PATH1_ARMED_RSI_CROSS_EMA3_UP']))
    assert buys(env)==[] and r['production_execution_enabled'] is False

def test_confirmed_entry_links_signal_order_and_execution(env):
    r=entry(env);assert len(buys(env))==1 and len(env[1].fills())==1
    assert r['ownership_status']['positions'][0]['entry_filled']==65
    assert r['ownership_status']['positions'][0]['remaining']==65
    assert env[1].fills()[0]['evidence_mode']=='SIMULATOR_GENERATED'
def test_nifty_price_not_used_as_option_price(env):
    r=record();r['payload']['event_details'][0]['entry_price']=24000.0
    env[2].process(r);assert buys(env)[0]['average_price']=='100'
def test_pause_blocks_entry_from_shared_control_state(env):
    command(env[0],'pause');r=entry(env)
    assert not buys(env) and r['events'][0]['state']=='BLOCKED'
def test_blocked_signal_not_replayed_after_resume(env):
    command(env[0],'pause');entry(env);command(env[0],'reconcile');command(env[0],'resume')
    env[3][0]+=timedelta(seconds=1);entry(env);assert not buys(env)
def test_duplicate_event_idempotent(env):
    entry(env);entry(env);assert len(buys(env))==1 and len(env[1].fills())==1

def test_different_source_hash_same_execution_not_duplicate(env):
    r=record();r['record_hash']='first';env[2].process(r);r['record_hash']='second';env[2].process(r)
    assert len(buys(env))==1

def test_recovered_record_ignored(env):
    r=record();r['status']='RECOVERED';env[2].process(r);assert not buys(env)
def test_reconstructed_record_ignored(env):
    r=record();r['payload']['reconstructed']=True;env[2].process(r);assert not buys(env)
def test_wrong_policy_pauses_and_rejects(env):
    r=record();r['payload']['policy_id']='OTHER'
    with pytest.raises(Blocked):env[2].process(r)
    assert not buys(env) and env[0].status()['control']['mode']=='PAUSED'
def test_candidate_without_entry_time_cannot_enter(env):
    r=record();r['payload']['event_details'][0]['entry_time']=None
    with pytest.raises(Blocked):env[2].process(r)
    assert not buys(env)
def test_stale_confirmed_entry_not_taken(env):
    env[3][0]+=timedelta(seconds=61);r=entry(env)
    assert not buys(env) and r['events'][0]['state']=='BLOCKED'
def test_non_boundary_rejected(env):
    r=record('09:26')
    with pytest.raises(Blocked):env[2].process(r)
def test_ambiguous_two_entries_rejected(env):
    with pytest.raises(Blocked):env[2].process(record(names=[BULL,BEAR]))
    assert not buys(env)
def test_duplicate_name_rejected(env):
    with pytest.raises(Blocked):env[2].process(record(names=[BULL,BULL]))

def test_strategy_exit_does_not_invoke_manual_pause(env):
    entry(env);move(env,'09:30');r=env[2].process(record('09:30',[BX]))
    assert len(sells(env))==1 and env[1].positions()['SIMULATOR|CE']==0
    assert env[0].status()['control']['mode']=='ARMED' and r['ownership_status']['positions'][0]['remaining']==0

def test_exit_while_paused_still_closes_existing_position(env):
    entry(env);command(env[0],'pause');move(env,'09:30');env[2].process(record('09:30',[BX]))
    assert env[1].positions()['SIMULATOR|CE']==0 and env[0].status()['control']['mode']=='PAUSED'
def test_immediate_reversal_sell_fills_before_new_buy(env):
    entry(env);move(env,'09:30');r=env[2].process(record('09:30',[BX,BEAR]))
    assert [f['side'] for f in env[1].fills()]==['BUY','SELL','BUY']
    assert env[1].positions()=={'SIMULATOR|CE':0,'SIMULATOR|PE':65}
    assert r['ownership_status']['status']=='RECONCILED_OFFLINE_FIXTURE'
def test_pending_sell_prevents_reversal_buy(env):
    entry(env);env[1].auto_fill_sells=False;move(env,'09:30');r=env[2].process(record('09:30',[BX,BEAR]))
    assert len(buys(env))==1 and len(sells(env))==1
    assert any(e['role']=='ENTRY' and e['state']=='WAIT_EXIT' for e in r['events'])
def test_pending_sell_then_fill_allows_fresh_reversal(env):
    entry(env);env[1].auto_fill_sells=False;move(env,'09:30');env[2].process(record('09:30',[BX,BEAR]))
    sell=next(i for i in env[0].store.intents() if i['side']=='SELL')
    env[3][0]+=timedelta(seconds=10);env[1].fill(sell['id'],65,100);env[2].poll()
    assert len(buys(env))==2 and env[1].positions()['SIMULATOR|PE']==65

def test_pause_during_reversal_blocks_opposite_buy(env):
    entry(env);env[1].auto_fill_sells=False;move(env,'09:30');env[2].process(record('09:30',[BX,BEAR]))
    command(env[0],'pause');sell=next(i for i in env[0].store.intents() if i['side']=='SELL')
    env[3][0]+=timedelta(seconds=10);env[1].fill(sell['id'],65,100);env[2].poll()
    assert len(buys(env))==1 and env[1].positions()['SIMULATOR|CE']==0

def test_pause_exactly_before_submit_wins(env,monkeypatch):
    original=env[0].submit_entry
    def submit(**kw):command(env[0],'pause');return original(**kw)
    monkeypatch.setattr(env[0],'submit_entry',submit);entry(env)
    assert not buys(env)
def test_waited_reversal_cannot_bypass_signal_age(env):
    entry(env);env[1].auto_fill_sells=False;move(env,'09:30');env[2].process(record('09:30',[BX,BEAR]))
    sell=next(i for i in env[0].store.intents() if i['side']=='SELL')
    env[3][0]+=timedelta(seconds=61);env[1].fill(sell['id'],65,100);env[2].poll()
    assert len(buys(env))==1

def test_external_activity_does_not_create_a_fake_owned_exit(env):
    entry(env);env[1].external_sell('SIMULATOR|CE',10,100)
    r=env[2].poll();assert r['status']=='REVIEW_REQUIRED'
    assert env[0].status()['control']['mode']=='PAUSED'

def test_old_exit_cannot_close_new_trade(env):
    entry(env);move(env,'09:30');env[2].process(record('09:30',[BX,BEAR]));move(env,'09:35')
    r=env[2].process(record('09:35',[SX],ref='09:25'))
    assert env[1].positions()['SIMULATOR|PE']==65 and len(sells(env))==1
    assert any(e['reason']=='EXIT_POSITION_REFERENCE_MISMATCH' for e in r['events'])
def test_stale_exit_not_applied_to_current_position(env):
    entry(env);move(env,'09:35');env[2].process(record('09:30',[BX]))
    assert env[1].positions()['SIMULATOR|CE']==65

def test_duplicate_exit_does_not_oversell(env):
    entry(env);move(env,'09:30');r=record('09:30',[BX]);env[2].process(r);env[2].process(r)
    assert len(sells(env))==1

def test_manual_ui_style_exit_is_linked(env):
    entry(env);move(env,'09:26');i=next(i for i in env[0].store.intents() if i['side']=='BUY')
    command(env[0],'exit',position_id=i['id']);proof=env[2].poll()
    assert proof['status']=='RECONCILED_OFFLINE_FIXTURE' and proof['positions'][0]['remaining']==0
    assert env[0].status()['control']['mode']=='PAUSED'

def test_simulated_partial_fill_execution_journal(env):
    env[2].auto=False;entry(env);i=next(i for i in env[0].store.intents() if i['side']=='BUY')
    env[1].fill(i['id'],20,100);env[1].fill(i['id'],65,101)
    fills=env[1].fills();assert [f['quantity'] for f in fills]==[20,45]
    from decimal import Decimal
    assert abs(sum(Decimal(f['price'])*f['quantity'] for f in fills)-Decimal(65)*101)<Decimal('0.00000001')
    proof=env[2].poll();assert proof['positions'][0]['entry_filled']==65

def test_identical_cumulative_fill_not_another_execution(env):
    entry(env);i=next(i for i in env[0].store.intents() if i['side']=='BUY');env[1].fill(i['id'],65,100)
    assert len(env[1].fills())==1

def test_legacy_filled_order_does_not_backfill_fake_trade(env):
    env[2].auto=False;entry(env);i=next(i for i in env[0].store.intents() if i['side']=='BUY')
    o=env[1].find(i['id']);o.update(filled=65,status='FILLED',average_price='100');env[1]._save(o)
    proof=env[2].poll();assert proof['status']=='REVIEW_REQUIRED' and env[1].fills()==[]

def test_timeout_accepted_entry_never_duplicates(env):
    env[1].timeout_after_accept=True;entry(env);env[2].poll();entry(env)
    assert len(buys(env))==1 and env[0].status()['control']['mode']=='PAUSED'

def test_crash_before_ack_recovers_existing_intent(env,monkeypatch):
    original=env[0].submit_entry
    def crash(**kw):original(**kw);raise SystemExit('simulated crash')
    monkeypatch.setattr(env[0],'submit_entry',crash)
    with pytest.raises(SystemExit):entry(env)
    monkeypatch.setattr(env[0],'submit_entry',original);env[2].poll()
    assert len(buys(env))==1 and any(r['state']=='SUBMITTED' for r in env[2].rows())

def test_crash_before_submission_requires_review_not_retry(env,monkeypatch):
    def crash(**kw):raise SystemExit('simulated crash')
    monkeypatch.setattr(env[0],'submit_entry',crash)
    with pytest.raises(SystemExit):entry(env)
    env[2].poll();assert not buys(env) and env[0].status()['control']['mode']=='PAUSED'

def test_source_chain_rejects_tampering(tmp_path):
    row=dict(record('09:25'),sequence=1,previous_hash=None)
    row['record_hash']=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
    p=tmp_path/'audit.jsonl';p.write_text(json.dumps(row)+'\n');assert len(b.verified_records(p))==1
    row['payload']['accepted_events']=[];p.write_text(json.dumps(row)+'\n')
    with pytest.raises(Blocked):b.verified_records(p)
def test_source_incomplete_line_rejected(tmp_path):
    p=tmp_path/'audit.jsonl';p.write_text('{}')
    with pytest.raises(Blocked):b.verified_records(p)


def test_equivalent_timezone_event_does_not_duplicate(env):
    entry(env);r=record();r['payload']['decision_timestamp']='2026-10-25T03:55:00+00:00'
    env[2].process(r);assert len(buys(env))==1

def write_chain(path,rows):
    previous=None;out=[]
    for i,r in enumerate(rows,1):
        r=copy.deepcopy(r);r.update(sequence=i,previous_hash=previous)
        r['record_hash']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
        previous=r['record_hash'];out.append(r)
    path.write_text(''.join(json.dumps(r)+'\n' for r in out))

def test_source_baseline_does_not_replay_existing_signal(env,tmp_path):
    p=tmp_path/'audit.jsonl';write_chain(p,[record()])
    assert env[2].run_source_once(p)['status']=='BASELINED_WAIT_NEXT_FRESH_SIGNAL'
    assert not buys(env)
def test_only_new_fresh_source_event_after_baseline_can_enter(env,tmp_path):
    p=tmp_path/'audit.jsonl';write_chain(p,[]);env[2].run_source_once(p)
    write_chain(p,[record()]);env[2].run_source_once(p);env[2].run_source_once(p)
    assert len(buys(env))==1

def test_source_truncation_blocks_and_pauses(env,tmp_path):
    p=tmp_path/'audit.jsonl';write_chain(p,[record()]);env[2].run_source_once(p);write_chain(p,[])
    with pytest.raises(Blocked):env[2].run_source_once(p)
    assert env[0].status()['control']['mode']=='PAUSED'
def test_prior_source_hash_replacement_blocks(env,tmp_path):
    p=tmp_path/'audit.jsonl';write_chain(p,[record()]);env[2].run_source_once(p)
    r=record();r['payload']['nifty_close']=24000;write_chain(p,[r])
    with pytest.raises(Blocked):env[2].run_source_once(p)
    assert not buys(env)
def test_new_wrong_version_source_event_blocks(env,tmp_path):
    p=tmp_path/'audit.jsonl';write_chain(p,[]);env[2].run_source_once(p)
    r=record();r['payload']['strategy_version']='unexpected-version';write_chain(p,[r])
    with pytest.raises(Blocked):env[2].run_source_once(p)
    assert not buys(env)

def test_workspace_api_pause_blocks_bridge_entry(env,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from market_lab import hilega_production_workspace_v1 as w
    token='fixture-control-token-012345678901234567890'
    monkeypatch.setenv('HILEGA_PRODUCTION_CONTROL_TOKEN',token)
    monkeypatch.delenv('HILEGA_PRODUCTION_CONTROL_TOKEN_FILE',raising=False)
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY')
    monkeypatch.setenv('HILEGA_PRODUCTION_BROKER_OBSERVE','0')
    monkeypatch.setattr(w,'service',lambda:env[0])
    app=FastAPI();app.include_router(w.router);c=TestClient(app);control=env[0].status()['control']
    r=c.post('/api/hilega-production/commands',headers={'Authorization':'Bearer '+token},json=dict(
        action='pause',request_id=str(uuid.uuid4()),expected_version=control['version'],session_date=control['session_date'],confirmation='SIMULATION_ONLY'))
    assert r.status_code==200 and r.json()['snapshot']['control']['mode']=='PAUSED'
    entry(env);assert not buys(env)

def test_partial_cancelled_strategy_sell_requires_review_not_oversell(env):
    entry(env);env[1].auto_fill_sells=False;move(env,'09:30');env[2].process(record('09:30',[BX,BEAR]))
    sell=next(i for i in env[0].store.intents() if i['side']=='SELL')
    env[3][0]+=timedelta(seconds=10);env[1].fill(sell['id'],20,100);env[1].cancel(sell['id']);env[2].poll()
    assert env[1].positions()['SIMULATOR|CE']==45 and len(sells(env))==1 and len(buys(env))==1
    assert env[0].status()['control']['mode']=='PAUSED'
