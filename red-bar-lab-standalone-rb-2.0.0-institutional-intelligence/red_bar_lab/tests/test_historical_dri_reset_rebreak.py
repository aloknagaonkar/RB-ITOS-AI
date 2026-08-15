import pandas as pd

from red_bar_lab.services.historical_dri_reentry_policy import (
    ResetAndRebreakGate,
)


def _frame(rows):
    return pd.DataFrame(rows)


def test_first_entry_is_allowed():
    gate = ResetAndRebreakGate()
    result = gate.evaluate(
        "BULLISH",
        "2026-08-14T10:00:00+05:30",
        _frame([]),
        trigger_level=24300,
        invalidation_level=24290,
    )
    assert result.allowed
    assert result.reason == "FIRST_DIRECTIONAL_ENTRY"


def test_same_direction_requires_reset_and_fresh_rebreak():
    gate = ResetAndRebreakGate()
    gate.record_taken(
        "BULLISH",
        "2026-08-14T10:00:00+05:30",
        trigger_level=24300,
        invalidation_level=24290,
    )
    candles = _frame(
        [
            {
                "timestamp": "2026-08-14T04:35:00Z",
                "open": 24305,
                "high": 24308,
                "low": 24296,
                "close": 24299,
            },
            {
                "timestamp": "2026-08-14T04:36:00Z",
                "open": 24299,
                "high": 24302,
                "low": 24292,
                "close": 24295,
            },
            {
                "timestamp": "2026-08-14T04:37:00Z",
                "open": 24295,
                "high": 24320,
                "low": 24294,
                "close": 24318,
            },
        ]
    )
    result = gate.evaluate(
        "BULLISH",
        "2026-08-14T10:07:00+05:30",
        candles,
        trigger_level=24323,
        invalidation_level=24300,
    )
    assert result.allowed
    assert result.reset_seen
    assert result.fresh_structure
    assert result.momentum_reexpanded


def test_no_reset_blocks_late_continuation():
    gate = ResetAndRebreakGate()
    gate.record_taken(
        "BEARISH",
        "2026-08-14T10:00:00+05:30",
        trigger_level=24300,
        invalidation_level=24315,
    )
    candles = _frame(
        [
            {
                "timestamp": "2026-08-14T04:35:00Z",
                "open": 24295,
                "high": 24298,
                "low": 24280,
                "close": 24282,
            },
            {
                "timestamp": "2026-08-14T04:36:00Z",
                "open": 24282,
                "high": 24284,
                "low": 24265,
                "close": 24267,
            },
            {
                "timestamp": "2026-08-14T04:37:00Z",
                "open": 24267,
                "high": 24269,
                "low": 24250,
                "close": 24252,
            },
        ]
    )
    result = gate.evaluate(
        "BEARISH",
        "2026-08-14T10:07:00+05:30",
        candles,
        trigger_level=24248,
        invalidation_level=24270,
    )
    assert not result.allowed
    assert result.reason == "NO_RESET_BEFORE_REBREAK"
