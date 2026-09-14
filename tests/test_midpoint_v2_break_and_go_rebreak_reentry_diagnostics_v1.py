from market_lab.midpoint_v2_break_and_go_rebreak_reentry_diagnostics_v1 import normalize_stop_regime

def test_normalize_initial_sl5():
    assert normalize_stop_regime({"stop_regime":"INITIAL_SL5"}) == "INITIAL_SL5"

def test_normalize_sl5_alias():
    assert normalize_stop_regime({"stop_type":"SL5"}) == "INITIAL_SL5"

def test_normalize_breakeven():
    assert normalize_stop_regime({"active_stop_regime":"BREAKEVEN"}) == "BREAKEVEN"

def test_missing_regime():
    assert normalize_stop_regime({}) is None
