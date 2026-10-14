#!/usr/bin/env python3
"""Evaluate a causal one-minute persistence gate after Hilega WMA confirmation."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_INPUT = Path(
    "data/historical-evidence/"
    "hilega-wma-delayed-confirmation-2026-09-30-2026-10-01-v2"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/"
    "hilega-wma-one-minute-persistence-2026-09-30-2026-10-01-v1"
)


def as_float(value: Any) -> float:
    if value in (None, ""):
        raise ValueError("required numeric value is unavailable")
    return float(value)


def as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen:
                fields.append(field)
                seen.add(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def directional_gap(row: dict[str, Any], direction: str) -> float:
    ema = as_float(row["provisional_ema3_rsi"])
    wma = as_float(row["provisional_wma21_rsi"])
    if direction == "BULLISH":
        return ema - wma
    if direction == "BEARISH":
        return wma - ema
    raise ValueError(f"unsupported direction: {direction!r}")


def directional_ema_delta(
    armed: dict[str, Any],
    confirmation: dict[str, Any],
    direction: str,
) -> float:
    armed_ema = as_float(armed["provisional_ema3_rsi"])
    current_ema = as_float(confirmation["provisional_ema3_rsi"])
    if direction == "BULLISH":
        return current_ema - armed_ema
    if direction == "BEARISH":
        return armed_ema - current_ema
    raise ValueError(f"unsupported direction: {direction!r}")


def exact_next_minute(left: dict[str, Any], right: dict[str, Any]) -> bool:
    first = datetime.fromisoformat(str(left["minute_timestamp"]))
    second = datetime.fromisoformat(str(right["minute_timestamp"]))
    return (second - first).total_seconds() == 60.0


def evaluate_pair(
    armed: dict[str, Any],
    current: dict[str, Any],
    *,
    threshold: float,
) -> dict[str, Any]:
    direction = str(armed["direction"])
    maintained = as_float(current["directional_wma_change"]) >= threshold
    aligned = as_bool(current["full_directional_alignment"])
    ema_delta = directional_ema_delta(armed, current, direction)
    armed_gap = directional_gap(armed, direction)
    current_gap = directional_gap(current, direction)
    gap_delta = current_gap - armed_gap
    ema_continues = ema_delta >= 0.0
    gap_not_contracting = gap_delta >= 0.0
    passed = maintained and aligned and ema_continues and gap_not_contracting
    failed: list[str] = []
    if not maintained:
        failed.append("WMA_THRESHOLD_NOT_MAINTAINED")
    if not aligned:
        failed.append("RSI_EMA_WMA_NOT_ALIGNED")
    if not ema_continues:
        failed.append("EMA_NOT_CONTINUING")
    if not gap_not_contracting:
        failed.append("EMA_WMA_GAP_CONTRACTING")
    return {
        "trade_id": armed["trade_id"],
        "session_date": armed["session_date"],
        "direction": direction,
        "strategy_signal_timestamp": armed["strategy_signal_timestamp"],
        "armed_timestamp": armed["minute_timestamp"],
        "confirmation_timestamp": current["minute_timestamp"],
        "armed_close": as_float(armed["observed_close"]),
        "confirmation_close": as_float(current["observed_close"]),
        "armed_rsi9": as_float(armed["provisional_rsi9"]),
        "confirmation_rsi9": as_float(current["provisional_rsi9"]),
        "armed_ema3_rsi": as_float(armed["provisional_ema3_rsi"]),
        "confirmation_ema3_rsi": as_float(current["provisional_ema3_rsi"]),
        "armed_wma21_rsi": as_float(armed["provisional_wma21_rsi"]),
        "confirmation_wma21_rsi": as_float(current["provisional_wma21_rsi"]),
        "armed_directional_wma_change": as_float(
            armed["directional_wma_change"]
        ),
        "confirmation_directional_wma_change": as_float(
            current["directional_wma_change"]
        ),
        "threshold_maintained": maintained,
        "full_directional_alignment": aligned,
        "directional_ema_delta": ema_delta,
        "ema_continues": ema_continues,
        "armed_directional_gap": armed_gap,
        "confirmation_directional_gap": current_gap,
        "directional_gap_delta": gap_delta,
        "gap_not_contracting": gap_not_contracting,
        "persistence_passed": passed,
        "failure_reasons": "|".join(failed),
    }


def find_persistence(
    rows: list[dict[str, Any]], threshold: float
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    ordered = sorted(rows, key=lambda row: str(row["minute_timestamp"]))
    attempts: list[dict[str, Any]] = []
    for armed, current in zip(ordered, ordered[1:]):
        if as_float(armed["directional_wma_change"]) < threshold:
            continue
        if not exact_next_minute(armed, current):
            continue
        result = evaluate_pair(armed, current, threshold=threshold)
        attempts.append(result)
        if result["persistence_passed"]:
            return result, attempts
    return None, attempts


def directional_points(direction: str, entry: float, exit_price: float) -> float:
    return exit_price - entry if direction == "BULLISH" else entry - exit_price


def aggregate(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    selected = list(rows)
    accepted = [row for row in selected if row["persistence_decision"] == "ENTRY"]
    denied = [row for row in selected if row["persistence_decision"] == "NO_ENTRY"]
    return {
        "signals": len(selected),
        "persistence_entries": len(accepted),
        "denied": len(denied),
        "persistence_sum_points": sum(
            float(row["persistence_points"]) for row in accepted
        ),
        "accepted_positive": sum(float(row["persistence_points"]) > 0 for row in accepted),
        "accepted_negative": sum(float(row["persistence_points"]) < 0 for row in accepted),
        "denied_canonical_sum_points": sum(
            float(row["canonical_points"]) for row in denied
        ),
        "denied_positive": sum(float(row["canonical_points"]) > 0 for row in denied),
        "denied_negative": sum(float(row["canonical_points"]) < 0 for row in denied),
        "denied_plus20": sum(bool(row["canonical_reached_plus20"]) for row in denied),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--threshold", type=float, default=0.75)
    args = parser.parse_args()
    if args.threshold <= 0:
        raise SystemExit("STOP: threshold must be positive")

    summaries = read_csv(args.input_root / "trade-validation.csv")
    traces = read_csv(args.input_root / "minute-by-minute-wma.csv")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in traces:
        grouped[row["trade_id"]].append(row)

    comparison: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    for source in summaries:
        passed, trade_attempts = find_persistence(
            grouped.get(source["trade_id"], []), args.threshold
        )
        attempts.extend(trade_attempts)
        direction = source["direction"]
        exit_price = as_float(source["canonical_exit_price"])
        persistence_points = None
        if passed is not None:
            persistence_points = directional_points(
                direction, as_float(passed["confirmation_close"]), exit_price
            )
        comparison.append({
            "trade_id": source["trade_id"],
            "session_date": source["session_date"],
            "direction": direction,
            "strategy_signal_timestamp": source["strategy_signal_timestamp"],
            "canonical_exit_timestamp": source["canonical_exit_timestamp"],
            "canonical_points": as_float(source["canonical_points"]),
            "canonical_mfe_points": as_float(source["canonical_mfe_points"]),
            "canonical_reached_plus20": as_bool(
                source["canonical_reached_plus20"]
            ),
            "first_touch_decision": source["candidate_decision"],
            "first_touch_timestamp": source["first_wma_075_timestamp"],
            "first_touch_points": (
                None if source["delayed_entry_to_canonical_exit_points"] == ""
                else as_float(source["delayed_entry_to_canonical_exit_points"])
            ),
            "persistence_decision": "ENTRY" if passed else "NO_ENTRY",
            "persistence_entry_timestamp": (
                None if passed is None else passed["confirmation_timestamp"]
            ),
            "persistence_entry_price": (
                None if passed is None else passed["confirmation_close"]
            ),
            "persistence_points": persistence_points,
            "delta_vs_canonical": (
                None if persistence_points is None
                else persistence_points - as_float(source["canonical_points"])
            ),
            "attempt_count": len(trade_attempts),
        })

    args.output_root.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_root / "trade-comparison.csv", comparison)
    write_csv(args.output_root / "persistence-attempts.csv", attempts)
    by_date = {
        day: aggregate(row for row in comparison if row["session_date"] == day)
        for day in sorted({row["session_date"] for row in comparison})
    }
    report = {
        "model": "HILEGA_WMA_ONE_MINUTE_PERSISTENCE_V1",
        "rule": {
            "signal_source": "UNCHANGED_CANONICAL_HILEGA_STRATEGY",
            "arm": "DIRECTIONAL_WMA_CHANGE_GE_0_75",
            "confirmation": [
                "NEXT_COMPLETED_MINUTE_REMAINS_GE_0_75",
                "RSI_EMA_WMA_FULL_DIRECTIONAL_ALIGNMENT",
                "EMA_CONTINUES_IN_SIGNAL_DIRECTION",
                "DIRECTIONAL_EMA_WMA_GAP_DOES_NOT_CONTRACT",
            ],
            "failed_pair": "MAY_REARM_INSIDE_EXISTING_T10_WINDOW",
            "fill": "ACTUAL_PERSISTENCE_CANDLE_CLOSE",
        },
        "overall": aggregate(comparison),
        "by_date": by_date,
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
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    print("HILEGA WMA ONE-MINUTE PERSISTENCE")
    for row in comparison:
        print({
            "date": row["session_date"],
            "signal": str(row["strategy_signal_timestamp"])[11:16],
            "direction": row["direction"],
            "first_touch": row["first_touch_timestamp"],
            "persistence": row["persistence_entry_timestamp"],
            "decision": row["persistence_decision"],
            "canonical_points": row["canonical_points"],
            "first_touch_points": row["first_touch_points"],
            "persistence_points": row["persistence_points"],
            "plus20": row["canonical_reached_plus20"],
        })
    bullish_winners = [
        row for row in comparison
        if row["direction"] == "BULLISH"
        and row["persistence_points"] is not None
        and float(row["persistence_points"]) > 0
    ]
    if bullish_winners:
        best = max(bullish_winners, key=lambda row: float(row["persistence_points"]))
        print("BEST BULLISH PASS-ALL", best)
    else:
        print("BEST BULLISH PASS-ALL: none")
    print("OVERALL", report["overall"])
    print("BY DATE", report["by_date"])
    print("Output:", args.output_root / "report.json")
    print("Read only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

