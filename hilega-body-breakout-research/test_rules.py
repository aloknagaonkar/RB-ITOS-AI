import pytest
from rules import qualify,decision

def test_oct22_signal():
    f=dict(open=22617.25,high=22677.55,low=22614.60,close=22667.90,ema10=22638.310027692627,previous_ema10=22631.73447829099)
    s=qualify('BULLISH',f)
    assert s is not None
    assert decision(s,22677.90)=='ENTRY'
    assert decision(s,s['midpoint'])=='WAIT'
    assert decision(s,s['midpoint']-.01)=='CANCEL_MIDPOINT'

def test_bear_wait_until_third():
    s=dict(direction='BEARISH',high=22763.55,low=22715.55,midpoint=22739.55)
    assert [decision(s,x) for x in [22726.65,22724.30,22711.15]]==['WAIT','WAIT','ENTRY']
    assert decision(s,22740)=='CANCEL_MIDPOINT'
    assert decision(s,22715.55)=='WAIT'

def test_weak_body_rejected():
    assert qualify('BEARISH',dict(open=100,close=99,high=110,low=90,ema10=99.8,previous_ema10=100)) is None

def test_symmetric_body():
    f=dict(open=100,close=110,high=111,low=99,ema10=104,previous_ema10=103)
    assert qualify('BULLISH',f)
    reflected={k:200-v for k,v in f.items()}
    reflected['high'],reflected['low']=reflected['low'],reflected['high']
    assert qualify('BEARISH',reflected)
