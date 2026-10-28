"""VM checks for signal-frame timing and EMA seeding; never imports live adapters."""
import sys
from pathlib import Path
from datetime import datetime,timedelta,date,time
import pytest
sys.path.insert(0,str(Path(__file__).parent))
import core,hybrid

def rows(day):
    at=datetime.combine(date.fromisoformat(day),time(9,15),core.IST)
    return [dict(timestamp=(at+timedelta(minutes=i)).isoformat(),open=100+i*.01,high=101+i*.01,low=99+i*.01,close=100.5+i*.01,volume=1) for i in range(375)]

@pytest.fixture
def inputs():
    day='2026-10-26';start=date(2026,9,1)
    return [(str(start+timedelta(days=i)),rows(str(start+timedelta(days=i)))) for i in range(20)],rows(day),day

@pytest.mark.parametrize('interval,first,last,count',[(1,'09:16','14:55',340),(3,'09:18','14:54',113),(5,'09:20','14:55',68)])
def test_complete_signal_boundaries(inputs,interval,first,last,count):
    warm,raw,day=inputs;frames=hybrid.build_signal_frames(warm,raw,day,interval)
    stamps=list(frames)
    assert len(stamps)==count
    assert stamps[0].strftime('%H:%M')==first and stamps[-1].strftime('%H:%M')==last
    assert all(datetime.fromisoformat(f['available_at'])-datetime.fromisoformat(f['candle_label'])==timedelta(minutes=interval) for f in frames.values())

@pytest.mark.parametrize('interval',[1,3,5])
def test_future_minutes_do_not_change_completed_first_frame(inputs,interval):
    warm,raw,day=inputs
    before=hybrid.build_signal_frames(warm,raw,day,interval)
    altered=[dict(r) for r in raw]
    for r in altered[interval:]:
        for k in ['open','high','low','close']:r[k]+=100
    after=hybrid.build_signal_frames(warm,altered,day,interval)
    first=min(before)
    assert before[first]==after[first]

def test_ema_uses_signal_interval_not_one_minute(inputs):
    warm,raw,day=inputs
    frames=hybrid.build_signal_frames(warm,raw,day,3)
    first=frames[min(frames)]
    tracker=core.policy5.PriceFrames()
    for d,rr in warm:
        for b in core.aggregate(rr,d,3,datetime.combine(date.fromisoformat(d),time(15,30),core.IST)):tracker.seed(b)
    expected_previous=tracker.value
    expected=expected_previous+(2/11)*(raw[2]['close']-expected_previous)
    assert first['previous_ema10']==expected_previous
    assert first['ema10']==expected
