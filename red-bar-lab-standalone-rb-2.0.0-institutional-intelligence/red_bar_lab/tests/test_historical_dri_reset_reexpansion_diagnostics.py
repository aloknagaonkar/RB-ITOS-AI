import pandas as pd

from red_bar_lab.services.historical_dri_refinements import (
    reset_reexpansion_diagnostics,
)


def test_reset_reexpansion_diagnostics_bearish():
    candles = pd.DataFrame([
        {
            "timestamp": "2026-08-14T04:30:00Z",
            "open": 100,
            "high": 101,
            "low": 98,
            "close": 99,
        },
        {
            "timestamp": "2026-08-14T04:31:00Z",
            "open": 99,
            "high": 102,
            "low": 99,
            "close": 101,
        },
        {
            "timestamp": "2026-08-14T04:32:00Z",
            "open": 101,
            "high": 101,
            "low": 96,
            "close": 97,
        },
    ])
    result = reset_reexpansion_diagnostics(
        candles,
        moment="2026-08-14T10:02:00+05:30",
        direction="BEARISH",
        momentum_ok=True,
    )
    assert result["reset_seen"] is True
    assert result["ema10_touch_detected"] is True
    assert result["reexpansion_detected"] is True
    assert result["reexpansion_break_level"] == 99.0


def test_reset_reexpansion_diagnostics_reports_momentum_failure():
    candles = pd.DataFrame([
        {
            "timestamp": "2026-08-14T04:30:00Z",
            "open": 100,
            "high": 101,
            "low": 98,
            "close": 99,
        },
        {
            "timestamp": "2026-08-14T04:31:00Z",
            "open": 99,
            "high": 102,
            "low": 99,
            "close": 101,
        },
        {
            "timestamp": "2026-08-14T04:32:00Z",
            "open": 101,
            "high": 101,
            "low": 96,
            "close": 97,
        },
    ])
    result = reset_reexpansion_diagnostics(
        candles,
        moment="2026-08-14T10:02:00+05:30",
        direction="BEARISH",
        momentum_ok=False,
    )
    assert result["reset_seen"] is True
    assert result["reexpansion_detected"] is False
    assert result["momentum_ok"] is False
