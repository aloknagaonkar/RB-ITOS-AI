from scripts.validate_hilega_milega_bullish_transition_audit_v1_2 import detect_upward_transitions


def test_detects_rsi_cross_ema_up_independently():
    x = detect_upward_transitions(40, 41, 50, 43, 42, 49)
    assert x["rsi_cross_ema_up"]
    assert not x["rsi_cross_wma_up"]
    assert not x["ema_cross_wma_up"]


def test_detects_rsi_cross_wma_up_independently():
    x = detect_upward_transitions(45, 55, 50, 52, 54, 51)
    assert x["rsi_cross_wma_up"]
    assert not x["rsi_cross_ema_up"]
    assert not x["ema_cross_wma_up"]


def test_detects_ema_cross_wma_up_independently():
    x = detect_upward_transitions(60, 49, 50, 61, 52, 51)
    assert x["ema_cross_wma_up"]
    assert not x["rsi_cross_ema_up"]
    assert not x["rsi_cross_wma_up"]


def test_reports_all_three_when_they_happen_together():
    x = detect_upward_transitions(40, 41, 42, 46, 45, 44)
    assert x["rsi_cross_ema_up"]
    assert x["rsi_cross_wma_up"]
    assert x["ema_cross_wma_up"]
    assert x["rsi_slope_up"]
    assert x["ema3_slope_up"]
    assert x["wma21_slope_up"]
