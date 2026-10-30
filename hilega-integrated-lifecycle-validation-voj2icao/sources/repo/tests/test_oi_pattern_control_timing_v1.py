from market_lab.oi_pattern_control_timing_v1 import candidate,persistence
from datetime import datetime,timedelta

def row(t,imb,pcr,sess):
    return {"timestamp":t.isoformat(),"imbalance_5m":imb,"pcr_change_5m":pcr,
            "session_imbalance":sess}

def test_bullish_candidate():
    t=datetime(2026,1,1,10,0)
    a=row(t,-2,-.1,-5)
    b=row(t+timedelta(minutes=5),3,.05,-2)
    assert candidate(a,b,"BULLISH")
    assert not candidate(a,b,"BEARISH")

def test_bearish_candidate():
    t=datetime(2026,1,1,10,0)
    a=row(t,2,.1,5)
    b=row(t+timedelta(minutes=5),-3,-.05,2)
    assert candidate(a,b,"BEARISH")
    assert not candidate(a,b,"BULLISH")

def test_persistence():
    t=datetime(2026,1,1,10,0)
    xs=[row(t+timedelta(minutes=5*i),v,.1,i) for i,v in enumerate([1,2,3,-1])]
    assert persistence(xs,0,"BULLISH",3)
    assert not persistence(xs,0,"BULLISH",4)
