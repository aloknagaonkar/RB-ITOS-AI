import importlib.util
from pathlib import Path
import pytest
from market_lab.hilega_production_foundation.core import Blocked
spec=importlib.util.spec_from_file_location('journal_validation_runner',Path(__file__).with_name('run.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
DAY='2026-10-22'
BULL='ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21'
BEAR='ENTRY_BEARISH_ROUTE_B_STRUCTURAL'
BX='STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'
SX='STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21'
def record(t,names,ref=None,seq=1):
    at=DAY+'T'+t+':00+05:30'
    return dict(sequence=seq,record_hash='fixture',stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(
        policy_id=m.b.POLICY,strategy_version=m.b.VERSION,reconstructed=False,decision_timestamp=at,
        accepted_events=names,event_details=[dict(event_type=n,event_time=at,
        entry_time=at if n in m.b.ENTRIES else DAY+'T'+ref+':00+05:30',qualified_signal_time=None) for n in names]))
def sample():
    return m.select([record('09:25',[BULL]),record('09:30',[BX,BEAR],'09:25',2),record('09:35',[SX],'09:30',3)],DAY)
def test_armed_recorded_events_reconcile_and_reverse(tmp_path):
    r=m.scenario(sample(),tmp_path/'armed','ARMED')
    assert r['status']=='PASS'
    assert [x['side'] for x in r['simulated_fills']]==['BUY','SELL','BUY','SELL']
    assert not any(r['final_positions'].values())
def test_paused_never_submits(tmp_path):
    r=m.scenario(sample(),tmp_path/'paused','PAUSED')
    assert r['status']=='PASS' and not r['simulated_orders']
def test_resume_does_not_replay_consumed_signal(tmp_path):
    r=m.scenario(sample(),tmp_path/'resume','RESUME_AFTER_FIRST_BLOCKED_ENTRY')
    assert r['status']=='PASS'
    assert len([x for x in r['simulated_orders'] if x['side']=='BUY'])==1
    assert r['events'][0]['state']=='BLOCKED'
def test_version_does_not_silently_fallback():
    r=record('09:25',[BULL]);r['payload']['strategy_version']='older'
    with pytest.raises(Blocked):m.select([r],DAY)
def test_reconstructed_not_executable():
    r=record('09:25',[BULL]);r['payload']['reconstructed']=True
    with pytest.raises(Blocked):m.select([r],DAY)
def test_time_regression_rejected():
    with pytest.raises(Blocked):m.select([record('09:30',[BULL]),record('09:25',[BEAR])],DAY)
def test_installed_files_match_validated_dependencies():m.installed()
