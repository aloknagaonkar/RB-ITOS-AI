from datetime import datetime, timezone
from market_lab.midpoint_aug25_oi_magnitude_replay_v1_fix1 import (
    pct, state, aggregate_same_strikes
)

def test_pct():
    assert pct(110,100) == 10.0
    assert pct(90,100) == -10.0

def test_state():
    assert state(5,5) == "LONG_BUILDUP"
    assert state(-5,5) == "SHORT_BUILDUP"
    assert state(5,-5) == "SHORT_COVERING"
    assert state(-5,-5) == "LONG_UNWINDING"

def test_same_strike_aggregation_ignores_moved_atm_offsets():
    prev=[
        {"strike":24100.0,"ce_oi":100.0,"pe_oi":100.0},
        {"strike":24150.0,"ce_oi":200.0,"pe_oi":200.0},
        {"strike":24200.0,"ce_oi":300.0,"pe_oi":300.0},
    ]
    cur=[
        {"strike":24100.0,"ce_oi":110.0,"pe_oi":100.0},
        {"strike":24150.0,"ce_oi":220.0,"pe_oi":220.0},
        {"strike":24200.0,"ce_oi":330.0,"pe_oi":360.0},
    ]
    out=aggregate_same_strikes(cur,prev,24150.0,1)
    assert out["common_strikes"] == [24100.0,24150.0,24200.0]
    assert round(out["ce_oi_change_pct_5m"],6) == 10.0
