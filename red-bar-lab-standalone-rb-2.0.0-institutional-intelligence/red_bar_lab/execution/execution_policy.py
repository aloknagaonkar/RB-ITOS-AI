from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

RSI_STRATEGY_SOURCE = "RSI_EXTREME_REVERSAL_V1"
STANDARD_EXIT_MODE = "STANDARD_MULTI_FACTOR"
RSI_EXIT_MODE = "RSI_PREMIUM_PROTECTION_ONLY"

# All three active execution strategies now use the reversal-style premium
# protection policy. Entry detection and strategy authority remain unchanged.
REVERSAL_STYLE_STOP_LOSS_PCT = 7.0
REVERSAL_STYLE_TARGET_PCT = None


@dataclass(frozen=True)
class ExecutionPolicy:
    strategy_source: str
    stop_loss_pct: float
    target_pct: float | None
    exit_mode: str
    directional_conflicts_observational: bool


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
    """Resolve the unified reversal-style exit policy for every strategy.

    Red Bar, RSI Extreme Reversal, and Directional Regime Intelligence all use
    the same premium-protection-only exit authority:

    - 7% option-premium hard stop
    - no fixed target exit
    - five-minute dynamic-protection delay in ``PaperExitEngine``
    - breakeven, profit lock, and trailing protection after the delay
    - directional conflicts remain observational

    Persisted legacy STANDARD_MULTI_FACTOR values are intentionally normalized
    here so newly evaluated and previously persisted strategy rows behave
    consistently under the unified policy.
    """
    source = execution_strategy_source(signal)
    return ExecutionPolicy(
        source,
        REVERSAL_STYLE_STOP_LOSS_PCT,
        REVERSAL_STYLE_TARGET_PCT,
        RSI_EXIT_MODE,
        True,
    )
