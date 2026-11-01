from market_lab.midpoint_v2_break_and_go_early_path_diagnostics_v1 import classify_path

def test_immediate_follow_through():
    assert classify_path(1.0, -2.0, -3.0) == "IMMEDIATE_FOLLOW_THROUGH"

def test_delayed_follow_through_from_30m():
    assert classify_path(-1.0, 5.0, -2.0) == "DELAYED_FOLLOW_THROUGH"

def test_delayed_follow_through_from_60m():
    assert classify_path(0.0, -5.0, 3.0) == "DELAYED_FOLLOW_THROUGH"

def test_failed_continuation():
    assert classify_path(-1.0, -2.0, 0.0) == "FAILED_CONTINUATION"
