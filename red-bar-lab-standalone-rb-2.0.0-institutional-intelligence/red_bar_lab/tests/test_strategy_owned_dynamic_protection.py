from __future__ import annotations

from datetime import datetime, timedelta

from red_bar_lab.execution.execution_policy import (
    RSI_DYNAMIC_PROTECTION_DELAY_SECONDS,
    RSI_EXIT_MODE,
    resolve_execution_policy,
)
from red_bar_lab.execution.exit_engine import PaperExitEngine


def _recent_position(strategy_source: str, *, rsi_signal_id: str | None = None):
    row = {
        "entry_price": 100.0,
        "current_price": 108.0,
        "mfe_points": 8.0,
        "initial_stop_price": 93.0,
        "stop_price": 93.0,
        "entry_timestamp": (datetime.now() - timedelta(seconds=30)).isoformat(),
        "execution_strategy_source": strategy_source,
        "signal_id": "RB-TEST-1",
    }
    if rsi_signal_id is not None:
        row["rsi_signal_id"] = rsi_signal_id
    return row


def test_red_bar_arms_profit_lock_without_five_minute_delay():
    result = PaperExitEngine().evaluate(
        position=_recent_position("RED_BAR"),
        signal={"execution_strategy_source": "RED_BAR", "signal_id": "RB-TEST-1"},
        exit_mode=RSI_EXIT_MODE,
    )

    assert result.breakeven_armed is True
    assert result.profit_lock_active is True
    assert result.profit_lock_price == 102.0
    assert result.effective_stop == 102.0
    assert not any("DYNAMIC_PROTECTION_DELAY_ACTIVE" in reason for reason in result.reasons)


def test_directional_regime_arms_profit_lock_without_delay():
    result = PaperExitEngine().evaluate(
        position=_recent_position("DIRECTIONAL_REGIME"),
        signal={
            "execution_strategy_source": "DIRECTIONAL_REGIME",
            "signal_id": "DRI-TEST-1",
        },
        exit_mode=RSI_EXIT_MODE,
    )

    assert result.profit_lock_active is True
    assert result.effective_stop == 102.0


def test_rsi_retains_five_minute_delay():
    position = _recent_position("RSI_EXTREME_REVERSAL_V1")
    position["signal_id"] = "RSI-TEST-1"
    result = PaperExitEngine().evaluate(
        position=position,
        signal={
            "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
            "signal_id": "RSI-TEST-1",
        },
        exit_mode=RSI_EXIT_MODE,
    )

    assert result.breakeven_armed is False
    assert result.profit_lock_active is False
    assert result.effective_stop == 93.0
    assert f"RSI_DYNAMIC_PROTECTION_DELAY_ACTIVE={int(RSI_DYNAMIC_PROTECTION_DELAY_SECONDS)}s" in result.reasons


def test_explicit_reference_level_is_not_reclassified_by_rsi_support_metadata():
    result = PaperExitEngine().evaluate(
        position=_recent_position(
            "REFERENCE_LEVEL",
            rsi_signal_id="RSI-SUPPORT-ONLY",
        ),
        signal={
            "execution_strategy_source": "REFERENCE_LEVEL",
            "signal_id": "RB-TEST-1",
            "rsi_signal_id": "RSI-SUPPORT-ONLY",
        },
        exit_mode=RSI_EXIT_MODE,
    )

    assert result.profit_lock_active is True
    assert result.effective_stop == 102.0


def test_execution_policy_exposes_strategy_owned_delay():
    red_bar = resolve_execution_policy(
        {"execution_strategy_source": "RED_BAR", "signal_id": "RB-1"}
    )
    dri = resolve_execution_policy(
        {"execution_strategy_source": "DIRECTIONAL_REGIME", "signal_id": "DRI-1"}
    )
    rsi = resolve_execution_policy(
        {
            "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
            "signal_id": "RSI-1",
        }
    )

    assert red_bar.dynamic_protection_delay_seconds == 0.0
    assert dri.dynamic_protection_delay_seconds == 0.0
    assert rsi.dynamic_protection_delay_seconds == 300.0
