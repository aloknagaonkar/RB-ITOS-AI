from scripts.validate_hilega_milega_original_sequence_wma_slope_v2_6 import (
    cross_up,
    wma_slope_up,
)


def test_wma_slope_up_only_when_current_is_greater():
    assert wma_slope_up(50.0, 50.1) is True
    assert wma_slope_up(50.0, 50.0) is False
    assert wma_slope_up(50.0, 49.9) is False


def test_cross_up():
    assert cross_up(48.0, 50.0, 51.0, 50.5) is True


def test_ema_fresh_cross_is_not_required_by_wma_slope_rule():
    # This test documents the intended architecture:
    # EMA may already be above WMA; V2.6 does not require EMA↑WMA now.
    prev_ema, prev_wma = 55.0, 50.0
    ema_now, wma_now = 56.0, 51.0
    assert prev_ema > prev_wma
    assert ema_now > wma_now
    assert wma_slope_up(prev_wma, wma_now) is True
