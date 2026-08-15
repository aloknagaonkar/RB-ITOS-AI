import pandas as pd

from red_bar_lab.services.historical_dri_quality_refinement import (
    evaluate_reset_override_quality,
)


def _candles(close_value: float):
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
            "close": close_value,
            "volume": 100,
        },
    ])


def test_moderate_market_action_can_pass():
    result = evaluate_reset_override_quality(
        _candles(104.0),
        moment="2026-08-14T10:01:00+05:30",
        direction="BULLISH",
        reset_classification="RESET_WINDOW_CONFIRMED",
        reset_rebreak_reason="RESET_MOMENTUM_REEXPANSION",
        break_level=103.96,
        candidate_score=88.89,
        opportunity_health=85.0,
        ema10_ok=True,
        ema30_ok=True,
        reversal_confirmed=True,
    )
    assert result["criteria_count"] >= 2
    assert result["market_action_count"] == 0
    assert result["moderate_market_action_passed"] is True
    assert result["market_action_tier"] == "MODERATE"
    assert result["passed"] is True


def test_moderate_market_action_requires_ema_alignment():
    result = evaluate_reset_override_quality(
        _candles(104.0),
        moment="2026-08-14T10:01:00+05:30",
        direction="BULLISH",
        reset_classification="RESET_WINDOW_CONFIRMED",
        reset_rebreak_reason="RESET_MOMENTUM_REEXPANSION",
        break_level=103.96,
        candidate_score=88.89,
        opportunity_health=85.0,
        ema10_ok=True,
        ema30_ok=False,
    )
    assert result["moderate_market_action_passed"] is False
    assert result["passed"] is False
