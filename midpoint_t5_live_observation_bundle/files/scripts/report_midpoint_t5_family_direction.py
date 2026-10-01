#!/usr/bin/env python3
"""Summarize frozen T+5 policies by family/direction and chronological split."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


DEFAULT_ROOT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-t5-initial-risk-policy-v1"
)
POLICIES = (
    "CURRENT_POLICY",
    "T5_TWO_OF_THREE_FAILURE",
    "T5_COMBINED_EDGE_FAILURE_ZERO",
)


def number(row: dict, name: str) -> float:
    value = row.get(name)
    return 0.0 if value in (None, "") else float(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_ROOT / "family-direction-breakdown.csv")
    parser.add_argument("--output", type=Path, default=DEFAULT_ROOT / "family-direction-validation.json")
    args = parser.parse_args()
    with args.input.open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    output: dict[str, dict] = {}
    for split in ("OOS_FROZEN_LAST_30", "FORWARD_LATEST_10", "ALL_490"):
        output[split] = {}
        keys = sorted({(r["family"], r["direction"]) for r in rows if r["split"] == split})
        for family, direction in keys:
            selected = {
                r["policy"]: r for r in rows
                if r["split"] == split and r["family"] == family
                and r["direction"] == direction and r["policy"] in POLICIES
            }
            baseline = selected.get("CURRENT_POLICY")
            if baseline is None:
                continue
            key = f"{family}|{direction}"
            output[split][key] = {}
            baseline_sum = number(baseline, "sum_points")
            for policy in POLICIES:
                row = selected.get(policy)
                if row is None:
                    continue
                output[split][key][policy] = {
                    "entries": int(number(row, "entries")),
                    "completed": int(number(row, "completed")),
                    "sum_points": round(number(row, "sum_points"), 4),
                    "mean_points": round(number(row, "mean_points"), 4),
                    "win_rate_pct": round(number(row, "win_rate_pct"), 4),
                    "profit_factor": round(number(row, "profit_factor"), 4),
                    "max_drawdown": round(number(row, "max_drawdown_points"), 4),
                    "delta_sum_vs_current": round(number(row, "sum_points") - baseline_sum, 4),
                    "improved": int(number(row, "improved")),
                    "harmed": int(number(row, "harmed")),
                }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    for split, groups in output.items():
        print("\n", split)
        for key, policies in groups.items():
            print(key)
            for policy, values in policies.items():
                print(" ", policy, values)
    print("\nOutput:", args.output)
    print("Read only: no live decision, audit, order or quantity changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
