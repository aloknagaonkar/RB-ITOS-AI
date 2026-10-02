from market_lab.midpoint_aug25_oi_magnitude_replay_v1 import pct, state

def test_pct():
    assert pct(112,100)==12.0
    assert pct(90,100)==-10.0

def test_states():
    assert state(5,8)=="LONG_BUILDUP"
    assert state(-5,8)=="SHORT_BUILDUP"
    assert state(5,-8)=="SHORT_COVERING"
    assert state(-5,-8)=="LONG_UNWINDING"
