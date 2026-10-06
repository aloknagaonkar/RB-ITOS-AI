#!/usr/bin/env python3
"""Compare WMA-gap persistence with causal first-touch entry candidates.

Research only. Canonical Hilega signals/exits are unchanged. The first observed
minute compares against the completed signal-bar indicator snapshot; later
minutes compare against the immediately preceding observed one-minute state.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any

FROZEN = Path("data/historical-evidence/hilega-wma-gap-490-v1")
FORWARD = Path("data/historical-evidence/hilega-wma-gap-forward-confirmation-v1")
OUTPUT = Path("data/historical-evidence/hilega-wma-gap-first-touch-v1")


def rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or not path.stat().st_size:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def directional_gap(row: dict[str, Any], direction: str, *, reference: bool = False) -> float | None:
    prefix = "reference" if reference else "provisional"
    ema = number(row.get(f"{prefix}_ema3_rsi"))
    wma = number(row.get(f"{prefix}_wma21_rsi"))
    if ema is None or wma is None:
        return None
    return ema - wma if direction == "BULLISH" else wma - ema


def directional_ema_delta(current: dict[str, Any], previous: dict[str, Any] | None,
                          direction: str) -> float | None:
    now = number(current.get("provisional_ema3_rsi"))
    before = number((previous or {}).get("provisional_ema3_rsi"))
    if previous is None:
        before = number(current.get("reference_ema3_rsi"))
    if now is None or before is None:
        return None
    raw = now - before
    return raw if direction == "BULLISH" else -raw


def first_touch(trace: list[dict[str, Any]], threshold: float) -> dict[str, Any] | None:
    ordered = sorted(trace, key=lambda row: str(row.get("minute_timestamp") or ""))
    previous: dict[str, Any] | None = None
    for current in ordered:
        if not truthy(current.get("within_confirmation_window")):
            previous = current
            continue
        direction = str(current.get("direction") or "")
        strength = number(current.get("directional_wma_change"))
        current_gap = directional_gap(current, direction)
        previous_gap = (
            directional_gap(previous, direction) if previous is not None
            else directional_gap(current, direction, reference=True)
        )
        gap_delta = (
            None if current_gap is None or previous_gap is None
            else current_gap - previous_gap
        )
        ema_delta = directional_ema_delta(current, previous, direction)
        gates = {
            "wma_threshold": strength is not None and strength >= threshold,
            "gap_positive": current_gap is not None and current_gap > 0,
            "gap_expanding": gap_delta is not None and gap_delta > 0,
            "ema_continuing": ema_delta is not None and ema_delta > 0,
            "aligned": truthy(current.get("full_directional_alignment")),
        }
        if all(gates.values()):
            return {
                **current,
                "policy_threshold": threshold,
                "previous_directional_gap": previous_gap,
                "current_directional_gap": current_gap,
                "directional_gap_delta": gap_delta,
                "directional_ema_delta": ema_delta,
                "comparison_source": (
                    "PRIOR_OBSERVED_1M" if previous is not None
                    else "COMPLETED_SIGNAL_BAR_REFERENCE"
                ),
                **gates,
            }
        previous = current
    return None


def points(direction: str, entry: float, exit_price: float) -> float:
    return exit_price - entry if direction == "BULLISH" else entry - exit_price


def metrics(records: list[dict[str, Any]], field: str, policy: str) -> dict[str, Any]:
    entered = [row for row in records if row.get(field) is not None]
    values = [float(row[field]) for row in entered]
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value < 0)
    denied = [row for row in records if row.get(field) is None]
    return {
        "policy": policy,
        "signals": len(records),
        "entries": len(entered),
        "denied": len(denied),
        "winning_trades": sum(value > 0 for value in values),
        "losing_trades": sum(value < 0 for value in values),
        "total_points": sum(values),
        "mean_points": fmean(values) if values else None,
        "profit_factor": gains / losses if losses else None,
        "denied_canonical_winners": sum(float(row["canonical_points"]) > 0 for row in denied),
        "denied_canonical_winner_points": sum(
            float(row["canonical_points"]) for row in denied
            if float(row["canonical_points"]) > 0
        ),
        "denied_canonical_losses": sum(float(row["canonical_points"]) < 0 for row in denied),
        "saved_denied_loss_points": -sum(
            float(row["canonical_points"]) for row in denied
            if float(row["canonical_points"]) < 0
        ),
        "plus20_moves_destroyed": sum(
            truthy(row.get("canonical_reached_plus20") or row.get("reached_plus20"))
            for row in denied
        ),
    }


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in records:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def load_evidence(roots: list[Path]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    trades: list[dict[str, str]] = []
    timeline: list[dict[str, str]] = []
    seen: set[str] = set()
    for root_index, root in enumerate(roots):
        cohort = "FROZEN_490" if root_index == 0 else "NEW_FORWARD_CONFIRMATION"
        for trade in rows(root / "trade-results.csv"):
            trade_id = str(trade.get("trade_id") or "")
            if trade_id and trade_id not in seen:
                trade["_evidence_cohort"] = cohort
                trades.append(trade)
                seen.add(trade_id)
        timeline.extend(rows(root / "candidate-timeline.csv"))
    return trades, timeline


def run(frozen: Path, forward: Path, output: Path) -> dict[str, Any]:
    trades, timeline = load_evidence([frozen, forward])
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in timeline:
        grouped[str(row.get("trade_id") or "")].append(row)
    comparisons: list[dict[str, Any]] = []
    for trade in trades:
        trade_id = str(trade["trade_id"])
        direction = str(trade["direction"])
        exit_price = number(trade.get("exit_price"))
        canonical = number(trade.get("canonical_points") or trade.get("captured_points"))
        if exit_price is None or canonical is None:
            continue
        result: dict[str, Any] = {
            "trade_id": trade_id,
            "session_date": trade.get("session_date"),
            "evidence_block": (
                trade.get("_evidence_cohort") or trade.get("evidence_block")
                or trade.get("split") or "FROZEN_490"
            ),
            "direction": direction,
            "signal_timestamp": trade.get("entry_timestamp"),
            "exit_timestamp": trade.get("exit_timestamp"),
            "canonical_points": canonical,
            "canonical_reached_plus20": trade.get("canonical_reached_plus20") or trade.get("reached_plus20"),
            "current_persistence_points": number(trade.get("candidate_points")),
        }
        for threshold, name in ((.75, "first_touch_075"), (1.0, "first_touch_100")):
            touch = first_touch(grouped.get(trade_id, []), threshold)
            result[f"{name}_timestamp"] = None if touch is None else touch.get("minute_timestamp")
            result[f"{name}_comparison_source"] = None if touch is None else touch.get("comparison_source")
            result[f"{name}_wma_strength"] = None if touch is None else touch.get("directional_wma_change")
            result[f"{name}_gap"] = None if touch is None else touch.get("current_directional_gap")
            result[f"{name}_gap_delta"] = None if touch is None else touch.get("directional_gap_delta")
            result[f"{name}_ema_delta"] = None if touch is None else touch.get("directional_ema_delta")
            result[f"{name}_points"] = (
                None if touch is None
                else points(direction, float(touch["observed_close"]), exit_price)
            )
        comparisons.append(result)

    policies = (
        ("current_persistence_points", "CURRENT_TWO_MINUTE_PERSISTENCE"),
        ("first_touch_075_points", "FIRST_TOUCH_GE_0_75"),
        ("first_touch_100_points", "FIRST_TOUCH_GE_1_00"),
    )
    headline: list[dict[str, Any]] = []
    for cohort, selected in (
        ("ALL", comparisons),
        ("FROZEN", [row for row in comparisons if row["evidence_block"] != "NEW_FORWARD_CONFIRMATION"]),
        ("FORWARD", [row for row in comparisons if row["evidence_block"] == "NEW_FORWARD_CONFIRMATION"]),
    ):
        for direction in ("ALL", "BULLISH", "BEARISH"):
            directional = selected if direction == "ALL" else [row for row in selected if row["direction"] == direction]
            for field, policy in policies:
                headline.append({"cohort": cohort, "direction": direction, **metrics(directional, field, policy)})

    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "trade-comparison.csv", comparisons)
    write_csv(output / "headline.csv", headline)
    report = {
        "model": "HILEGA_WMA_GAP_FIRST_TOUCH_RESEARCH_V1",
        "rules": {
            "baseline": "completed signal-bar snapshot on first observed minute; previous observed 1m thereafter",
            "common": "canonical signal + directional WMA threshold + positive expanding directional EMA3-WMA21 gap + directional EMA3 continuation + RSI9/EMA3/WMA21 alignment",
            "policies": [policy for _, policy in policies],
            "timeout_minutes": 10,
            "exit": "unchanged canonical exit",
        },
        "trades": len(comparisons),
        "headline": headline,
        "observation_only": True,
        "execution_enabled": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-root", type=Path, default=FROZEN)
    parser.add_argument("--forward-root", type=Path, default=FORWARD)
    parser.add_argument("--output-root", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = run(args.frozen_root, args.forward_root, args.output_root)
    print("HILEGA WMA-GAP FIRST-TOUCH RESEARCH", report["trades"], "trades")
    for row in report["headline"]:
        if row["cohort"] in {"FROZEN", "FORWARD"} and row["direction"] in {"ALL", "BULLISH", "BEARISH"}:
            print(row)
    print("Output:", args.output_root / "report.json")
    print("Read only: live strategy, orders, quantity and frozen evidence untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
