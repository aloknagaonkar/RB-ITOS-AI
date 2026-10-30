from market_lab.midpoint_v2_fbr_structural_stop_diagnostics_v1 import structural_invalidation


def test_bullish_fbr_invalidates_on_close_below_midpoint():
    assert structural_invalidation("BULLISH", 100.0, 99.9) is True
    assert structural_invalidation("BULLISH", 100.0, 100.0) is False
    assert structural_invalidation("BULLISH", 100.0, 101.0) is False


def test_bearish_fbr_invalidates_on_close_above_midpoint():
    assert structural_invalidation("BEARISH", 100.0, 100.1) is True
    assert structural_invalidation("BEARISH", 100.0, 100.0) is False
    assert structural_invalidation("BEARISH", 100.0, 99.0) is False
