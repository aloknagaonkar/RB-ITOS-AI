from market_lab.pcr_regime_research_v1 import (
    ROUND_TRIP_COST_PCT_POINTS,
    assign_regimes,
    derive_cuts,
    momentum_alignment,
    profit_factor,
    quantile_linear,
    realized_trade,
    trend_regime,
    volatility_regime,
)


def test_quantile_linear_is_deterministic():
    assert quantile_linear([1, 2, 3, 4], 1 / 3) == 2.0
    assert quantile_linear([1, 2, 3, 4], 2 / 3) == 3.0


def test_trend_and_alignment():
    assert trend_regime(2.0, 3.0) == "RANGE"
    assert trend_regime(4.0, 3.0) == "UP"
    assert trend_regime(-4.0, 3.0) == "DOWN"

    assert momentum_alignment("BEARISH", "DOWN") == "ALIGNED"
    assert momentum_alignment("BEARISH", "UP") == "AGAINST"
    assert momentum_alignment("BULLISH", "UP") == "ALIGNED"
    assert momentum_alignment("BULLISH", "DOWN") == "AGAINST"
    assert momentum_alignment("BULLISH", "RANGE") == "NEUTRAL"


def test_volatility_regime_boundaries():
    assert volatility_regime(1.0, 1.0, 3.0) == "LOW"
    assert volatility_regime(2.0, 1.0, 3.0) == "NORMAL"
    assert volatility_regime(3.0, 1.0, 3.0) == "HIGH"


def test_profit_factor():
    assert profit_factor([2.0, 1.0, -1.0]) == 3.0
    assert profit_factor([1.0, 2.0]) is None


def test_realized_policy_target_stop_and_time_exit():
    target = {
        "target_stop": {"TARGET_5_STOP_10": "TARGET_FIRST"},
        "returns_pct": {"15m": -3.0},
    }
    stop = {
        "target_stop": {"TARGET_5_STOP_10": "STOP_FIRST"},
        "returns_pct": {"15m": 8.0},
    }
    ambiguous = {
        "target_stop": {"TARGET_5_STOP_10": "AMBIGUOUS_SAME_BAR"},
        "returns_pct": {"15m": 8.0},
    }
    timed = {
        "target_stop": {"TARGET_5_STOP_10": "NEITHER_WITHIN_15M"},
        "returns_pct": {"15m": 2.25},
    }

    assert realized_trade(target) == (
        "TARGET",
        5.0,
        5.0 - ROUND_TRIP_COST_PCT_POINTS,
    )
    assert realized_trade(stop) == (
        "STOP",
        -10.0,
        -10.0 - ROUND_TRIP_COST_PCT_POINTS,
    )
    assert realized_trade(ambiguous) == (
        "AMBIGUOUS_ASSUMED_STOP",
        -10.0,
        -10.0 - ROUND_TRIP_COST_PCT_POINTS,
    )
    assert realized_trade(timed) == (
        "TIME_EXIT_15M",
        2.25,
        2.25 - ROUND_TRIP_COST_PCT_POINTS,
    )


def test_derive_cuts_does_not_need_outcomes_or_returns():
    rows = [
        {
            "spot_momentum_5m": x,
            "spot_momentum_15m": 2 * x,
            "spot_realized_vol_15m": abs(x) + 1,
        }
        for x in (-3.0, -2.0, -1.0, 1.0, 2.0, 3.0)
    ]
    cuts = derive_cuts(rows)
    assert set(cuts) == {
        "trend_abs_spot_momentum_15m_q33",
        "spot_momentum_5m_abs_q33",
        "volatility_15m_q33",
        "volatility_15m_q67",
    }


def test_assign_regimes_uses_frozen_cuts():
    row = {
        "direction": "BEARISH",
        "confirmation_timestamp": "2026-07-15T10:30:00+05:30",
        "spot_momentum_5m": -8.0,
        "spot_momentum_15m": -20.0,
        "spot_realized_vol_15m": 4.0,
        "moving_pcr_change_5m": -0.05,
    }
    cuts = {
        "trend_abs_spot_momentum_15m_q33": 5.0,
        "spot_momentum_5m_abs_q33": 2.0,
        "volatility_15m_q33": 1.0,
        "volatility_15m_q67": 3.0,
    }
    out = assign_regimes(row, cuts)
    assert out["trend_regime"] == "DOWN"
    assert out["volatility_regime"] == "HIGH"
    assert out["momentum_alignment"] == "ALIGNED"
    assert out["time_regime"] == "EARLY"
    assert out["pcr_spot_alignment"] == "ALIGNED"
