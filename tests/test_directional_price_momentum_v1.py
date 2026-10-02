from market_lab.directional_price_momentum_v1 import (
    EXPANSION_MULTIPLIER,
    _signal_direction,
    ema,
    realized_vol_15m,
)


def test_ema_direction_on_rising_series():
    values = [float(x) for x in range(1, 31)]
    fast = ema(values, 5)
    slow = ema(values, 15)
    assert fast[-1] > slow[-1]
    assert fast[-1] - fast[-4] > 0


def test_bullish_breakout_signal():
    direction, conditions, extension, ratio = _signal_direction(
        spot=121.0,
        prior_high=120.0,
        prior_low=100.0,
        ema_fast_value=115.0,
        ema_slow_value=112.0,
        ema_slope=2.0,
        momentum_5m=6.0,
        momentum_15m=12.0,
        current_1m_change=3.0,
        median_abs_change=2.0,
        prior_range=20.0,
    )
    assert direction == "BULLISH"
    assert all(conditions.values())
    assert extension == 1.0
    assert ratio == 1.5


def test_bearish_breakout_signal():
    direction, conditions, extension, ratio = _signal_direction(
        spot=99.0,
        prior_high=120.0,
        prior_low=100.0,
        ema_fast_value=105.0,
        ema_slow_value=108.0,
        ema_slope=-2.0,
        momentum_5m=-6.0,
        momentum_15m=-12.0,
        current_1m_change=-3.0,
        median_abs_change=2.0,
        prior_range=20.0,
    )
    assert direction == "BEARISH"
    assert all(conditions.values())
    assert extension == 1.0
    assert ratio == 1.5


def test_rejects_late_overextended_breakout():
    direction, _, _, _ = _signal_direction(
        spot=140.0,
        prior_high=120.0,
        prior_low=100.0,
        ema_fast_value=130.0,
        ema_slow_value=120.0,
        ema_slope=5.0,
        momentum_5m=25.0,
        momentum_15m=35.0,
        current_1m_change=10.0,
        median_abs_change=2.0,
        prior_range=20.0,
    )
    # max extension = 0.75 * 20 = 15; this is 20 points over breakout.
    assert direction is None


def test_rejects_breakout_without_expansion():
    direction, _, _, _ = _signal_direction(
        spot=121.0,
        prior_high=120.0,
        prior_low=100.0,
        ema_fast_value=115.0,
        ema_slow_value=112.0,
        ema_slope=2.0,
        momentum_5m=6.0,
        momentum_15m=12.0,
        current_1m_change=1.0,
        median_abs_change=2.0,
        prior_range=20.0,
    )
    assert EXPANSION_MULTIPLIER == 1.25
    assert direction is None


def test_rejects_bullish_breakout_against_trend():
    direction, _, _, _ = _signal_direction(
        spot=121.0,
        prior_high=120.0,
        prior_low=100.0,
        ema_fast_value=110.0,
        ema_slow_value=112.0,
        ema_slope=-1.0,
        momentum_5m=6.0,
        momentum_15m=12.0,
        current_1m_change=3.0,
        median_abs_change=2.0,
        prior_range=20.0,
    )
    assert direction is None


def test_realized_vol_uses_only_backward_series():
    spots = [100.0 + i for i in range(16)]
    assert realized_vol_15m(spots, 15) == 0.0
