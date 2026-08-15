import pandas as pd
from types import SimpleNamespace

from red_bar_lab.services.historical_dri_refinements import (
    override_reset_rebreak_if_reexpanded,
    reset_momentum_reexpansion,
    strong_expansion_candle,
)


def test_strong_bullish_expansion_candle():
    frame = pd.DataFrame([
        {"open":100,"high":102,"low":99,"close":101},
        {"open":101,"high":106,"low":100,"close":105},
    ])
    assert strong_expansion_candle(frame, "BULLISH")


def test_reset_then_bearish_reexpansion():
    candles = pd.DataFrame([
        {"timestamp":"2026-08-14T04:30:00Z","open":100,"high":101,"low":98,"close":99},
        {"timestamp":"2026-08-14T04:31:00Z","open":99,"high":102,"low":99,"close":101},
        {"timestamp":"2026-08-14T04:32:00Z","open":101,"high":101,"low":96,"close":97},
    ])
    assert reset_momentum_reexpansion(
        candles,
        moment="2026-08-14T10:02:00+05:30",
        direction="BEARISH",
        momentum_ok=True,
    )


def test_only_specific_reset_reason_is_overridden():
    result = SimpleNamespace(
        allowed=False,
        reason="NO_FRESH_STRUCTURE_REBREAK",
    )
    candles = pd.DataFrame([
        {"timestamp":"2026-08-14T04:30:00Z","open":100,"high":101,"low":98,"close":99},
        {"timestamp":"2026-08-14T04:31:00Z","open":99,"high":102,"low":99,"close":101},
        {"timestamp":"2026-08-14T04:32:00Z","open":101,"high":101,"low":96,"close":97},
    ])
    updated = override_reset_rebreak_if_reexpanded(
        result,
        candles,
        moment="2026-08-14T10:02:00+05:30",
        direction="BEARISH",
        momentum_ok=True,
    )
    assert updated.allowed is True
    assert updated.reason == "RESET_MOMENTUM_REEXPANSION"
