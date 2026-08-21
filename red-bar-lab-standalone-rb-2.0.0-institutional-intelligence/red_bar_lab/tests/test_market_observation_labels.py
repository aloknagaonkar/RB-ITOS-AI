from datetime import datetime, timezone

from red_bar_lab.ui.market_at_a_glance import build_market_at_a_glance

NOW = datetime(2026, 8, 21, 6, 5, tzinfo=timezone.utc)
STAMP = "2026-08-21T06:04:00+00:00"


def _summary(ce, pe, ce_slope, pe_slope):
    return {
        "ce_score": ce,
        "pe_score": pe,
        "ce_score_slope": ce_slope,
        "pe_score_slope": pe_slope,
        "eligible_ce": 9,
        "eligible_pe": 9,
        "rejected": 0,
        "observed_at": STAMP,
    }


def _futures():
    return {
        "positioning_state": "NEUTRAL",
        "strength": "WEAK",
        "observed_at": STAMP,
        "latest_timestamp": STAMP,
    }


def _underlying():
    return {
        "direction": "NEUTRAL",
        "state": "SIDEWAYS_VOLATILE",
        "acceptance_state": "NO_BREAK",
        "momentum": "VOLATILE",
        "rsi_view": "BULLISH_RECOVERY",
        "rsi": 35.9,
        "rsi_slope": 6.6,
        "observed_at": STAMP,
    }


def test_sub_threshold_pe_dominance_is_weak_bearish_lean_not_confirmation():
    view = build_market_at_a_glance(
        _summary(15.0, 45.0, 0.0, -0.6),
        _futures(),
        _underlying(),
        now=NOW,
    )
    assert view["option_direction"] == "WAIT"
    assert view["option_pressure_label"] == "WEAK BEARISH LEAN"
    assert view["option_pressure_trend"] == "FADING"
    assert view["trade_bias"] == "WAIT"


def test_rsi_recovery_is_early_alert_without_owning_direction():
    view = build_market_at_a_glance(
        _summary(15.0, 45.0, 0.0, -0.6),
        _futures(),
        _underlying(),
        now=NOW,
    )
    assert view["early_alert"] == "BULLISH RSI RECOVERY"
    assert view["observed_direction"] == "NEUTRAL"
    assert view["direction_state"] == "NEUTRAL"
    assert view["trade_eligibility"] == "BLOCKED"
