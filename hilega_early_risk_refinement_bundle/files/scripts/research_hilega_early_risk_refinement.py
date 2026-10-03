#!/usr/bin/env python3
"""Research three causal Hilega early-risk exits with a hard T+10 sunset.

The canonical Hilega lifecycle is the unchanged control.  Candidate exits are
valued only at observed completed five-minute closes and cannot fire after
T+10.  This is an observation-only research program; it does not modify live
strategy state, configuration, services, orders, or quantity.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable


DEFAULT_ROOT = Path("data/historical-evidence/hilega-alignment-points-490-v1")
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-early-risk-refinement-490-v2-flat-wait"
)
DIRECTIONS = ("BULLISH", "BEARISH")
POLICIES = (
    "CURRENT_EXIT_POLICY",
    "A_T5_SEVERE_FAILURE",
    "B_T5_T10_PERSISTENT_FAILURE",
    "C_EARLY_PRICE_STRUCTURE_FAILURE",
)
PREFIXES = {
    "CURRENT_EXIT_POLICY": "control",
    "A_T5_SEVERE_FAILURE": "candidate_a",
    "B_T5_T10_PERSISTENT_FAILURE": "candidate_b",
    "C_EARLY_PRICE_STRUCTURE_FAILURE": "candidate_c",
}
HEALTH_FIELDS = (
    "rsi9",
    "ema3_rsi",
    "wma21_rsi",
    "rsi9_slope_3",
    "ema3_rsi_slope_3",
    "wma21_rsi_slope_3",
    "ema_minus_wma_slope_3",
)
TRADE_NUMERIC_FIELDS = (
    "entry_price",
    "exit_price",
    "captured_points",
    "mfe_points",
    "mae_points",
    "giveback_points",
)
TIMELINE_NUMERIC_FIELDS = (
    "minutes_from_entry",
    "close",
    "directional_points_close",
    "mfe_points",
    *HEALTH_FIELDS,
)
EPSILON = 1e-9
FLAT_WMA_EPSILON = 0.10


def finite(value: Any) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty CSV: {path}")
    return rows


def load_inputs(
    trades_path: Path,
    timeline_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], int]:
    trades = read_csv(trades_path)
    timeline = read_csv(timeline_path)
    required_trade = {
        "trade_id", "session_date", "direction", "route",
        "entry_timestamp", "exit_timestamp", *TRADE_NUMERIC_FIELDS,
    }
    required_timeline = {
        "trade_id", "session_date", "timestamp", "direction",
        "is_exit_candle", *TIMELINE_NUMERIC_FIELDS,
    }
    missing_trade = required_trade - set(trades[0])
    missing_timeline = required_timeline - set(timeline[0])
    if missing_trade:
        raise ValueError(f"trade CSV missing columns: {sorted(missing_trade)}")
    if missing_timeline:
        raise ValueError(
            f"timeline CSV missing columns: {sorted(missing_timeline)}"
        )

    complete: list[dict[str, Any]] = []
    unavailable = 0
    for raw in trades:
        row = dict(raw)
        for field in TRADE_NUMERIC_FIELDS:
            row[field] = finite(row.get(field))
        if any(row[field] is None for field in TRADE_NUMERIC_FIELDS):
            unavailable += 1
            continue
        if row.get("direction") not in DIRECTIONS:
            raise ValueError(f"unsupported direction: {row.get('direction')!r}")
        row["entry_wma21_rsi_slope_3"] = finite(
            row.get("entry_wma21_rsi_slope_3")
        )
        complete.append(row)

    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in timeline:
        row = dict(raw)
        for field in TIMELINE_NUMERIC_FIELDS:
            row[field] = finite(row.get(field))
        row["is_exit_candle"] = truthy(row.get("is_exit_candle"))
        grouped[str(row["trade_id"])].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: datetime.fromisoformat(str(row["timestamp"])))
    return complete, dict(grouped), unavailable


def assign_evidence_blocks(
    trades: list[dict[str, Any]], *, observed_forward_sessions: int
) -> dict[str, Any]:
    sessions = sorted({str(row["session_date"]) for row in trades})
    if observed_forward_sessions < 0 or observed_forward_sessions >= len(sessions):
        raise ValueError("observed forward sessions must leave development data")
    development = (
        sessions[:-observed_forward_sessions]
        if observed_forward_sessions else sessions
    )
    observed = (
        sessions[-observed_forward_sessions:]
        if observed_forward_sessions else []
    )
    # Three chronological development blocks expose regime instability without
    # pretending that previously inspected evidence remains an untouched OOS.
    block_size = len(development) // 3
    block_1 = set(development[:block_size])
    block_2 = set(development[block_size:2 * block_size])
    block_3 = set(development[2 * block_size:])
    observed_set = set(observed)
    for row in trades:
        day = str(row["session_date"])
        if day in block_1:
            row["evidence_block"] = "DEVELOPMENT_BLOCK_1"
        elif day in block_2:
            row["evidence_block"] = "DEVELOPMENT_BLOCK_2"
        elif day in block_3:
            row["evidence_block"] = "DEVELOPMENT_BLOCK_3"
        elif day in observed_set:
            row["evidence_block"] = "OBSERVED_FORWARD"
        else:
            row["evidence_block"] = "UNASSIGNED"
    return {
        "all_sessions": len(sessions),
        "development_sessions": len(development),
        "development_block_1": len(block_1),
        "development_block_2": len(block_2),
        "development_block_3": len(block_3),
        "observed_forward_sessions": len(observed_set),
        "observed_forward_dates": observed,
        "new_untouched_confirmation_sessions": 0,
        "first_session": sessions[0],
        "last_session": sessions[-1],
    }


def directional_wma_state(value: float | None, direction: str) -> str:
    if value is None:
        return "UNAVAILABLE"
    sign = 1.0 if direction == "BULLISH" else -1.0
    directional = sign * value
    if directional > FLAT_WMA_EPSILON:
        return "SUPPORTING"
    if directional < -FLAT_WMA_EPSILON:
        return "OPPOSING"
    return "FLAT_WAIT"


def candle_health(row: dict[str, Any], direction: str) -> dict[str, Any]:
    missing = [field for field in HEALTH_FIELDS if row.get(field) is None]
    if missing:
        return {
            "health_available": False,
            "missing_health_fields": "|".join(missing),
            "failure_count": None,
            "failure_reasons": "",
        }
    sign = 1.0 if direction == "BULLISH" else -1.0
    wma_state = directional_wma_state(
        float(row["wma21_rsi_slope_3"]), direction
    )
    checks = {
        "EMA_WMA_ORDER": sign * (
            float(row["ema3_rsi"]) - float(row["wma21_rsi"])
        ) > 0.0,
        "RSI_SLOPE": sign * float(row["rsi9_slope_3"]) > 0.0,
        "EMA_SLOPE": sign * float(row["ema3_rsi_slope_3"]) > 0.0,
        "GAP_EXPANSION": sign * float(row["ema_minus_wma_slope_3"]) > 0.0,
    }
    failures = [name for name, supported in checks.items() if not supported]
    # Flat is deliberately neutral. Only a slope beyond the opposite epsilon
    # is counted as a WMA failure.
    if wma_state == "OPPOSING":
        failures.append("WMA_SLOPE_OPPOSING")
    return {
        "health_available": True,
        "missing_health_fields": "",
        "failure_count": len(failures),
        "failure_reasons": "|".join(failures),
        "wma_state": wma_state,
        "ema_wma_order_support": checks["EMA_WMA_ORDER"],
        "rsi_slope_support": checks["RSI_SLOPE"],
        "ema_slope_support": checks["EMA_SLOPE"],
        "wma_slope_support": wma_state == "SUPPORTING",
        "wma_slope_opposing": wma_state == "OPPOSING",
        "wma_flat_wait": wma_state == "FLAT_WAIT",
        "gap_expansion_support": checks["GAP_EXPANSION"],
    }


def eligible_checkpoints(
    trade: dict[str, Any], timeline: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    entry_at = datetime.fromisoformat(str(trade["entry_timestamp"]))
    exit_at = datetime.fromisoformat(str(trade["exit_timestamp"]))
    output: list[dict[str, Any]] = []
    for raw in timeline:
        timestamp = datetime.fromisoformat(str(raw["timestamp"]))
        if timestamp <= entry_at or timestamp > exit_at:
            continue
        minutes = int((timestamp - entry_at).total_seconds() // 60)
        # Hard causal sunset: nothing before T+5 or after T+10 can trigger.
        if minutes not in (5, 10):
            continue
        row = dict(raw)
        row["derived_minutes_from_entry"] = minutes
        row.update(candle_health(row, str(trade["direction"])))
        output.append(row)
    return output


def base_result(trade: dict[str, Any], policy: str) -> dict[str, Any]:
    return {
        "policy": policy,
        "status": "CONTROL_EXIT",
        "exit_timestamp": trade["exit_timestamp"],
        "exit_price": float(trade["exit_price"]),
        "exit_points": float(trade["captured_points"]),
        "candidate_fired": False,
        "signal_minutes_from_entry": None,
        "directional_points_at_signal": None,
        "mfe_at_signal": None,
        "failure_count": None,
        "failure_reasons": "",
        "wma_state_at_signal": None,
        "valuation_basis": "CANONICAL_CONTROL_EXIT",
    }


def condition_a(row: dict[str, Any]) -> bool:
    return bool(
        row.get("health_available")
        and row["derived_minutes_from_entry"] == 5
        and float(row["directional_points_close"]) <= 0.0
        and float(row["mfe_points"]) < 5.0
        and int(row["failure_count"]) >= 4
    )


def basic_unhealthy(row: dict[str, Any]) -> bool:
    return bool(
        row.get("health_available")
        and float(row["directional_points_close"]) <= 0.0
        and int(row["failure_count"]) >= 2
    )


def condition_c(row: dict[str, Any]) -> bool:
    return bool(
        row.get("health_available")
        and row["derived_minutes_from_entry"] in (5, 10)
        and float(row["directional_points_close"]) <= 0.0
        and float(row["mfe_points"]) < 10.0
        and not row["ema_wma_order_support"]
        and not row["gap_expansion_support"]
        and row["wma_slope_opposing"]
    )


def candidate_result(
    trade: dict[str, Any], timeline: list[dict[str, Any]], policy: str
) -> dict[str, Any]:
    control = base_result(trade, policy)
    if policy == "CURRENT_EXIT_POLICY":
        return control
    checkpoints = {
        int(row["derived_minutes_from_entry"]): row
        for row in eligible_checkpoints(trade, timeline)
    }
    signal: dict[str, Any] | None = None
    if policy == "A_T5_SEVERE_FAILURE":
        row = checkpoints.get(5)
        if row is None:
            return {**control, "status": "EXACT_T5_UNAVAILABLE"}
        if condition_a(row):
            signal = row
    elif policy == "B_T5_T10_PERSISTENT_FAILURE":
        t5 = checkpoints.get(5)
        t10 = checkpoints.get(10)
        if t5 is None or t10 is None:
            return {**control, "status": "T5_OR_T10_UNAVAILABLE"}
        if (
            basic_unhealthy(t5)
            and basic_unhealthy(t10)
            and float(t10["mfe_points"]) < 10.0
        ):
            signal = t10
    elif policy == "C_EARLY_PRICE_STRUCTURE_FAILURE":
        for minute in (5, 10):
            row = checkpoints.get(minute)
            if row is not None and condition_c(row):
                signal = row
                break
    else:
        raise ValueError(f"unknown policy: {policy}")

    if signal is None:
        return control
    signal_at = datetime.fromisoformat(str(signal["timestamp"]))
    control_at = datetime.fromisoformat(str(trade["exit_timestamp"]))
    if signal_at >= control_at:
        return {
            **control,
            "status": "CONTROL_SAME_CANDLE_PRIORITY",
            "signal_minutes_from_entry": signal["derived_minutes_from_entry"],
            "directional_points_at_signal": signal["directional_points_close"],
            "mfe_at_signal": signal["mfe_points"],
            "failure_count": signal["failure_count"],
            "failure_reasons": signal["failure_reasons"],
            "wma_state_at_signal": signal["wma_state"],
        }

    close = float(signal["close"])
    entry = float(trade["entry_price"])
    points = close - entry if trade["direction"] == "BULLISH" else entry - close
    return {
        "policy": policy,
        "status": "CANDIDATE_EXIT",
        "exit_timestamp": signal["timestamp"],
        "exit_price": close,
        "exit_points": points,
        "candidate_fired": True,
        "signal_minutes_from_entry": signal["derived_minutes_from_entry"],
        "directional_points_at_signal": signal["directional_points_close"],
        "mfe_at_signal": signal["mfe_points"],
        "failure_count": signal["failure_count"],
        "failure_reasons": signal["failure_reasons"],
        "wma_state_at_signal": signal["wma_state"],
        "valuation_basis": "OBSERVED_COMPLETED_FIVE_MINUTE_CLOSE",
    }


def outcome_label(control_points: float, candidate_points: float, fired: bool) -> str:
    delta = candidate_points - control_points
    if control_points < 0.0:
        if not fired:
            return "BAD_TRADE_NOT_DETECTED"
        if delta > EPSILON:
            return "BAD_TRADE_CORRECTLY_EXITED_EARLY"
        if abs(delta) <= EPSILON:
            return "BAD_TRADE_EXITED_NO_CHANGE"
        return "BAD_TRADE_EXIT_HARMED"
    if control_points > 0.0:
        if not fired:
            return "GOOD_TRADE_RETAINED"
        if delta < -EPSILON:
            return "GOOD_TRADE_WRONGLY_EXITED_EARLY"
        if delta > EPSILON:
            return "GOOD_TRADE_EXIT_IMPROVED"
        return "GOOD_TRADE_EXITED_NO_CHANGE"
    return "FLAT_CONTROL_TRADE"


def simulate(
    trades: list[dict[str, Any]], timeline: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for trade in trades:
        row = dict(trade)
        values = timeline.get(str(trade["trade_id"]), [])
        for policy in POLICIES:
            result = candidate_result(trade, values, policy)
            prefix = PREFIXES[policy]
            for key, value in result.items():
                if key != "policy":
                    row[f"{prefix}_{key}"] = value
            if policy != "CURRENT_EXIT_POLICY":
                control_points = float(trade["captured_points"])
                candidate_points = float(result["exit_points"])
                delta = candidate_points - control_points
                row[f"{prefix}_delta_vs_control"] = delta
                row[f"{prefix}_outcome_label"] = outcome_label(
                    control_points, candidate_points, bool(result["candidate_fired"])
                )
                row[f"{prefix}_plus20_move_destroyed"] = bool(
                    result["candidate_fired"]
                    and float(trade["mfe_points"]) >= 20.0
                    and float(result["mfe_at_signal"] or 0.0) < 20.0
                )
        output.append(row)
    return output


def maximum_drawdown(points: Iterable[float]) -> float:
    equity = peak = worst = 0.0
    for value in points:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def metrics(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    points = [float(row[field]) for row in rows]
    if not points:
        return {
            "trades": 0, "total_points": 0.0, "mean_points": None,
            "median_points": None, "positive": 0, "negative": 0,
            "win_rate_pct": None, "profit_factor": None,
            "max_drawdown_points": 0.0,
        }
    gains = sum(value for value in points if value > 0.0)
    losses = -sum(value for value in points if value < 0.0)
    positive = sum(value > 0.0 for value in points)
    return {
        "trades": len(points),
        "total_points": sum(points),
        "mean_points": fmean(points),
        "median_points": median(points),
        "positive": positive,
        "negative": sum(value < 0.0 for value in points),
        "win_rate_pct": 100.0 * positive / len(points),
        "profit_factor": gains / losses if losses else None,
        "max_drawdown_points": maximum_drawdown(points),
    }


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def learn_development_thresholds(rows: list[dict[str, Any]]) -> dict[str, float]:
    output: dict[str, float] = {}
    for direction in DIRECTIONS:
        values = [
            float(row["mfe_points"]) for row in rows
            if row["direction"] == direction
            and str(row["evidence_block"]).startswith("DEVELOPMENT_")
        ]
        if not values:
            raise ValueError(f"no development rows for {direction}")
        output[direction] = percentile(values, 0.90)
    return output


def policy_summary(
    rows: list[dict[str, Any]], thresholds: dict[str, float]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    blocks = (
        "DEVELOPMENT_ALL", "DEVELOPMENT_BLOCK_1", "DEVELOPMENT_BLOCK_2",
        "DEVELOPMENT_BLOCK_3", "OBSERVED_FORWARD", "ALL_OBSERVED",
    )
    for block in blocks:
        for direction in (*DIRECTIONS, "ALL"):
            if block == "DEVELOPMENT_ALL":
                cohort = [
                    row for row in rows
                    if str(row["evidence_block"]).startswith("DEVELOPMENT_")
                ]
            elif block == "ALL_OBSERVED":
                cohort = list(rows)
            else:
                cohort = [row for row in rows if row["evidence_block"] == block]
            if direction != "ALL":
                cohort = [row for row in cohort if row["direction"] == direction]
            if not cohort:
                continue
            for policy in POLICIES:
                prefix = PREFIXES[policy]
                points_field = f"{prefix}_exit_points"
                result = {
                    "evidence_block": block,
                    "direction": direction,
                    "policy": policy,
                    **metrics(cohort, points_field),
                }
                if policy == "CURRENT_EXIT_POLICY":
                    result.update({
                        "candidate_exits": 0,
                        "delta_vs_control_sum": 0.0,
                        "net_point_recovery": 0.0,
                        "bad_trades_saved": 0,
                        "bad_trades_missed": sum(
                            float(row["captured_points"]) < 0.0 for row in cohort
                        ),
                        "bad_trades_exit_harmed": 0,
                        "good_trades_retained": sum(
                            float(row["captured_points"]) > 0.0 for row in cohort
                        ),
                        "good_trades_wrongly_exited": 0,
                        "good_trades_exit_improved": 0,
                        "points_saved_on_bad_trades": 0.0,
                        "points_lost_on_good_trades": 0.0,
                        "plus20_moves": sum(
                            float(row["mfe_points"]) >= 20.0 for row in cohort
                        ),
                        "plus20_moves_destroyed": 0,
                        "plus20_moves_retained": sum(
                            float(row["mfe_points"]) >= 20.0 for row in cohort
                        ),
                        "top_decile_moves": sum(
                            float(row["mfe_points"]) >= thresholds[row["direction"]]
                            for row in cohort
                        ),
                        "top_decile_moves_destroyed": 0,
                        "top_decile_moves_retained": sum(
                            float(row["mfe_points"]) >= thresholds[row["direction"]]
                            for row in cohort
                        ),
                    })
                else:
                    labels = Counter(row[f"{prefix}_outcome_label"] for row in cohort)
                    fired = [row for row in cohort if row[f"{prefix}_candidate_fired"]]
                    result.update({
                        "candidate_exits": len(fired),
                        "delta_vs_control_sum": sum(
                            float(row[f"{prefix}_delta_vs_control"]) for row in cohort
                        ),
                        "net_point_recovery": sum(
                            float(row[f"{prefix}_delta_vs_control"]) for row in cohort
                        ),
                        "bad_trades_saved": labels[
                            "BAD_TRADE_CORRECTLY_EXITED_EARLY"
                        ],
                        "bad_trades_missed": labels["BAD_TRADE_NOT_DETECTED"],
                        "bad_trades_exit_harmed": labels["BAD_TRADE_EXIT_HARMED"],
                        "good_trades_retained": labels["GOOD_TRADE_RETAINED"],
                        "good_trades_wrongly_exited": labels[
                            "GOOD_TRADE_WRONGLY_EXITED_EARLY"
                        ],
                        "good_trades_exit_improved": labels[
                            "GOOD_TRADE_EXIT_IMPROVED"
                        ],
                        "points_saved_on_bad_trades": sum(
                            max(0.0, float(row[f"{prefix}_delta_vs_control"]))
                            for row in cohort
                            if float(row["captured_points"]) < 0.0
                        ),
                        "points_lost_on_good_trades": sum(
                            max(0.0, -float(row[f"{prefix}_delta_vs_control"]))
                            for row in cohort
                            if float(row["captured_points"]) > 0.0
                        ),
                        "plus20_moves": sum(
                            float(row["mfe_points"]) >= 20.0 for row in cohort
                        ),
                        "plus20_moves_destroyed": sum(
                            bool(row[f"{prefix}_plus20_move_destroyed"])
                            for row in cohort
                        ),
                        "plus20_moves_retained": sum(
                            float(row["mfe_points"]) >= 20.0
                            and not bool(row[f"{prefix}_plus20_move_destroyed"])
                            for row in cohort
                        ),
                        "top_decile_moves": sum(
                            float(row["mfe_points"]) >= thresholds[row["direction"]]
                            for row in cohort
                        ),
                        "top_decile_moves_destroyed": sum(
                            bool(row[f"{prefix}_candidate_fired"])
                            and float(row["mfe_points"])
                            >= thresholds[row["direction"]]
                            for row in cohort
                        ),
                        "top_decile_moves_retained": sum(
                            float(row["mfe_points"])
                            >= thresholds[row["direction"]]
                            and not bool(row[f"{prefix}_candidate_fired"])
                            for row in cohort
                        ),
                    })
                output.append(result)
    return output


def outcome_matrix(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for policy in POLICIES[1:]:
        prefix = PREFIXES[policy]
        groups: defaultdict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[(
                str(row["evidence_block"]),
                str(row["direction"]),
                str(row[f"{prefix}_outcome_label"]),
            )].append(row)
        for key, cohort in sorted(groups.items()):
            deltas = [float(row[f"{prefix}_delta_vs_control"]) for row in cohort]
            output.append({
                "policy": policy,
                "evidence_block": key[0],
                "direction": key[1],
                "outcome_label": key[2],
                "trades": len(cohort),
                "control_points": sum(float(row["captured_points"]) for row in cohort),
                "candidate_points": sum(float(row[f"{prefix}_exit_points"]) for row in cohort),
                "point_delta": sum(deltas),
                "mean_point_delta": fmean(deltas),
            })
    return output


def decision_ledger(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        for policy in POLICIES[1:]:
            prefix = PREFIXES[policy]
            output.append({
                "policy": policy,
                "outcome_label": row[f"{prefix}_outcome_label"],
                "session_date": row["session_date"],
                "evidence_block": row["evidence_block"],
                "trade_id": row["trade_id"],
                "direction": row["direction"],
                "route": row["route"],
                "entry_timestamp": row["entry_timestamp"],
                "entry_price": row["entry_price"],
                "control_exit_timestamp": row["exit_timestamp"],
                "control_exit_price": row["exit_price"],
                "control_points": row["captured_points"],
                "candidate_fired": row[f"{prefix}_candidate_fired"],
                "candidate_exit_timestamp": row[f"{prefix}_exit_timestamp"],
                "candidate_exit_price": row[f"{prefix}_exit_price"],
                "candidate_points": row[f"{prefix}_exit_points"],
                "point_delta": row[f"{prefix}_delta_vs_control"],
                "signal_minutes_from_entry": row[
                    f"{prefix}_signal_minutes_from_entry"
                ],
                "progress_at_signal": row[f"{prefix}_directional_points_at_signal"],
                "mfe_at_signal": row[f"{prefix}_mfe_at_signal"],
                "final_mfe_points": row["mfe_points"],
                "plus20_move": float(row["mfe_points"]) >= 20.0,
                "plus20_move_destroyed": row[
                    f"{prefix}_plus20_move_destroyed"
                ],
                "failure_count": row[f"{prefix}_failure_count"],
                "failure_reasons": row[f"{prefix}_failure_reasons"],
                "wma_state_at_signal": row[f"{prefix}_wma_state_at_signal"],
            })
    return output


def checkpoint_ledger(
    trades: list[dict[str, Any]],
    timeline: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Expose every exact T+5/T+10 value used by the candidates."""
    output: list[dict[str, Any]] = []
    for trade in trades:
        checkpoints = {
            int(row["derived_minutes_from_entry"]): row
            for row in eligible_checkpoints(
                trade, timeline.get(str(trade["trade_id"]), [])
            )
        }
        entry_wma_slope = finite(trade.get("entry_wma21_rsi_slope_3"))
        entry_wma_state = directional_wma_state(
            entry_wma_slope, str(trade["direction"])
        )
        for minute in (5, 10):
            row = checkpoints.get(minute)
            output.append({
                "session_date": trade["session_date"],
                "evidence_block": trade["evidence_block"],
                "trade_id": trade["trade_id"],
                "direction": trade["direction"],
                "route": trade["route"],
                "entry_timestamp": trade["entry_timestamp"],
                "entry_price": trade["entry_price"],
                "entry_wma21_rsi_slope_3": entry_wma_slope,
                "entry_wma_state": entry_wma_state,
                "checkpoint": f"T+{minute}",
                "checkpoint_available": row is not None,
                "checkpoint_timestamp": None if row is None else row["timestamp"],
                "checkpoint_close": None if row is None else row["close"],
                "directional_points_close": (
                    None if row is None else row["directional_points_close"]
                ),
                "running_mfe_points": None if row is None else row["mfe_points"],
                "rsi9": None if row is None else row["rsi9"],
                "ema3_rsi": None if row is None else row["ema3_rsi"],
                "wma21_rsi": None if row is None else row["wma21_rsi"],
                "rsi9_slope_3": None if row is None else row["rsi9_slope_3"],
                "ema3_rsi_slope_3": (
                    None if row is None else row["ema3_rsi_slope_3"]
                ),
                "wma21_rsi_slope_3": (
                    None if row is None else row["wma21_rsi_slope_3"]
                ),
                "wma_state": None if row is None else row.get("wma_state"),
                "ema_minus_wma_slope_3": (
                    None if row is None else row["ema_minus_wma_slope_3"]
                ),
                "ema_wma_order_support": (
                    None if row is None else row.get("ema_wma_order_support")
                ),
                "gap_expansion_support": (
                    None if row is None else row.get("gap_expansion_support")
                ),
                "wma_flat_wait": (
                    None if row is None else row.get("wma_flat_wait")
                ),
                "wma_slope_opposing": (
                    None if row is None else row.get("wma_slope_opposing")
                ),
                "failure_count": None if row is None else row.get("failure_count"),
                "failure_reasons": (
                    "" if row is None else row.get("failure_reasons", "")
                ),
                "control_exit_timestamp": trade["exit_timestamp"],
                "control_exit_price": trade["exit_price"],
                "control_points": trade["captured_points"],
                "final_mfe_points": trade["mfe_points"],
                "control_outcome": (
                    "POSITIVE" if float(trade["captured_points"]) > 0.0
                    else "NEGATIVE" if float(trade["captured_points"]) < 0.0
                    else "FLAT"
                ),
                "reached_plus20": float(trade["mfe_points"]) >= 20.0,
            })
    return output


