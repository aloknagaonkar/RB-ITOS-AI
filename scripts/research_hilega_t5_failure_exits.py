#!/usr/bin/env python3
"""Backtest causal T+5 Hilega failure exits on the 490-session trade timeline.

Policies:
* CURRENT_EXIT_POLICY: unchanged canonical entry and exit.
* T5_IMMEDIATE_FAILURE: at the exact next completed five-minute candle, exit
  at its observed close when directional close progress is non-positive and at
  least two entry-health components fail.
* T5_TWO_CLOSE_FAILURE: starting at T+5, require the same unhealthy condition
  on two consecutive completed five-minute candles and exit at the second
  observed close.

All inputs are available on the evaluated completed candle.  A canonical exit
on the same candle retains priority.  This program is research-only.
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


DEFAULT_ROOT = Path(
    "data/historical-evidence/hilega-alignment-points-490-v1"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-t5-failure-exits-490-v1"
)
POLICIES = (
    "CURRENT_EXIT_POLICY",
    "T5_IMMEDIATE_FAILURE",
    "T5_TWO_CLOSE_FAILURE",
)
DIRECTIONS = ("BULLISH", "BEARISH")
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
    *HEALTH_FIELDS,
)


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
    trades_path: Path, timeline_path: Path
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

    complete_trades: list[dict[str, Any]] = []
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
        complete_trades.append(row)

    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in timeline:
        row = dict(raw)
        for field in TIMELINE_NUMERIC_FIELDS:
            row[field] = finite(row.get(field))
        row["is_exit_candle"] = truthy(row.get("is_exit_candle"))
        grouped[str(row["trade_id"])].append(row)
    for values in grouped.values():
        values.sort(key=lambda row: datetime.fromisoformat(row["timestamp"]))
    return complete_trades, dict(grouped), unavailable


def assign_splits(
    trades: list[dict[str, Any]], *, forward_sessions: int, is_ratio: float
) -> dict[str, Any]:
    sessions = sorted({str(row["session_date"]) for row in trades})
    if forward_sessions < 0 or forward_sessions >= len(sessions):
        raise ValueError("forward_sessions must leave frozen sessions")
    frozen = sessions[:-forward_sessions] if forward_sessions else sessions
    forward = sessions[-forward_sessions:] if forward_sessions else []
    split_at = int(len(frozen) * is_ratio)
    is_set = set(frozen[:split_at])
    oos_set = set(frozen[split_at:])
    forward_set = set(forward)
    for row in trades:
        day = str(row["session_date"])
        row["research_split"] = (
            "IS" if day in is_set
            else "OOS" if day in oos_set
            else "FORWARD" if day in forward_set
            else "UNASSIGNED"
        )
    return {
        "all": len(sessions),
        "frozen": len(frozen),
        "is": len(is_set),
        "oos": len(oos_set),
        "forward": len(forward_set),
        "first": sessions[0],
        "last": sessions[-1],
        "forward_dates": forward,
    }


def candle_health(row: dict[str, Any], direction: str) -> dict[str, Any]:
    missing = [field for field in HEALTH_FIELDS if row.get(field) is None]
    if missing:
        return {
            "available": False,
            "missing": "|".join(missing),
            "failure_count": None,
            "failure_reasons": "",
            "unhealthy": False,
        }
    sign = 1.0 if direction == "BULLISH" else -1.0
    checks = {
        "EMA_WMA_ORDER_LOST": sign * (
            float(row["ema3_rsi"]) - float(row["wma21_rsi"])
        ) > 0.0,
        "RSI_SLOPE_ADVERSE": sign * float(row["rsi9_slope_3"]) > 0.0,
        "EMA_SLOPE_ADVERSE": sign * float(row["ema3_rsi_slope_3"]) > 0.0,
        "WMA_SLOPE_ADVERSE": sign * float(row["wma21_rsi_slope_3"]) > 0.0,
        "GAP_NOT_EXPANDING": sign * float(
            row["ema_minus_wma_slope_3"]
        ) > 0.0,
    }
    failures = [reason for reason, passes in checks.items() if not passes]
    points = row.get("directional_points_close")
    unhealthy = (
        points is not None
        and float(points) <= 0.0
        and len(failures) >= 2
    )
    return {
        "available": True,
        "missing": "",
        "failure_count": len(failures),
        "failure_reasons": "|".join(failures),
        "unhealthy": unhealthy,
        **{
            reason.lower().replace("_adverse", "_support").replace(
                "_lost", "_support"
            ).replace("not_expanding", "expansion_support"): passes
            for reason, passes in checks.items()
        },
    }


def eligible_bars(
    trade: dict[str, Any], timeline: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    entry_at = datetime.fromisoformat(str(trade["entry_timestamp"]))
    exit_at = datetime.fromisoformat(str(trade["exit_timestamp"]))
    output = []
    for raw in timeline:
        timestamp = datetime.fromisoformat(str(raw["timestamp"]))
        if timestamp <= entry_at or timestamp > exit_at:
            continue
        row = dict(raw)
        row["derived_minutes_from_entry"] = int(
            (timestamp - entry_at).total_seconds() // 60
        )
        row.update(candle_health(row, str(trade["direction"])))
        output.append(row)
    return output


def candidate_result(
    trade: dict[str, Any], timeline: list[dict[str, Any]], policy: str
) -> dict[str, Any]:
    control_points = float(trade["captured_points"])
    control = {
        "policy": policy,
        "status": "CONTROL_EXIT",
        "exit_timestamp": trade["exit_timestamp"],
        "exit_price": float(trade["exit_price"]),
        "exit_points": control_points,
        "candidate_fired": False,
        "failure_count": None,
        "failure_reasons": "",
        "signal_minutes_from_entry": None,
        "valuation_basis": "CANONICAL_CONTROL_EXIT",
    }
    if policy == "CURRENT_EXIT_POLICY":
        return control

    bars = eligible_bars(trade, timeline)
    if not bars:
        return {**control, "status": "TIMELINE_UNAVAILABLE"}

    signal: dict[str, Any] | None = None
    if policy == "T5_IMMEDIATE_FAILURE":
        exact = [row for row in bars if row["derived_minutes_from_entry"] == 5]
        if not exact:
            return {**control, "status": "EXACT_T5_UNAVAILABLE"}
        if exact[0]["unhealthy"]:
            signal = exact[0]
    elif policy == "T5_TWO_CLOSE_FAILURE":
        consecutive = 0
        for row in bars:
            if row["derived_minutes_from_entry"] < 5:
                continue
            if row["unhealthy"]:
                consecutive += 1
            else:
                consecutive = 0
            if consecutive >= 2:
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
            "failure_count": signal["failure_count"],
            "failure_reasons": signal["failure_reasons"],
            "signal_minutes_from_entry": signal["derived_minutes_from_entry"],
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
        "failure_count": signal["failure_count"],
        "failure_reasons": signal["failure_reasons"],
        "signal_minutes_from_entry": signal["derived_minutes_from_entry"],
        "valuation_basis": "OBSERVED_COMPLETED_FIVE_MINUTE_CLOSE",
    }


def simulate(
    trades: list[dict[str, Any]], timeline: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for trade in trades:
        values = timeline.get(str(trade["trade_id"]), [])
        results = {
            policy: candidate_result(trade, values, policy)
            for policy in POLICIES
        }
        row = dict(trade)
        for policy, result in results.items():
            prefix = {
                "CURRENT_EXIT_POLICY": "control",
                "T5_IMMEDIATE_FAILURE": "immediate",
                "T5_TWO_CLOSE_FAILURE": "two_close",
            }[policy]
            for key, value in result.items():
                if key != "policy":
                    row[f"{prefix}_{key}"] = value
        row["immediate_delta_vs_control"] = (
            float(row["immediate_exit_points"])
            - float(row["control_exit_points"])
        )
        row["two_close_delta_vs_control"] = (
            float(row["two_close_exit_points"])
            - float(row["control_exit_points"])
        )
        output.append(row)
    return output


def maximum_drawdown(points: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in points:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def metrics(rows: list[dict[str, Any]], points_field: str) -> dict[str, Any]:
    if not rows:
        return {
            "trades": 0, "total_points": 0.0, "mean_points": None,
            "median_points": None, "positive": 0, "negative": 0,
            "win_rate_pct": None, "profit_factor": None,
            "max_drawdown_points": 0.0,
        }
    points = [float(row[points_field]) for row in rows]
    gains = sum(value for value in points if value > 0)
    losses = -sum(value for value in points if value < 0)
    positive = sum(value > 0 for value in points)
    return {
        "trades": len(rows),
        "total_points": sum(points),
        "mean_points": fmean(points),
        "median_points": median(points),
        "positive": positive,
        "negative": sum(value < 0 for value in points),
        "win_rate_pct": 100.0 * positive / len(rows),
        "profit_factor": gains / losses if losses else None,
        "max_drawdown_points": maximum_drawdown(points),
    }


def learn_large_thresholds(rows: list[dict[str, Any]]) -> dict[str, float]:
    output: dict[str, float] = {}
    for direction in DIRECTIONS:
        values = sorted(
            float(row["mfe_points"]) for row in rows
            if row["research_split"] == "IS" and row["direction"] == direction
        )
        if not values:
            raise ValueError(f"no IS rows for {direction}")
        position = (len(values) - 1) * 0.90
        lower = math.floor(position)
        upper = math.ceil(position)
        weight = position - lower
        output[direction] = (
            values[lower] * (1.0 - weight) + values[upper] * weight
        )
    return output


def policy_summary(
    rows: list[dict[str, Any]], thresholds: dict[str, float]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    policy_fields = {
        "CURRENT_EXIT_POLICY": ("control_exit_points", "control_candidate_fired"),
        "T5_IMMEDIATE_FAILURE": (
            "immediate_exit_points", "immediate_candidate_fired"
        ),
        "T5_TWO_CLOSE_FAILURE": (
            "two_close_exit_points", "two_close_candidate_fired"
        ),
    }
    for split in ("IS", "OOS", "FORWARD"):
        for direction in (*DIRECTIONS, "ALL"):
            for route in ("ALL", "ROUTE_A", "ROUTE_B"):
                cohort = [
                    row for row in rows
                    if row["research_split"] == split
                    and (direction == "ALL" or row["direction"] == direction)
                    and (route == "ALL" or row["route"] == route)
                ]
                if not cohort:
                    continue
                large = [
                    row for row in cohort
                    if float(row["mfe_points"]) >= thresholds[row["direction"]]
                ]
                for policy, (points_field, fired_field) in policy_fields.items():
                    stats = metrics(cohort, points_field)
                    deltas = [
                        float(row[points_field])
                        - float(row["control_exit_points"])
                        for row in cohort
                    ]
                    early_large = [row for row in large if row[fired_field]]
                    output.append({
                        "split": split,
                        "direction": direction,
                        "route": route,
                        "policy": policy,
                        **stats,
                        "candidate_exits": sum(bool(row[fired_field]) for row in cohort),
                        "delta_vs_control_sum": sum(deltas),
                        "improved": sum(delta > 1e-9 for delta in deltas),
                        "equal": sum(abs(delta) <= 1e-9 for delta in deltas),
                        "harmed": sum(delta < -1e-9 for delta in deltas),
                        "control_winners_harmed": sum(
                            float(row["control_exit_points"]) > 0.0
                            and float(row[points_field])
                            < float(row["control_exit_points"]) - 1e-9
                            for row in cohort
                        ),
                        "large_moves": len(large),
                        "large_moves_exited_early": len(early_large),
                        "large_move_early_exit_pct": (
                            100.0 * len(early_large) / len(large)
                            if large else None
                        ),
                    })
    return output


def failure_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for policy_prefix in ("immediate", "two_close"):
        counter: defaultdict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
        points: defaultdict[tuple[str, str, str, str], float] = defaultdict(float)
        for row in rows:
            if not row[f"{policy_prefix}_candidate_fired"]:
                continue
            key = (row["research_split"], row["direction"], policy_prefix)
            for reason in str(row[f"{policy_prefix}_failure_reasons"]).split("|"):
                if reason:
                    counter[key][reason] += 1
                    points[(*key, reason)] += float(
                        row[f"{policy_prefix}_delta_vs_control"]
                    )
        for key, reasons in sorted(counter.items()):
            for reason, count in sorted(reasons.items()):
                output.append({
                    "split": key[0],
                    "direction": key[1],
                    "policy": key[2],
                    "failure_reason": reason,
                    "candidate_exits_containing_reason": count,
                    "delta_vs_control_for_those_trades": points[(*key, reason)],
                })
    return output


def selected_date_details(
    rows: list[dict[str, Any]], dates: set[str]
) -> list[dict[str, Any]]:
    return [
        row for row in rows if str(row["session_date"]) in dates
    ]


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
    parser.add_argument("--forward-sessions", type=int, default=10)
    parser.add_argument("--is-ratio", type=float, default=0.70)
    parser.add_argument(
        "--validation-dates", nargs="+",
        default=("2026-09-30", "2026-10-01"),
    )
    args = parser.parse_args()
    if not 0.0 < args.is_ratio < 1.0:
        raise SystemExit("STOP: --is-ratio must be between zero and one")

    trades, timeline, unavailable = load_inputs(args.trades, args.timeline)
    universe = assign_splits(
        trades,
        forward_sessions=args.forward_sessions,
        is_ratio=args.is_ratio,
    )
    results = simulate(trades, timeline)
    thresholds = learn_large_thresholds(results)
    summary = policy_summary(results, thresholds)
    failures = failure_summary(results)
    selected = selected_date_details(results, set(args.validation_dates))

    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "policy-summary.csv", summary)
    write_csv(args.output_root / "trade-policy-comparison.csv", results)
    write_csv(args.output_root / "failure-component-summary.csv", failures)
    write_csv(args.output_root / "selected-date-details.csv", selected)

    headline = [
        row for row in summary
        if row["direction"] == "ALL" and row["route"] == "ALL"
    ]
    report = {
        "model": "HILEGA_T5_FAILURE_EXIT_RESEARCH_490_V1",
        "sessions": universe,
        "completed_trades": len(results),
        "excluded_unavailable_trades": unavailable,
        "frozen_is_large_mfe_thresholds": thresholds,
        "candidate_definitions": {
            "T5_IMMEDIATE_FAILURE": (
                "At exact next completed 5m candle: directional close points "
                "<= 0 and at least two of five health components fail."
            ),
            "T5_TWO_CLOSE_FAILURE": (
                "Starting at T+5, same condition on two consecutive completed "
                "5m candles; reset counter on recovery."
            ),
            "health_components": [
                "EMA/WMA ordering", "RSI slope", "EMA slope", "WMA slope",
                "EMA-WMA gap expansion",
            ],
        },
        "headline_summary": headline,
        "interpretation_guards": [
            "Canonical entries are unchanged.",
            "No RSI50 or minimum WMA magnitude is used.",
            "Candidate valuation is the observed completed 5m candle close.",
            "Canonical exit retains priority on the same candle.",
            "IS selects; OOS and forward remain holdouts.",
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

    print("HILEGA T+5 FAILURE EXIT RESEARCH")
    print("Sessions", universe)
    print("Trades", len(results), "unavailable excluded", unavailable)
    print("HEADLINE")
    for row in headline:
        print(row)
    print("SELECTED DATES")
    for row in selected:
        print({
            "date": row["session_date"],
            "direction": row["direction"],
            "route": row["route"],
            "entry": row["entry_timestamp"],
            "control_exit": row["control_exit_timestamp"],
            "control_points": row["control_exit_points"],
            "immediate_exit": row["immediate_exit_timestamp"],
            "immediate_points": row["immediate_exit_points"],
            "immediate_status": row["immediate_status"],
            "two_close_exit": row["two_close_exit_timestamp"],
            "two_close_points": row["two_close_exit_points"],
            "two_close_status": row["two_close_status"],
        })
    print("Output:", args.output_root / "report.json")
    print("Read only: strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
