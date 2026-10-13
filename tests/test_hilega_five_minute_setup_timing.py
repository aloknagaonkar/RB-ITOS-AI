from datetime import datetime,timedelta
import json,math
from market_lab.domain import IST
from market_lab.hilega_milega_strategy_v1 import IndicatorSnapshot,StrategyEvent
from market_lab import hilega_v2_alignment_replay_v1 as engine
from scripts.validate_hilega_alignment_live_parity import verify

def raw(day):
    start=datetime.fromisoformat(day+'T09:15:00+05:30')
    rows=[]
    for i in range(375):
        price=22000+60*math.sin(i/19)+20*math.sin(i/4)+i*.04
        rows.append(dict(timestamp=(start+timedelta(minutes=i)).isoformat(),open=price-1,high=price+2,low=price-2,close=price,volume=0))
    return rows

def test_synthetic_replay_and_live_share_five_minute_setups(tmp_path):
    days=['2026-10-08','2026-10-09','2026-10-12']
    for day in days:(tmp_path/(day+'.json')).write_text(json.dumps({'candles':raw(day)}))
    result=engine.replay(days[-1],raw(days[-1]),[(day,raw(day)) for day in days[:-1]])
    assert result['setup_attempts'], 'fixture must exercise setup generation'
    assert all(datetime.fromisoformat(s['time']).minute%5==0 for s in result['setup_attempts'])
    assert all(datetime.fromisoformat(a['checkpoint']).minute%5==0 or a['checks'] or a['transitions'] for a in result['audit'])
    matched=verify(days[-1],[tmp_path])
    assert matched['status']=='PASS' and matched['entries']>0

def test_entry_does_not_wait_for_next_five_minute_boundary():
    gate=engine.WmaGapGate();signal=datetime(2026,10,12,9,25,tzinfo=IST)
    gate.signal(StrategyEvent('ENTRY_PATH1_ROUTE_B_STRUCTURAL',signal,None,'IDLE','ARMED'),signal)
    ref=IndicatorSnapshot(40,40,40)
    entries,checks=gate.evaluate(minute=signal,current=IndicatorSnapshot(49,46,41),reference=ref,price=100)
    assert not entries and checks[0]['persistence_pass'] is False
    entries,checks=gate.evaluate(minute=signal+timedelta(minutes=1),current=IndicatorSnapshot(50,47,41.2),reference=ref,price=101)
    assert len(entries)==1 and entries[0].entry_time.minute==27
    assert checks[0]['persistence_pass'] and checks[0]['gap_expanding_pass']

def test_confirmation_expiry_and_audit_schedule():
    gate=engine.WmaGapGate();at=datetime(2026,10,12,9,25,tzinfo=IST)
    gate.signal(StrategyEvent('ENTRY_PATH1_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED'),at)
    entries,checks=gate.evaluate(minute=at+timedelta(minutes=10),current=IndicatorSnapshot(40,40,40),reference=IndicatorSnapshot(40,40,40),price=100)
    assert not entries and 'WINDOW_EXPIRED' in checks[0]['reasons'] and not gate.pending
    assert not engine.decision_checkpoint(boundary=False,checks=[],entries=[],exits=[])
    assert engine.decision_checkpoint(boundary=True,checks=[],entries=[],exits=[])
    assert engine.decision_checkpoint(boundary=False,checks=checks,entries=[],exits=[])
