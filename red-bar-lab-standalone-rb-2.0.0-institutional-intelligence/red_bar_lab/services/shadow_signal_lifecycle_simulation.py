from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

import pandas as pd


def _timestamp(row: Mapping[str, object]) -> pd.Timestamp:
    return pd.Timestamp(row.get("timestamp") or row.get("candle_timestamp"))


def _accuracy(rows: list[Mapping[str, object]], field: str) -> float | None:
    values = [bool(row[field]) for row in rows if row.get(field) is not None]
    if not values:
        return None
    return round(sum(values) / len(values) * 100.0, 2)


def _mean(rows: list[Mapping[str, object]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _mfe_mae_ratio(rows: list[Mapping[str, object]]) -> float | None:
    mfe = _mean(rows, "maximum_favorable_excursion")
    mae = _mean(rows, "maximum_adverse_excursion")
    if mfe is None or mae in {None, 0}:
        return None
    return round(mfe / mae, 3)


def _max_failure_cluster(rows: list[Mapping[str, object]]) -> int:
    largest = 0
    current = 0
    for row in sorted(rows, key=_timestamp):
        if row.get("direction_correct_30m") is False:
            current += 1
            largest = max(largest, current)
        elif row.get("direction_correct_30m") is not None:
            current = 0
    return largest


def _duplicate_share(rows: list[Mapping[str, object]], window_minutes: int = 30) -> float | None:
    ordered = sorted(rows, key=_timestamp)
    if not ordered:
        return None
    duplicates = 0
    for previous, current in zip(ordered, ordered[1:]):
        delta = (_timestamp(current) - _timestamp(previous)).total_seconds() / 60.0
        if (
            str(previous.get("direction")) == str(current.get("direction"))
            and delta <= window_minutes
        ):
            duplicates += 1
    return round(duplicates / len(ordered) * 100.0, 2)


@dataclass(frozen=True)
class SimulationConfig:
    name: str
    cooldown_minutes: int = 0
    failure_lockout_minutes: int = 0
    one_signal_per_move: bool = False
    require_breakout_hold: bool = False
    require_retest_confirmation: bool = False


def _same_move(previous: Mapping[str, object], current: Mapping[str, object]) -> bool:
    same_direction = str(previous.get("direction")) == str(current.get("direction"))
    same_regime = str(previous.get("regime")) == str(current.get("regime"))
    if not same_direction:
        return False
    if not same_regime:
        return False

    direction = str(current.get("direction"))
    if direction == "BULLISH":
        reset = bool(current.get("breakdown")) or float(current.get("ema_spread_atr") or 0.0) <= 0
    else:
        reset = bool(current.get("breakout")) or float(current.get("ema_spread_atr") or 0.0) >= 0
    return not reset


def _breakout_hold_passes(row: Mapping[str, object]) -> bool:
    direction = str(row.get("direction"))
    evidence = row.get("evidence") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    tags = {str(item) for item in evidence}

    if direction == "BULLISH":
        return (
            bool(row.get("breakout"))
            and (
                "BREAKOUT_HOLD_CONFIRMED" in tags
                or float(row.get("directional_displacement_atr") or 0.0) > 0
            )
        )
    if direction == "BEARISH":
        return (
            bool(row.get("breakdown"))
            and (
                "BREAKDOWN_HOLD_CONFIRMED" in tags
                or float(row.get("directional_displacement_atr") or 0.0) > 0
            )
        )
    return False


def _retest_confirmation_passes(row: Mapping[str, object]) -> bool:
    evidence = row.get("evidence") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    tags = {str(item) for item in evidence}
    return (
        "PULLBACK_RETEST_CONFIRMED" in tags
        or "EMA_RETEST_CONTINUATION" in tags
        or bool(row.get("pullback_retest_confirmed"))
    )


def apply_simulation(
    rows: Iterable[Mapping[str, object]],
    config: SimulationConfig,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    ordered = sorted((dict(row) for row in rows), key=_timestamp)
    accepted: list[dict[str, object]] = []
    suppressed: list[dict[str, object]] = []

    last_accepted_by_direction: dict[str, dict[str, object]] = {}
    last_failed_by_direction: dict[str, pd.Timestamp] = {}

    for row in ordered:
        direction = str(row.get("direction") or "")
        ts = _timestamp(row)
        reason = None

        previous = last_accepted_by_direction.get(direction)
        if previous and config.cooldown_minutes > 0:
            elapsed = (ts - _timestamp(previous)).total_seconds() / 60.0
            if elapsed <= config.cooldown_minutes:
                reason = "COOLDOWN_SUPPRESSED"

        failed_at = last_failed_by_direction.get(direction)
        if reason is None and failed_at is not None and config.failure_lockout_minutes > 0:
            elapsed = (ts - failed_at).total_seconds() / 60.0
            if elapsed <= config.failure_lockout_minutes:
                reason = "FAILURE_LOCKOUT_SUPPRESSED"

        if reason is None and config.one_signal_per_move and previous:
            if _same_move(previous, row):
                reason = "SAME_MOVE_SUPPRESSED"

        if reason is None and config.require_breakout_hold:
            if not _breakout_hold_passes(row):
                reason = "BREAKOUT_HOLD_NOT_CONFIRMED"

        if reason is None and config.require_retest_confirmation:
            if not _retest_confirmation_passes(row):
                reason = "RETEST_NOT_CONFIRMED"

        if reason:
            suppressed.append({
                **row,
                "simulation": config.name,
                "suppression_reason": reason,
                "execution_allowed": False,
            })
            continue

        accepted_row = {
            **row,
            "simulation": config.name,
            "suppression_reason": None,
            "execution_allowed": False,
        }
        accepted.append(accepted_row)
        last_accepted_by_direction[direction] = accepted_row

        if row.get("direction_correct_30m") is False:
            last_failed_by_direction[direction] = ts

    return accepted, suppressed


def summarize_simulation(
    config: SimulationConfig,
    accepted: list[Mapping[str, object]],
    suppressed: list[Mapping[str, object]],
) -> dict[str, object]:
    resolved = [row for row in accepted if row.get("direction_correct_30m") is not None]
    return {
        "simulation": config.name,
        "accepted_signals": len(accepted),
        "suppressed_signals": len(suppressed),
        "resolved_30m": len(resolved),
        "accuracy_5m": _accuracy(accepted, "direction_correct_5m"),
        "accuracy_15m": _accuracy(accepted, "direction_correct_15m"),
        "accuracy_30m": _accuracy(accepted, "direction_correct_30m"),
        "false_rate_30m": (
            round(100.0 - _accuracy(accepted, "direction_correct_30m"), 2)
            if _accuracy(accepted, "direction_correct_30m") is not None
            else None
        ),
        "average_mfe": _mean(resolved, "maximum_favorable_excursion"),
        "average_mae": _mean(resolved, "maximum_adverse_excursion"),
        "mfe_mae_ratio": _mfe_mae_ratio(resolved),
        "max_consecutive_failures": _max_failure_cluster(resolved),
        "duplicate_share_pct": _duplicate_share(accepted),
        "execution_allowed": False,
    }


def _group_by(rows: list[Mapping[str, object]], field: str) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(field) or "UNKNOWN"), []).append(row)
    output = []
    for value, group in sorted(grouped.items()):
        output.append({
            field: value,
            "samples": len(group),
            "resolved_30m": sum(row.get("direction_correct_30m") is not None for row in group),
            "accuracy_30m": _accuracy(list(group), "direction_correct_30m"),
            "mfe_mae_ratio": _mfe_mae_ratio(list(group)),
            "execution_allowed": False,
        })
    return output


class ShadowSignalLifecycleSimulationService:
    @staticmethod
    def default_configs() -> list[SimulationConfig]:
        return [
            SimulationConfig(name="BASELINE"),
            SimulationConfig(name="COOLDOWN_15M", cooldown_minutes=15),
            SimulationConfig(name="COOLDOWN_30M", cooldown_minutes=30),
            SimulationConfig(name="COOLDOWN_45M", cooldown_minutes=45),
            SimulationConfig(name="COOLDOWN_60M", cooldown_minutes=60),
            SimulationConfig(name="ONE_SIGNAL_PER_MOVE", one_signal_per_move=True),
            SimulationConfig(name="FAILURE_LOCKOUT_30M", failure_lockout_minutes=30),
            SimulationConfig(name="FAILURE_LOCKOUT_60M", failure_lockout_minutes=60),
            SimulationConfig(
                name="ONE_MOVE_COOLDOWN30_LOCKOUT60",
                cooldown_minutes=30,
                failure_lockout_minutes=60,
                one_signal_per_move=True,
            ),
            SimulationConfig(
                name="BREAKOUT_HOLD",
                require_breakout_hold=True,
            ),
            SimulationConfig(
                name="RETEST_CONFIRMATION",
                require_retest_confirmation=True,
            ),
        ]

    def evaluate(
        self,
        rows: Iterable[Mapping[str, object]],
        configs: Iterable[SimulationConfig] | None = None,
    ) -> dict[str, object]:
        items = [dict(row) for row in rows]
        configs = list(configs or self.default_configs())

        summaries = []
        details = {}
        for config in configs:
            accepted, suppressed = apply_simulation(items, config)
            summary = summarize_simulation(config, accepted, suppressed)
            summaries.append(summary)
            details[config.name] = {
                "summary": summary,
                "accepted": accepted,
                "suppressed": suppressed,
                "by_regime": _group_by(accepted, "regime"),
                "by_time_bucket": _group_by(accepted, "time_bucket"),
                "suppression_reasons": _group_by(suppressed, "suppression_reason"),
                "execution_allowed": False,
            }

        ranked = sorted(
            summaries,
            key=lambda row: (
                -(float(row.get("accuracy_30m") or -1)),
                -(float(row.get("mfe_mae_ratio") or -1)),
                int(row.get("max_consecutive_failures") or 999),
            ),
        )

        return {
            "summaries": summaries,
            "ranked": ranked,
            "details": details,
            "execution_allowed": False,
        }
