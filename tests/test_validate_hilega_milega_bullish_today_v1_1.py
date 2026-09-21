from scripts.validate_hilega_milega_bullish_today_v1_1 import strict_bullish


def test_strict_bullish_requires_rsi_cross_ema_up():
    assert strict_bullish(40, 41, 42, 46, 45, 44)


def test_rejects_when_rsi_was_already_above_wma():
    assert not strict_bullish(43, 41, 42, 46, 45, 44)


def test_rejects_when_ema_was_already_above_wma():
    assert not strict_bullish(40, 43, 42, 46, 45, 44)


def test_rejects_when_wma_not_sloping_up():
    assert not strict_bullish(40, 41, 42, 46, 45, 41.5)


def test_slope_filter_can_be_disabled_for_diagnostic_only():
    assert strict_bullish(40, 41, 42, 46, 45, 41.5, require_upward_slopes=False)
