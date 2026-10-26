from datetime import datetime,timedelta
from decimal import Decimal
import hashlib,pytest
from market_lab.hilega_production_foundation.core import Store,Service,SimBroker,Blocked
from market_lab.hilega_sim_allocation_v1 import synthetic_funds,summary
from market_lab.hilega_production_simulator_bridge_v1 import Bridge,POLICY,VERSION
import uuid
AT='2026-10-26T09:25:00+05:30'
def command(s,action):
    c=s.status()['control'];return s.command(action,request_id=str(uuid.uuid4()),expected_version=c['version'],session_date=c['session_date'],actor='central-allocation-test')
@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY');monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')
    clock=[datetime.fromisoformat(AT)-timedelta(seconds=1)];store=Store(tmp_path/'sim.sqlite');broker=SimBroker(store)
    s=Service(store,broker,lambda:clock[0]);return s,broker,clock

def ready(env,cash='100000'):
    s,b,clock=env;synthetic_funds(s,cash);command(s,'reconcile');command(s,'resume');clock[0]=datetime.fromisoformat(AT)
def entry(env,signal='s1',instrument='SIMULATOR|CE',price='100'):
    return env[0].submit_entry(signal_id=signal,signal_at=env[2][0].isoformat(),instrument=instrument,quantity=65,price=price)
def held(env):return env[0].status()['allocation']['held_total']
def test_workspace_missing_funds_blocks_resume(env):
    command(env[0],'reconcile')
    with pytest.raises(Blocked,match='SYNTHETIC_FUNDS_NOT_CONFIGURED'):command(env[0],'resume')
def test_direct_public_submit_cannot_bypass(env):
    ready(env,'100')
    with pytest.raises(Blocked,match='HALF_CASH'):entry(env)
    assert not env[1].orders()
def test_hold_precedes_transport(env):
    ready(env);env[1].before_accept=lambda: summary(env[0].store,env[0].now())['held_total']=='6600.00' or pytest.fail('No hold')
    entry(env);assert held(env)=='6600.00'
def test_entry_fill_holds_exit_releases(env):
    ready(env);row=entry(env);env[1].fill(row['id'],65,'100');command(env[0],'reconcile');assert held(env)=='6600.00'
    env[0].strategy_exit(position_id=row['id'],exit_id='sell',price='100');assert held(env)=='0.00'
def test_partial_pause_cleanup_releases(env):
    ready(env);row=entry(env);env[1].fill(row['id'],20,'100');command(env[0],'reconcile');assert held(env)=='6600.00'
    command(env[0],'pause');assert held(env)=='0.00' and not any(env[1].positions().values())
def test_pause_established_retains(env):
    ready(env)
    row=entry(env)
    env[1].fill(row['id'],65,'100')
    command(env[0],'reconcile')
    assert env[0].store.intents()[0]['status']=='FILLED'
    command(env[0],'pause')
    assert held(env)=='6600.00'
    assert env[1].positions()['SIMULATOR|CE']==65

def test_pause_unobserved_full_fill_flattens_and_releases(env):
    ready(env)
    row=entry(env)
    env[1].fill(row['id'],65,'100')
    command(env[0],'pause')
    assert held(env)=='0.00'
    assert not any(env[1].positions().values())
    assert env[0].status()['control']['mode']=='PAUSED'
    assert [f['side'] for f in env[1].fills()]==['BUY','SELL']
def test_pending_exit_retains(env):
    ready(env);row=entry(env);env[1].fill(row['id'],65,'100');env[1].auto_fill_sells=False
    env[0].strategy_exit(position_id=row['id'],exit_id='sell',price='100');assert held(env)=='6600.00'
    env[1].fill('sell',65,'100');command(env[0],'reconcile');assert held(env)=='0.00'
def test_unknown_unavailable_retains(env):
    ready(env);env[1].timeout_after_accept=True;env[1].before_accept=lambda:setattr(env[1],'unavailable',True)
    row=entry(env);assert row['status']=='UNKNOWN' and held(env)=='6600.00'
    env[1].unavailable=False;env[1].before_accept=None;command(env[0],'reconcile');assert held(env)=='0.00'
def test_stale_funds_block_entry_but_not_exit(env):
    ready(env);row=entry(env);env[1].fill(row['id'],65,'100');env[2][0]+=timedelta(seconds=31)
    env[0].strategy_exit(position_id=row['id'],exit_id='sell',price='100');assert held(env)=='0.00'
    command(env[0],'reconcile')
    with pytest.raises(Blocked,match='FUNDS_STALE'):entry(env,'s2')
