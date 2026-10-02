#!/usr/bin/env python3
"""Map causal pre-entry/entry health labels to subsequent strategy points."""

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
    "midpoint-entry-health-490-v1/trade-health-features.csv"
)
DEFAULT_OUTPUT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-preentry-health-outcomes-490-v1"
)


def finite(value) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def health(row: dict, checkpoint: str) -> tuple[str, int | None]:
    di = finite(row.get(f"{checkpoint}_directional_di_spread"))
    edge = finite(row.get(f"{checkpoint}_combined_edge"))
    momentum = finite(row.get(f"{checkpoint}_price_momentum_support"))
    if None in (di, edge, momentum):
        return "UNAVAILABLE", None
    support = sum((di > 0, edge > 0, momentum > 0))
    return ("HEALTHY" if support >= 2 else "UNHEALTHY"), support


def profit_factor(points: list[float]) -> float | None:
    wins = sum(value for value in points if value > 0)
    losses = -sum(value for value in points if value < 0)
    if losses == 0:
        return None if wins else 0.0
    return wins / losses


def max_drawdown(rows: list[dict]) -> float:
    daily: dict[str, float] = defaultdict(float)
    for row in rows:
        value = finite(row.get("selected_exit_points"))
        if value is not None:
            daily[row["session_date"]] += value
    equity = peak = worst = 0.0
    for day in sorted(daily):
        equity += daily[day]
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def metric(rows: list[dict]) -> dict:
    points = [finite(row.get("selected_exit_points")) for row in rows]
    clean = [float(value) for value in points if value is not None]
    proved = sum(row.get("cohort") == "GOOD_PLUS20_PROVED" for row in rows)
    return {
        "entries": len(rows),
        "completed": len(clean),
        "plus20_proved": proved,
        "proof_rate_pct": 100.0 * proved / len(rows) if rows else None,
        "sum_points": sum(clean),
        "mean_points": statistics.mean(clean) if clean else None,
        "median_points": statistics.median(clean) if clean else None,
        "positive": sum(value > 0 for value in clean),
        "negative": sum(value < 0 for value in clean),
        "win_rate_pct": 100.0 * sum(value > 0 for value in clean) / len(clean) if clean else None,
        "profit_factor": profit_factor(clean),
        "max_drawdown_points": max_drawdown(rows),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    with args.input.open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    details = []
    for row in rows:
        detail = {key: row.get(key) for key in (
            "split", "segment", "session_date", "family", "direction",
            "entry_timestamp", "cohort", "selected_exit_policy",
            "selected_exit_timestamp", "selected_exit_points",
        )}
        for checkpoint in ("preentry", "entry"):
            label, support = health(row, checkpoint)
            detail[f"{checkpoint}_health"] = label
            detail[f"{checkpoint}_support_count"] = support
            for metric_name in (
                "directional_di_spread", "combined_edge",
                "price_momentum_support", "futures_vwap_support",
                "directional_volume_support", "ema_9_21_support",
                "macd_direction_support", "rsi14_support",
            ):
                detail[f"{checkpoint}_{metric_name}"] = row.get(
                    f"{checkpoint}_{metric_name}"
                )
        details.append(detail)

    report: dict[str, dict] = {}
    summary_rows = []
    for split in ("IS_FROZEN_FIRST_70", "OOS_FROZEN_LAST_30", "FORWARD_LATEST_10", "ALL_490"):
        members = rows if split == "ALL_490" else [row for row in rows if row["split"] == split]
        report[split] = {}
        for checkpoint in ("preentry", "entry"):
            report[split][checkpoint] = {}
            for label in ("HEALTHY", "UNHEALTHY", "UNAVAILABLE"):
                selected = [row for row in members if health(row, checkpoint)[0] == label]
                values = metric(selected)
                report[split][checkpoint][label] = values
                summary_rows.append({"split": split, "checkpoint": checkpoint,
                                     "health": label, **values})

    family_rows = []
    oos = [row for row in rows if row["split"] == "OOS_FROZEN_LAST_30"]
    for checkpoint in ("preentry", "entry"):
        groups = sorted({(row["family"], row["direction"]) for row in oos})
        for family, direction in groups:
            for label in ("HEALTHY", "UNHEALTHY", "UNAVAILABLE"):
                selected = [row for row in oos if row["family"] == family
                            and row["direction"] == direction
                            and health(row, checkpoint)[0] == label]
                family_rows.append({"split": "OOS_FROZEN_LAST_30",
                                    "checkpoint": checkpoint, "family": family,
                                    "direction": direction, "health": label,
                                    **metric(selected)})

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "trade-health-outcomes.csv", details)
    write_csv(args.output_dir / "health-summary.csv", summary_rows)
    write_csv(args.output_dir / "oos-family-direction.csv", family_rows)
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    for split in ("OOS_FROZEN_LAST_30", "FORWARD_LATEST_10", "ALL_490"):
        print("\n", split)
        for checkpoint in ("preentry", "entry"):
            print(checkpoint.upper())
            for label, values in report[split][checkpoint].items():
                print(" ", label, values)
    print("\nOutput:", args.output_dir / "report.json")
    print("Descriptive only: health labels do not block entries or alter exits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
