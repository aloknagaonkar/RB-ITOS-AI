from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

RSI_STRATEGY_SOURCE = "RSI_EXTREME_REVERSAL_V1"
STANDARD_EXIT_MODE = "STANDARD_MULTI_FACTOR"
RSI_EXIT_MODE = "RSI_PREMIUM_PROTECTION_ONLY"

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
    if source == RSI_STRATEGY_SOURCE or signal_id.startswith("RSI-"):
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
    source = execution_strategy_source(signal)
    if source == RSI_STRATEGY_SOURCE:
        return ExecutionPolicy(source, 7.0, None, RSI_EXIT_MODE, True)
    return ExecutionPolicy(
        source,
        float(default_stop_loss_pct),
        float(default_target_pct) if default_target_pct is not None else None,
        STANDARD_EXIT_MODE,
        False,
    )
