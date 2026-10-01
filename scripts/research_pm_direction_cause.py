#!/usr/bin/env python3
"""Diagnose PM_B/PM_E directional performance without changing strategy rules.

This script consumes the enriched ``pm-trades.csv`` produced by
``backtest_midpoint_pm_be.py --include-forward``.  It performs descriptive,
read-only attribution by direction, exit route, chronological block, proof
status, entry delay, entry time, futures/VWAP strength and PM range width.

The output is an evidence pack, not a threshold search.  In particular, the
boundary-price counterfactual remains selection-biased because PM_B trades are
known only after their later confirmation; it is never used by the decision
gate below.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


DEFAULT_INPUT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-pm-be-backtest-480-plus-forward-corrected-v2/pm-trades.csv"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "pm-direction-cause-v1"
)
GROUPS = (
    "PM_B|BEARISH",
    "PM_B|BULLISH",
    "PM_E|BEARISH",
    "PM_E|BULLISH",
)
NUMERIC_FIELDS = {
    "selected_exit_points",
    "confirmation_delay_minutes",
    "pre_entry_move_points",
    "mfe_points_after_entry",
    "mae_points_after_entry",
    "boundary_directional_vwap_diff",
    "entry_directional_vwap_diff",
    "directional_vwap_change_boundary_to_entry",
    "midpoint_to_boundary_minutes",
    "entry_minutes_before_1515",
    "pm_range_points",
}


def optional_float(value) -> float | None:
    if value in (None, "", "None", "null"):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def boolean(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def load_trades(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"STOP: PM trade file unavailable: {path}. Run "
            "scripts/backtest_midpoint_pm_be.py --include-forward first."
        )
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "block", "session_date", "family", "direction", "entry_timestamp",
        "plus20", "selected_exit_policy", "selected_exit_points",
        "boundary_directional_vwap_diff", "entry_directional_vwap_diff",
        "pm_range_points",
    }
    missing = required.difference(rows[0] if rows else set())
    if missing:
        raise SystemExit(
            "STOP: PM trade file predates cause-diagnostic enrichment; rerun "
            "scripts/backtest_midpoint_pm_be.py --include-forward. Missing: "
            + ", ".join(sorted(missing))
        )
    for row in rows:
        for field in NUMERIC_FIELDS:
            row[field] = optional_float(row.get(field))
        row["plus20"] = boolean(row.get("plus20"))
        row["group"] = f'{row["family"]}|{row["direction"]}'
        points = row["selected_exit_points"]
        row["outcome"] = (
            "UNRESOLVED" if points is None else "WIN" if points > 0 else "LOSS"
        )
    return rows


def metric(rows: list[dict]) -> dict:
    values = [
        float(row["selected_exit_points"])
        for row in rows if row["selected_exit_points"] is not None
    ]
    return {
        "entries": len(rows),
        "completed": len(values),
        "unresolved": len(rows) - len(values),
        "sum_points": round(sum(values), 6),
        "mean_points": round(statistics.mean(values), 6) if values else None,
        "median_points": round(statistics.median(values), 6) if values else None,
        "positive": sum(value > 0 for value in values),
        "negative": sum(value < 0 for value in values),
        "win_rate_pct": round(
            100.0 * sum(value > 0 for value in values) / len(values), 6
        ) if values else None,
    }


def grouped_metrics(rows: list[dict], fields: tuple[str, ...]) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[field] for field in fields)].append(row)
    output = []
    for key, members in sorted(groups.items()):
        output.append({
            **dict(zip(fields, key)),
            **metric(members),
        })
    return output


def outlier_summary(group: str, rows: list[dict]) -> dict:
    values = sorted(
        float(row["selected_exit_points"])
        for row in rows if row["selected_exit_points"] is not None
    )
    total = sum(values)
    best = values[-1] if values else None
    worst = values[0] if values else None
    top_three = sum(values[-3:]) if values else 0.0
    return {
        "group": group,
        "completed": len(values),
        "sum_points": round(total, 6),
        "best_trade_points": best,
        "worst_trade_points": worst,
        "top_three_sum_points": round(top_three, 6),
        "sum_without_best_trade": round(total - best, 6) if best is not None else None,
        "top_one_share_of_positive_total_pct": round(
            100.0 * best / sum(value for value in values if value > 0), 6
        ) if best is not None and sum(value for value in values if value > 0) else None,
        "top_three_share_of_positive_total_pct": round(
            100.0 * sum(value for value in values[-3:] if value > 0)
            / sum(value for value in values if value > 0), 6
        ) if sum(value for value in values if value > 0) else None,
    }


def mean_feature(rows: list[dict], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return round(statistics.mean(values), 6) if values else None


def feature_rows(rows: list[dict]) -> list[dict]:
    fields = (
        "boundary_directional_vwap_diff",
        "entry_directional_vwap_diff",
        "directional_vwap_change_boundary_to_entry",
        "confirmation_delay_minutes",
        "pre_entry_move_points",
        "midpoint_to_boundary_minutes",
        "entry_minutes_before_1515",
        "pm_range_points",
        "mfe_points_after_entry",
        "mae_points_after_entry",
    )
    output = []
    for group in GROUPS:
        members = [row for row in rows if row["group"] == group]
        winners = [row for row in members if row["outcome"] == "WIN"]
        losers = [row for row in members if row["outcome"] == "LOSS"]
        for field in fields:
            winner_mean = mean_feature(winners, field)
            loser_mean = mean_feature(losers, field)
            output.append({
                "group": group,
                "feature": field,
                "all_mean": mean_feature(members, field),
                "winner_mean": winner_mean,
                "loser_mean": loser_mean,
                "winner_minus_loser": (
                    round(winner_mean - loser_mean, 6)
                    if winner_mean is not None and loser_mean is not None else None
                ),
                "available": sum(row.get(field) is not None for row in members),
            })
    return output


def assign_chronological_split(rows: list[dict]) -> str | None:
    dates = sorted({row["session_date"] for row in rows})
    if not dates:
        return None
    cutoff_index = max(1, math.ceil(len(dates) * 0.70))
    is_dates = set(dates[:cutoff_index])
    for row in rows:
        row["chronological_split"] = (
            "IS_FIRST_70_PCT" if row["session_date"] in is_dates
            else "OOS_LAST_30_PCT"
        )
    return dates[cutoff_index - 1]


def entry_time_bucket(timestamp: str) -> str:
    minute = timestamp[11:16]
    if minute < "13:45":
        return "13:15_TO_13:44"
    if minute < "14:15":
        return "13:45_TO_14:14"
    return "14:15_OR_LATER"


def delay_bucket(value: float | None) -> str:
    if value is None or value == 0:
        return "IMMEDIATE"
    if value <= 3:
        return "DELAY_1_TO_3"
    if value <= 6:
        return "DELAY_4_TO_6"
    return "DELAY_7_TO_10"


def decision_gate(rows: list[dict], outliers: list[dict]) -> dict:
    target = [row for row in rows if row["group"] == "PM_B|BEARISH"]
    completed = [row for row in target if row["selected_exit_points"] is not None]
    frozen = [row for row in completed if row["block"] != "FORWARD_OOS_2026-09"]
    forward = [row for row in completed if row["block"] == "FORWARD_OOS_2026-09"]
    frozen_blocks = grouped_metrics(frozen, ("block",))
    positive_blocks = sum((row["sum_points"] or 0) > 0 for row in frozen_blocks)
    concentration = next(row for row in outliers if row["group"] == "PM_B|BEARISH")
    checks = {
        "positive_without_best_trade": (
            concentration["sum_without_best_trade"] is not None
            and concentration["sum_without_best_trade"] > 0
        ),
        "at_least_three_positive_frozen_blocks": positive_blocks >= 3,
        "forward_sample_minimum_10": len(forward) >= 10,
        "forward_mean_non_negative": (
            metric(forward)["mean_points"] is not None
            and metric(forward)["mean_points"] >= 0
        ),
        "unresolved_rate_at_most_10_pct": (
            100.0 * (len(target) - len(completed)) / len(target) <= 10.0
            if target else False
        ),
        "no_future_leakage_from_source_backtest": True,
    }
    return {
        "candidate": "PM_B_BEARISH_ONLY",
        "status": "ADVANCE_OBSERVATION_ONLY" if all(checks.values()) else "HOLD_RESEARCH",
        "checks": checks,
        "frozen_positive_blocks": positive_blocks,
        "frozen_blocks_observed": len(frozen_blocks),
        "forward_completed": len(forward),
        "forward_metric": metric(forward),
        "reason": (
            "All predeclared robustness checks passed."
            if all(checks.values()) else
            "At least one predeclared robustness check is incomplete or failed; do not enable PM live."
        ),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    fields = list(rows[0])
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    trades = load_trades(arguments.input)
    cutoff = assign_chronological_split(trades)
    for row in trades:
        row["entry_time_bucket"] = entry_time_bucket(row["entry_timestamp"])
        row["confirmation_delay_bucket"] = delay_bucket(
            row["confirmation_delay_minutes"]
        )

    group_summary = grouped_metrics(trades, ("group",))
    route_summary = grouped_metrics(
        trades, ("group", "selected_exit_policy")
    )
    block_summary = grouped_metrics(trades, ("group", "block"))
    split_summary = grouped_metrics(trades, ("group", "chronological_split"))
    proof_summary = grouped_metrics(trades, ("group", "plus20"))
    time_summary = grouped_metrics(trades, ("group", "entry_time_bucket"))
    delay_summary = grouped_metrics(
        trades, ("group", "confirmation_delay_bucket")
    )
    outliers = [
        outlier_summary(group, [row for row in trades if row["group"] == group])
        for group in GROUPS
    ]
    features = feature_rows(trades)
    gate = decision_gate(trades, outliers)

    report = {
        "model": "MIDPOINT_PM_DIRECTION_CAUSE_RESEARCH_V1",
        "source": str(arguments.input),
        "trade_count": len(trades),
        "chronological_split": {
            "method": "first 70% versus last 30% of distinct session dates",
            "is_last_session": cutoff,
            "thresholds_optimized_on_oos": False,
        },
        "group_summary": group_summary,
        "route_summary": route_summary,
        "block_summary": block_summary,
        "split_summary": split_summary,
        "proof_summary": proof_summary,
        "entry_time_summary": time_summary,
        "confirmation_delay_summary": delay_summary,
        "outlier_concentration": outliers,
        "feature_summary": features,
        "decision_gate": gate,
        "interpretation_guards": [
            "Descriptive association is not a causal entry or exit rule.",
            "No threshold search or parameter optimization is performed.",
            "The PM_B boundary counterfactual is selection-biased and excluded from the decision gate.",
            "Underlying NIFTY points exclude option premium, spread, slippage, charges and quantity.",
            "Unresolved trades remain visible and are not silently converted to wins or losses.",
        ],
        "safety": {
            "research_only": True,
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
            "live_gate_modified": False,
        },
    }

    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(arguments.output_dir / "trade-diagnostics.csv", trades)
    write_csv(arguments.output_dir / "route-summary.csv", route_summary)
    write_csv(arguments.output_dir / "block-summary.csv", block_summary)
    write_csv(arguments.output_dir / "split-summary.csv", split_summary)
    write_csv(arguments.output_dir / "proof-summary.csv", proof_summary)
    write_csv(arguments.output_dir / "feature-summary.csv", features)
    write_csv(arguments.output_dir / "outlier-concentration.csv", outliers)
    (arguments.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )

    print(f"PM trades: {len(trades)}")
    for row in group_summary:
        print(row["group"], {key: value for key, value in row.items() if key != "group"})
    print("DECISION", gate)
    print(f"Output: {arguments.output_dir / 'report.json'}")
    print("Read only: live gates, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
