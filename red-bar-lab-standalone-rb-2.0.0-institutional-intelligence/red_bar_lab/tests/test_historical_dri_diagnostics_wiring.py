from dataclasses import fields
import pandas as pd

from red_bar_lab.services.historical_decision_replay import DecisionReplayRow
from red_bar_lab.services.historical_dri_diagnostics import (
    build_reversal_diagnostics,
)


class Decision:
    state = type("State", (), {"value": "PENDING_BULLISH_REVERSAL"})()
    reason = "PENDING_REVERSAL"
    provisional = False
    confirmed = False


def test_decision_replay_row_contains_diagnostic_fields():
    names = {item.name for item in fields(DecisionReplayRow)}
    assert {
        "reversal_state",
        "reversal_reason",
        "reversal_ema10_value",
        "reversal_ema10_slope",
        "reversal_ema30_value",
        "reversal_ema30_slope",
        "reversal_two_directional_closes",
        "reversal_active_invalidation",
        "reversal_invalidation_broken",
        "reset_rebreak_reason",
        "trailing_activated",
        "trailing_exit_price",
    }.issubset(names)


def test_diagnostics_compute_ema_and_two_closes():
    candles = pd.DataFrame([
        {"timestamp": "2026-08-14T04:35:00Z", "open": 100, "close": 101},
        {"timestamp": "2026-08-14T04:36:00Z", "open": 101, "close": 103},
    ])
    result = build_reversal_diagnostics(
        candles,
        moment="2026-08-14T10:06:00+05:30",
        direction="BULLISH",
        reversal_decision=Decision(),
        active_invalidation=102,
        reset_rebreak_reason="RESET_REQUIRED",
    )
    assert result["reversal_two_directional_closes"] is True
    assert result["reversal_ema10_ok"] is True
    assert result["reversal_invalidation_broken"] is True
