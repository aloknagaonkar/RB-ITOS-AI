import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import run as m

def records():
    day='2026-10-22';previous=None;out=[]
    schedule=[('09:20',['PATH1_ARMED_RSI_CROSS_EMA3_UP'],None),
      ('09:25',['ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21'],None),
      ('09:30',['STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'],'09:25'),
      ('09:35',['ENTRY_BEARISH_ROUTE_B_STRUCTURAL'],None),
      ('09:40',['STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21'],'09:35')]
    for t,names,ref in schedule:
        at=day+'T'+t+':00+05:30'
        r=dict(sequence=len(out)+1,previous_hash=previous,stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(
            policy_id=m.b.POLICY,strategy_version=m.b.VERSION,reconstructed=False,decision_timestamp=at,
            accepted_events=names,event_details=[dict(event_type=n,event_time=at,
                entry_time=at if n in m.b.ENTRIES else day+'T'+(ref or t)+':00+05:30') for n in names]))
        r['record_hash']=hashlib.sha256(json.dumps(r,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
        previous=r['record_hash'];out.append(r)
    return out

def test_real_reader_iterations_armed(tmp_path):
    rs=records();selected=m.j.select(rs,'2026-10-22')
    r=m.exercise(rs,selected,tmp_path/'armed','ARMED')
    assert r['status']=='PASS',r['checks']
    assert [f['side'] for f in r['simulated_fills']]==['BUY','SELL','BUY','SELL']

def test_pause_resume_health_and_fault_checks(tmp_path):
    rs=records();selected=m.j.select(rs,'2026-10-22')
    r=m.exercise(rs,selected,tmp_path/'resume','PAUSED_THEN_RESUME')
    assert r['status']=='PASS',r['checks']
    assert [f['side'] for f in r['simulated_fills']]==['BUY','SELL']
    assert r['final_control']['control']['mode']=='PAUSED'

def test_existing_history_never_replayed(tmp_path):
    rs=records();selected=m.j.select(rs,'2026-10-22')
    assert m.baseline_history(rs,selected,tmp_path/'history')['status']=='PASS'

def test_copy_preserves_original_chain(tmp_path):
    rs=records();p=tmp_path/'copy.jsonl';m.write_prefix(p,rs)
    assert m.b.verified_records(p)==rs

def test_installed_version_and_hashes():m.j.installed()
