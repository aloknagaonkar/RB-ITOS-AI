import pandas as pd

from red_bar_lab.services.historical_dri_quality_refinement import (
    evaluate_reset_override_quality,
)


def _candles(body_close=105.0):
    return pd.DataFrame([
        {
            "timestamp": "2026-08-14T04:30:00Z",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 100,
        },
        {
            "timestamp": "2026-08-14T04:31:00Z",
            "open": 100,
            "high": 106,
            "low": 100,
            "close": body_close,
            "volume": 100,
        },
    ])


def test_score_and_health_alone_cannot_pass():
    result = evaluate_reset_override_quality(
        _candles(body_close=100.5),
        moment="2026-08-14T10:01:00+05:30",
        direction="BULLISH",
        reset_classification="RESET_WINDOW_CONFIRMED",
        reset_rebreak_reason="RESET_MOMENTUM_REEXPANSION",
        break_level=106,
        candidate_score=95,
        opportunity_health=95,
    )
    assert result["criteria_count"] >= 2
    assert result["market_action_count"] == 0
    assert result["passed"] is False


def test_total_two_plus_market_action_passes():
    result = evaluate_reset_override_quality(
        _candles(),
        moment="2026-08-14T10:01:00+05:30",
        direction="BULLISH",
        reset_classification="RESET_WINDOW_CONFIRMED",
        reset_rebreak_reason="RESET_MOMENTUM_REEXPANSION",
        break_level=102,
        candidate_score=90,
        opportunity_health=70,
    )
    assert result["criteria_count"] >= 2
    assert result["market_action_count"] >= 1
    assert result["passed"] is True
