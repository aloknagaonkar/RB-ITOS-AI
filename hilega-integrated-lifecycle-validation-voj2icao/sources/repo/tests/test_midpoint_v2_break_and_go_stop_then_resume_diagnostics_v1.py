from market_lab.midpoint_v2_break_and_go_stop_then_resume_diagnostics_v1 import classify_resume

def test_resumed_15m():
    assert classify_resume(1.0, -5.0, -10.0) == "RESUMED_BY_15M"

def test_resumed_30m():
    assert classify_resume(-1.0, 2.0, -10.0) == "RESUMED_BY_30M"

def test_resumed_60m():
    assert classify_resume(0.0, -2.0, 3.0) == "RESUMED_BY_60M"

def test_no_resume():
    assert classify_resume(-1.0, 0.0, -3.0) == "NO_RESUME_BY_60M"
