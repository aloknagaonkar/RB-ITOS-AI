from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

RSI_STRATEGY_SOURCE = "RSI_EXTREME_REVERSAL_V1"
STANDARD_EXIT_MODE = "STANDARD_MULTI_FACTOR"
RSI_EXIT_MODE = "RSI_PREMIUM_PROTECTION_ONLY"

# All three active execution strategies use the same premium-protection
# thresholds. Protection timing remains strategy-owned so RSI-specific entry
# noise handling is not imposed on Red Bar or Directional Regime trades.
REVERSAL_STYLE_STOP_LOSS_PCT = 7.0
REVERSAL_STYLE_TARGET_PCT = None
IMMEDIATE_DYNAMIC_PROTECTION_DELAY_SECONDS = 0.0
RSI_DYNAMIC_PROTECTION_DELAY_SECONDS = 300.0


@dataclass(frozen=True)
class ExecutionPolicy:
    strategy_source: str
    stop_loss_pct: float
    target_pct: float | None
    exit_mode: str
    directional_conflicts_observational: bool
    dynamic_protection_delay_seconds: float = (
        IMMEDIATE_DYNAMIC_PROTECTION_DELAY_SECONDS
    )


def execution_strategy_source(signal: Mapping[str, object] | None) -> str:
    row = signal or {}
    source = str(
        row.get("execution_strategy_source")
        or row.get("signal_source")
        or row.get("source")
        or ""
    ).upper().strip()
    signal_id = str(row.get("signal_id") or "").upper().strip()
    if (
        source == RSI_STRATEGY_SOURCE
        or signal_id.startswith("RSI7-")
        or signal_id.startswith("RSI-")
    ):
        return RSI_STRATEGY_SOURCE
    return source or "REFERENCE_LEVEL"


def is_rsi_primary(signal: Mapping[str, object] | None) -> bool:
    return execution_strategy_source(signal) == RSI_STRATEGY_SOURCE


def resolve_execution_policy(
    signal: Mapping[str, object] | None,
    *,
    default_stop_loss_pct: float = 15.0,
    default_target_pct: float | None = 25.0,
) -> ExecutionPolicy:
    """Resolve premium-protection thresholds and strategy-owned timing.

    Red Bar, RSI Extreme Reversal, and Directional Regime Intelligence retain
    the same protection thresholds:

    - 7% option-premium hard stop
    - no fixed target exit
    - breakeven, profit lock, and trailing protection
    - directional conflicts remain observational

    Protection timing differs by primary strategy:

    - RSI Extreme Reversal: five-minute dynamic-protection delay
    - Red Bar, Directional Regime, Reference Level, and other non-RSI sources:
      immediate dynamic protection

    Persisted legacy ``STANDARD_MULTI_FACTOR`` values remain normalized to the
    premium-protection-only exit authority. The default stop/target arguments
    are retained for call compatibility and are intentionally not authoritative.
    """
    source = execution_strategy_source(signal)
    delay_seconds = (
        RSI_DYNAMIC_PROTECTION_DELAY_SECONDS
        if source == RSI_STRATEGY_SOURCE
        else IMMEDIATE_DYNAMIC_PROTECTION_DELAY_SECONDS
    )
    return ExecutionPolicy(
        source,
        REVERSAL_STYLE_STOP_LOSS_PCT,
        REVERSAL_STYLE_TARGET_PCT,
        RSI_EXIT_MODE,
        True,
        delay_seconds,
    )