def wma_transition_summary(
    trades: list[dict[str, Any]],
    timeline: dict[str, list[dict[str, Any]]],
    thresholds: dict[str, float],
) -> list[dict[str, Any]]:
    groups: defaultdict[
        tuple[str, str, str, str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    for trade in trades:
        checkpoints = {
            int(row["derived_minutes_from_entry"]): row
            for row in eligible_checkpoints(
                trade, timeline.get(str(trade["trade_id"]), [])
            )
        }
        entry_state = directional_wma_state(
            finite(trade.get("entry_wma21_rsi_slope_3")),
            str(trade["direction"]),
        )
        t5_state = (
            checkpoints[5].get("wma_state", "UNAVAILABLE")
            if 5 in checkpoints else "UNAVAILABLE"
        )
        t10_state = (
            checkpoints[10].get("wma_state", "UNAVAILABLE")
            if 10 in checkpoints else "UNAVAILABLE"
        )
        groups[(
            str(trade["evidence_block"]), str(trade["direction"]),
            entry_state, str(t5_state), str(t10_state),
        )].append(trade)

    output: list[dict[str, Any]] = []
    for key, cohort in sorted(groups.items()):
        points = [float(row["captured_points"]) for row in cohort]
        output.append({
            "evidence_block": key[0],
            "direction": key[1],
            "entry_wma_state": key[2],
            "t5_wma_state": key[3],
            "t10_wma_state": key[4],
            "trades": len(cohort),
            "total_control_points": sum(points),
            "mean_control_points": fmean(points),
            "positive": sum(value > 0.0 for value in points),
            "negative": sum(value < 0.0 for value in points),
            "win_rate_pct": 100.0 * sum(value > 0.0 for value in points) / len(points),
            "plus20_moves": sum(
                float(row["mfe_points"]) >= 20.0 for row in cohort
            ),
            "top_decile_moves": sum(
                float(row["mfe_points"]) >= thresholds[row["direction"]]
                for row in cohort
            ),
        })
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trades", type=Path,
        default=DEFAULT_ROOT / "trade-alignment-points.csv",
    )
    parser.add_argument(
        "--timeline", type=Path,
        default=DEFAULT_ROOT / "trade-health-timeline.csv",
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--observed-forward-sessions", type=int, default=10)
    parser.add_argument(
        "--validation-dates", nargs="+",
        default=("2026-09-30", "2026-10-01"),
    )
    args = parser.parse_args()

    trades, timeline, unavailable = load_inputs(args.trades, args.timeline)
    universe = assign_evidence_blocks(
        trades, observed_forward_sessions=args.observed_forward_sessions
    )
    results = simulate(trades, timeline)
    thresholds = learn_development_thresholds(results)
    summary = policy_summary(results, thresholds)
    matrix = outcome_matrix(results)
    ledger = decision_ledger(results)
    checkpoints = checkpoint_ledger(trades, timeline)
    transitions = wma_transition_summary(trades, timeline, thresholds)
    selected = [
        row for row in checkpoints
        if str(row["session_date"]) in set(args.validation_dates)
    ]
    fired = [row for row in ledger if row["candidate_fired"]]
    bad_missed = [
        row for row in ledger if row["outcome_label"] == "BAD_TRADE_NOT_DETECTED"
    ]
    major_destroyed = [
        row for row in ledger
        if row["candidate_fired"]
        and float(row["final_mfe_points"]) >= thresholds[row["direction"]]
    ]

    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "policy-summary.csv", summary)
    write_csv(args.output_root / "outcome-matrix.csv", matrix)
    write_csv(args.output_root / "trade-policy-comparison.csv", results)
    write_csv(args.output_root / "candidate-exit-ledger.csv", fired)
    write_csv(args.output_root / "bad-trades-not-detected.csv", bad_missed)
    write_csv(args.output_root / "checkpoint-values.csv", checkpoints)
    write_csv(args.output_root / "wma-transition-summary.csv", transitions)
    write_csv(args.output_root / "selected-date-checkpoints.csv", selected)
    write_csv(args.output_root / "top-decile-moves-destroyed.csv", major_destroyed)

    headline = [
        row for row in summary
        if row["evidence_block"] in ("DEVELOPMENT_ALL", "OBSERVED_FORWARD")
        and row["direction"] == "ALL"
    ]
    report = {
        "model": "HILEGA_EARLY_RISK_REFINEMENT_490_V2_FLAT_WAIT",
        "session_universe": universe,
        "completed_trades": len(results),
        "excluded_unavailable_trades": unavailable,
        "development_top_decile_mfe_thresholds": thresholds,
        "candidate_definitions": {
            "A_T5_SEVERE_FAILURE": (
                "Exact T+5 only: close progress <=0, causal running MFE <5, "
                "and at least four health components fail. A flat WMA is "
                "neutral and is not counted as a failure."
            ),
            "B_T5_T10_PERSISTENT_FAILURE": (
                "Both exact T+5 and T+10 must have close progress <=0 and at "
                "least two health failures; causal running MFE at T+10 <10. "
                "A flat WMA is neutral."
            ),
            "C_EARLY_PRICE_STRUCTURE_FAILURE": (
                "At exact T+5 or T+10: close progress <=0, causal running MFE "
                "<10, EMA/WMA order lost, gap not expanding, and WMA slope "
                "strictly opposes the trade beyond the flat epsilon."
            ),
            "hard_sunset": "No candidate can signal after T+10.",
            "wma_states": {
                "SUPPORTING": "directional slope > +0.10",
                "FLAT_WAIT": "directional slope from -0.10 through +0.10",
                "OPPOSING": "directional slope < -0.10",
            },
        },
        "headline_summary": headline,
        "required_outcome_labels": [
            "BAD_TRADE_CORRECTLY_EXITED_EARLY",
            "BAD_TRADE_NOT_DETECTED",
            "GOOD_TRADE_RETAINED",
            "GOOD_TRADE_WRONGLY_EXITED_EARLY",
        ],
        "interpretation_guards": [
            "All 480 frozen historical sessions are development evidence because prior OOS results were inspected.",
            "The existing 10 forward sessions are already observed evidence, not untouched confirmation.",
            "Only sessions arriving after rule selection may be called untouched confirmation.",
            "Canonical Hilega entries and exits remain unchanged.",
            "Candidate valuation uses an observed completed five-minute close.",
            "WMA21 means WMA21 of RSI9 on completed five-minute candles.",
            "FLAT_WAIT is neutral and cannot by itself reject or exit a trade.",
            "Canonical exit retains priority on the same candle.",
            "Underlying points exclude option premiums, spread, charges and quantity.",
        ],
        "safety": {
            "research_only": True,
            "observation_only": True,
            "live_strategy_modified": False,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        },
    }
    (args.output_root / "report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )

    print("HILEGA EARLY-RISK REFINEMENT — HARD T+10 SUNSET")
    print("Sessions", universe)
    print("Trades", len(results), "unavailable excluded", unavailable)
    print("Development top-decile MFE", thresholds)
    print("HEADLINE")
    for row in headline:
        print(row)
    print("SELECTED DATES")
    for row in selected:
        print({
            "date": row["session_date"],
            "trade": row["trade_id"],
            "direction": row["direction"],
            "entry": row["entry_timestamp"],
            "checkpoint": row["checkpoint"],
            "time": row["checkpoint_timestamp"],
            "points": row["directional_points_close"],
            "mfe": row["running_mfe_points"],
            "wma_slope": row["wma21_rsi_slope_3"],
            "wma_state": row["wma_state"],
            "failures": row["failure_count"],
            "control_points": row["control_points"],
            "plus20": row["reached_plus20"],
        })
    print("Output:", args.output_root / "report.json")
    print("Read only: strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
