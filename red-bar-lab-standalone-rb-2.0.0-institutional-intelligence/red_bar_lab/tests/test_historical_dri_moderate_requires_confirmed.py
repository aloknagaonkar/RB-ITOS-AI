import pandas as pd

from red_bar_lab.services.historical_dri_quality_refinement import (
    evaluate_reset_override_quality,
)


def _candles():
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
            "close": 104,
            "volume": 100,
        },
    ])


def test_moderate_tier_requires_confirmed_reversal():
    result = evaluate_reset_override_quality(
        _candles(),
        moment="2026-08-14T10:01:00+05:30",
        direction="BULLISH",
        reset_classification="RESET_WINDOW_CONFIRMED",
        reset_rebreak_reason="RESET_MOMENTUM_REEXPANSION",
        break_level=103.96,
        candidate_score=88.89,
        opportunity_health=85.0,
        ema10_ok=True,
        ema30_ok=True,
        reversal_confirmed=False,
    )
    assert result["market_action_count"] == 0
    assert result["moderate_market_action_passed"] is False
    assert result["passed"] is False


def test_moderate_tier_allows_confirmed_reversal():
    result = evaluate_reset_override_quality(
        _candles(),
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
    assert result["market_action_count"] == 0
    assert result["moderate_market_action_passed"] is True
    assert result["market_action_tier"] == "MODERATE"
    assert result["passed"] is True


def test_strong_tier_does_not_require_confirmed_reversal():
    result = evaluate_reset_override_quality(
        _candles(),
        moment="2026-08-14T10:01:00+05:30",
        direction="BULLISH",
        reset_classification="RESET_WINDOW_CONFIRMED",
        reset_rebreak_reason="RESET_MOMENTUM_REEXPANSION",
        break_level=102.0,
        candidate_score=70.0,
        opportunity_health=85.0,
        ema10_ok=False,
        ema30_ok=False,
        reversal_confirmed=False,
    )
    assert result["market_action_count"] >= 1
    assert result["market_action_tier"] == "STRONG"
    assert result["passed"] is True
