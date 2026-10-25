#!/usr/bin/env python3
"""Explain ordered Hilega WMA-gap candidate failures for every session."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROOT = Path("data/historical-evidence/hilega-wma-gap-490-v1")
DIRECTIONS = ("BULLISH", "BEARISH")


def finite(value: Any) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty CSV: {path}")
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
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


def enrich_trade(
    raw: dict[str, str], top_thresholds: dict[str, float]
) -> dict[str, Any]:
    row: dict[str, Any] = dict(raw)
    for field in (
        "canonical_points", "first_touch_points", "candidate_points",
        "candidate_delta_vs_canonical", "mfe_points", "mae_points",
    ):
        row[field] = finite(row.get(field))
    canonical = float(row["canonical_points"])
    candidate = row["candidate_points"]
    accepted = row.get("candidate_decision") == "ENTRY" and candidate is not None
    denied = not accepted
    candidate_value = float(candidate) if accepted else 0.0
    delta = candidate_value - canonical
    direction = str(row["direction"])
    top_move = float(row["mfe_points"]) >= top_thresholds[direction]
    row.update({
        "candidate_policy_points": candidate_value,
        "policy_delta_vs_canonical": delta,
        "accepted_candidate_loss_points": (
            -candidate_value if accepted and candidate_value < 0 else 0.0
        ),
        "denied_winner_opportunity_points": (
            canonical if denied and canonical > 0 else 0.0
        ),
        "saved_denied_loss_points": (
            -canonical if denied and canonical < 0 else 0.0
        ),
        "adverse_entry_delay_cost_points": (
            -float(row["candidate_delta_vs_canonical"])
            if accepted
            and row["candidate_delta_vs_canonical"] is not None
            and float(row["candidate_delta_vs_canonical"]) < 0
            else 0.0
        ),
        "favourable_entry_timing_points": (
            float(row["candidate_delta_vs_canonical"])
            if accepted
            and row["candidate_delta_vs_canonical"] is not None
            and float(row["candidate_delta_vs_canonical"]) > 0
            else 0.0
        ),
        "candidate_accepted": accepted,
        "candidate_denied": denied,
        "canonical_reached_plus20": truthy(
            row.get("canonical_reached_plus20")
        ),
        "top_decile_move": top_move,
    })
    return row


def summarize(rows: Iterable[dict[str, Any]], direction: str) -> dict[str, Any]:
    selected = list(rows)
    canonical = sum(float(row["canonical_points"]) for row in selected)
    candidate = sum(float(row["candidate_policy_points"]) for row in selected)
    delta = candidate - canonical
    first_touch = sum(
        float(row["first_touch_points"])
        for row in selected if row["first_touch_points"] is not None
    )
    return {
        "session_date": selected[0]["session_date"],
        "evidence_block": selected[0].get("evidence_block"),
        "direction": direction,
        "signals": len(selected),
        "candidate_entries": sum(bool(row["candidate_accepted"]) for row in selected),
        "candidate_denied": sum(bool(row["candidate_denied"]) for row in selected),
        "canonical_points": canonical,
        "first_touch_points": first_touch,
        "candidate_points": candidate,
        "delta_vs_canonical": delta,
        "lost_vs_canonical_points": max(0.0, -delta),
        "improved_vs_canonical_points": max(0.0, delta),
        "accepted_winning_trades": sum(
            bool(row["candidate_accepted"])
            and float(row["candidate_policy_points"]) > 0
            for row in selected
        ),
        "accepted_losing_trades": sum(
            bool(row["candidate_accepted"])
            and float(row["candidate_policy_points"]) < 0
            for row in selected
        ),
        "accepted_candidate_loss_points": sum(
            float(row["accepted_candidate_loss_points"]) for row in selected
        ),
        "denied_losing_trades": sum(
            bool(row["candidate_denied"])
            and float(row["canonical_points"]) < 0
            for row in selected
        ),
        "saved_denied_loss_points": sum(
            float(row["saved_denied_loss_points"]) for row in selected
        ),
        "denied_winning_trades": sum(
            bool(row["candidate_denied"])
            and float(row["canonical_points"]) > 0
            for row in selected
        ),
        "denied_winner_opportunity_points": sum(
            float(row["denied_winner_opportunity_points"]) for row in selected
        ),
        "adverse_entry_delay_cost_points": sum(
            float(row["adverse_entry_delay_cost_points"]) for row in selected
        ),
        "favourable_entry_timing_points": sum(
            float(row["favourable_entry_timing_points"]) for row in selected
        ),
        "plus20_moves_destroyed": sum(
            bool(row["candidate_denied"])
            and bool(row["canonical_reached_plus20"])
            for row in selected
        ),
        "top_decile_moves_destroyed": sum(
            bool(row["candidate_denied"])
            and bool(row["top_decile_move"])
            for row in selected
        ),
        "negative_candidate_day": candidate < 0,
        "underperformed_canonical": delta < 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--worst-days", type=int, default=25)
    args = parser.parse_args()
    report_path = args.input_root / "report.json"
    if not report_path.is_file():
        raise FileNotFoundError(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    top_thresholds = {
        key: float(value)
        for key, value in report["development_top_decile_mfe_thresholds"].items()
    }
    trades = [
        enrich_trade(row, top_thresholds)
        for row in read_csv(args.input_root / "trade-results.csv")
    ]
    by_day: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        by_day[str(row["session_date"])].append(row)

    daily: list[dict[str, Any]] = []
    for day in sorted(by_day):
        rows = by_day[day]
        daily.append(summarize(rows, "ALL"))
        for direction in DIRECTIONS:
            subset = [row for row in rows if row["direction"] == direction]
            if subset:
                daily.append(summarize(subset, direction))

    failure_trades = [
        {
            "session_date": row["session_date"],
            "evidence_block": row.get("evidence_block"),
            "trade_id": row["trade_id"],
            "signal_timestamp": row["entry_timestamp"],
            "direction": row["direction"],
            "route": row["route"],
            "candidate_decision": row["candidate_decision"],
            "candidate_entry_timestamp": row.get("candidate_entry_timestamp"),
            "canonical_points": row["canonical_points"],
            "first_touch_points": row["first_touch_points"],
            "candidate_points": row["candidate_points"],
            "policy_delta_vs_canonical": row["policy_delta_vs_canonical"],
            "accepted_candidate_loss_points": row[
                "accepted_candidate_loss_points"
            ],
            "denied_winner_opportunity_points": row[
                "denied_winner_opportunity_points"
            ],
            "saved_denied_loss_points": row["saved_denied_loss_points"],
            "adverse_entry_delay_cost_points": row[
                "adverse_entry_delay_cost_points"
            ],
            "mfe_points": row["mfe_points"],
            "mae_points": row["mae_points"],
            "plus20": row["canonical_reached_plus20"],
            "top_decile": row["top_decile_move"],
        }
        for row in trades
        if float(row["accepted_candidate_loss_points"]) > 0
        or float(row["denied_winner_opportunity_points"]) > 0
        or float(row["adverse_entry_delay_cost_points"]) > 0
    ]
    write_csv(args.input_root / "daily-failure-summary.csv", daily)
    write_csv(args.input_root / "daily-failure-trades.csv", failure_trades)

    all_rows = [row for row in daily if row["direction"] == "ALL"]
    worst = sorted(
        all_rows,
        key=lambda row: (
            float(row["lost_vs_canonical_points"]),
            float(row["accepted_candidate_loss_points"]),
        ),
        reverse=True,
    )[:args.worst_days]
    summary = {
        "model": "HILEGA_WMA_GAP_DAILY_FAILURE_V1",
        "sessions": len(all_rows),
        "negative_candidate_days": sum(
            bool(row["negative_candidate_day"]) for row in all_rows
        ),
        "candidate_underperformed_canonical_days": sum(
            bool(row["underperformed_canonical"]) for row in all_rows
        ),
        "total_accepted_candidate_loss_points": sum(
            float(row["accepted_candidate_loss_points"]) for row in all_rows
        ),
        "total_denied_winner_opportunity_points": sum(
            float(row["denied_winner_opportunity_points"]) for row in all_rows
        ),
        "total_adverse_entry_delay_cost_points": sum(
            float(row["adverse_entry_delay_cost_points"]) for row in all_rows
        ),
        "total_lost_vs_canonical_on_underperforming_days": sum(
            float(row["lost_vs_canonical_points"]) for row in all_rows
        ),
        "warning": (
            "Loss categories overlap. Do not add realized loss, denied-winner "
            "opportunity and delay cost into one total. Policy-level lost-vs-"
            "canonical is the non-overlapping daily comparison."
        ),
        "safety": report["safety"],
    }
    (args.input_root / "daily-failure-report.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )

    print("HILEGA WMA-GAP DAILY FAILURE ANALYSIS")
    print("SUMMARY", summary)
    print("WORST DAYS VS CANONICAL")
    for row in worst:
        print({
            "date": row["session_date"],
            "block": row["evidence_block"],
            "canonical": round(float(row["canonical_points"]), 2),
            "candidate": round(float(row["candidate_points"]), 2),
            "lost_vs_canonical": round(
                float(row["lost_vs_canonical_points"]), 2
            ),
            "accepted_loss": round(
                float(row["accepted_candidate_loss_points"]), 2
            ),
            "denied_winner_loss": round(
                float(row["denied_winner_opportunity_points"]), 2
            ),
            "delay_cost": round(
                float(row["adverse_entry_delay_cost_points"]), 2
            ),
            "plus20_destroyed": row["plus20_moves_destroyed"],
            "top_decile_destroyed": row["top_decile_moves_destroyed"],
        })
    print("Output:", args.input_root / "daily-failure-summary.csv")
    print("Trades:", args.input_root / "daily-failure-trades.csv")
    print("Read only: live strategy, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

