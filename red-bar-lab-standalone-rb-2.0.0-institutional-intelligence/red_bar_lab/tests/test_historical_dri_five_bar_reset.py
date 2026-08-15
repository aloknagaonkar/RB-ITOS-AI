import pandas as pd
from types import SimpleNamespace

from red_bar_lab.services.historical_dri_refinements import (
    override_reset_rebreak_if_reexpanded,
    reset_reexpansion_diagnostics,
)


def test_five_bar_near_touch_reset_confirms():
    candles = pd.DataFrame([
        {"timestamp":"2026-08-14T04:28:00Z","open":100,"high":101,"low":99,"close":100},
        {"timestamp":"2026-08-14T04:29:00Z","open":100,"high":102,"low":99,"close":101},
        {"timestamp":"2026-08-14T04:30:00Z","open":101,"high":102,"low":100,"close":100.5},
        {"timestamp":"2026-08-14T04:31:00Z","open":100.5,"high":101,"low":99.9,"close":100.2},
        {"timestamp":"2026-08-14T04:32:00Z","open":100.2,"high":101,"low":100,"close":100.8},
        {"timestamp":"2026-08-14T04:33:00Z","open":100.8,"high":104,"low":100.7,"close":103.8},
    ])
    result = reset_reexpansion_diagnostics(
        candles,
        moment="2026-08-14T10:03:00+05:30",
        direction="BULLISH",
        momentum_ok=True,
    )
    assert result["reset_counter_candle_seen"] is True
    assert result["reset_near_touch_detected"] is True
    assert result["reset_classification"] == "RESET_WINDOW_CONFIRMED"


def test_override_remains_limited_to_specific_reason():
    original = SimpleNamespace(
        allowed=False,
        reason="RESET_REQUIRED",
    )
    candles = pd.DataFrame([
        {"timestamp":"2026-08-14T04:30:00Z","open":100,"high":101,"low":99,"close":100},
        {"timestamp":"2026-08-14T04:31:00Z","open":100,"high":103,"low":99,"close":102.8},
        {"timestamp":"2026-08-14T04:32:00Z","open":102.8,"high":106,"low":102,"close":105.5},
    ])
    updated = override_reset_rebreak_if_reexpanded(
        original,
        candles,
        moment="2026-08-14T10:02:00+05:30",
        direction="BULLISH",
        momentum_ok=True,
    )
    assert updated is original
    assert updated.allowed is False
