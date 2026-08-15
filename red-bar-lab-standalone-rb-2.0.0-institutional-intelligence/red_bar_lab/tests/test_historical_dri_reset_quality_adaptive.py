import pandas as pd

from red_bar_lab.services.historical_dri_quality_refinement import (
    derive_adaptive_initial_stop_pct,
    evaluate_reset_override_quality,
)


def test_reset_quality_requires_two_criteria():
    candles = pd.DataFrame([
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
            "close": 105,
            "volume": 200,
        },
    ])
    result = evaluate_reset_override_quality(
        candles,
        moment="2026-08-14T10:01:00+05:30",
        direction="BULLISH",
        reset_classification="RESET_WINDOW_CONFIRMED",
        break_level=102,
        candidate_score=90,
        opportunity_health=70,
    )
    assert result["passed"] is True
    assert result["criteria_count"] >= 2


def test_non_reset_window_classification_is_not_blocked():
    result = evaluate_reset_override_quality(
        pd.DataFrame(),
        moment="2026-08-14T10:01:00+05:30",
        direction="BULLISH",
        reset_classification="SHALLOW_RESET_EXPANSION",
        break_level=None,
        candidate_score=None,
        opportunity_health=None,
    )
    assert result["applicable"] is False
    assert result["passed"] is True


def test_adaptive_stop_is_bounded():
    candles = pd.DataFrame([
        {
            "timestamp": f"2026-08-14T04:{30+i:02d}:00Z",
            "open": 100 + i,
            "high": 104 + i,
            "low": 97 + i,
            "close": 101 + i,
        }
        for i in range(6)
    ])
    stop = derive_adaptive_initial_stop_pct(
        candles,
        entry_moment="2026-08-14T10:05:00+05:30",
        entry_price=100,
    )
    assert 5.0 <= stop <= 12.0