def test_env_flag_removal_cannot_disable_enrollment(env,monkeypatch):
    ready(env,'100');monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','DISABLED')
    with pytest.raises(Blocked,match='HALF_CASH'):entry(env)
def test_crash_after_hold_before_intent_blocks_restart(env,monkeypatch):
    ready(env)
    def crash(row):raise SystemExit('fixture crash')
    monkeypatch.setattr(env[0],'_submit',crash)
    with pytest.raises(SystemExit):entry(env)
    assert held(env)=='6600.00'
    s=Service(env[0].store,env[1],lambda:env[2][0]);command(s,'reconcile')
    assert not s.status()['control']['reconciled'] and s.status()['allocation']['status']=='ALLOCATION_OUTCOME_REVIEW_REQUIRED'
    assert not env[1].orders()
def test_duplicate_signal_no_second_hold(env):
    ready(env);entry(env)
    with pytest.raises(Blocked):entry(env)
    assert held(env)=='6600.00' and len(env[1].orders())==1

def event(at,names,ref=None):
    return dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(policy_id=POLICY,strategy_version=VERSION,reconstructed=False,
        decision_timestamp=at,accepted_events=names,event_details=[dict(event_type=n,event_time=at,entry_time=ref if n.startswith('STRUCTURAL_EXIT') else at) for n in names]))
def test_journal_bridge_reversal_uses_central_gate(env,tmp_path):
    ready(env);bridge=Bridge(env[0],tmp_path/'ownership.sqlite',auto_fill_entries=True)
    bridge.process(event(AT,['ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21']));assert held(env)=='6600.00'
    env[2][0]+=timedelta(minutes=5);synthetic_funds(env[0],'100000');bridge.poll()
    bridge.process(event(env[2][0].isoformat(),['STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21','ENTRY_BEARISH_ROUTE_B_STRUCTURAL'],AT))
    assert [x['side'] for x in env[1].fills()]==['BUY','SELL','BUY']
    assert held(env)=='6600.00' and len(env[0].status()['allocation']['reservations'])==2

def test_bridge_low_cash_no_order(env,tmp_path):
    ready(env,'100');bridge=Bridge(env[0],tmp_path/'ownership.sqlite',auto_fill_entries=True)
    bridge.process(event(AT,['ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21']))
    assert not env[1].orders() and any('HALF_CASH' in r.get('reason','') for r in bridge.rows())
def test_status_exposes_only_synthetic_allocation(env):
    ready(env);a=env[0].status()['allocation'];assert a['evidence_mode']=='SYNTHETIC_SIMULATOR_ONLY' and a['production_execution_enabled'] is False

def test_concurrent_public_callers_only_one_order(env):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    ready(env);barrier=Barrier(2)
    def work(n):
        barrier.wait()
        try:return entry(env,'concurrent'+str(n))['status']
        except Blocked:return 'BLOCKED'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(work,[1,2]))
    assert sorted(results)==['BLOCKED','OPEN'] and held(env)=='6600.00' and len(env[1].orders())==1

def test_cli_once_requires_explicit_fixture_cash(tmp_path):
    import subprocess,sys,os,json
    from pathlib import Path
    root=Path(__file__).resolve().parents[1];source=tmp_path/'source.jsonl';source.touch();empty=tmp_path/'empty.env';empty.touch()
    db=tmp_path/'sim.sqlite'
    env=dict(PATH=os.environ.get('PATH',''),PYTHONPATH=os.environ.get('PYTHONPATH',str(root/'backend')),HILEGA_PRODUCTION_WORKSPACE_MODE='SIMULATION_ONLY',
        HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='1',HILEGA_PRODUCTION_SIM_DB=str(db))
    result=subprocess.run([sys.executable,str(root/'scripts/hilega_production_simulator_bridge.py'),'--once','--env-file',str(empty),
        '--source',str(source),'--synthetic-cash','100000'],env=env,cwd=tmp_path,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
    s=Service(Store(db),SimBroker(Store(db)),worker_start=False)
    assert s.status()['allocation']['synthetic_available_cash']=='100000' and s.status()['control']['mode']=='PAUSED'
    assert not s.broker.orders()
