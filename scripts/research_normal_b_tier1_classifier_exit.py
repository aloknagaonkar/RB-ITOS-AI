#!/usr/bin/env python3
"""Research exact NORMAL_B Tier-1 dual-failure classifier-close exit."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import statistics
from collections import defaultdict
from pathlib import Path


CURRENT = Path("scripts/backtest_midpoint_current_strategy.py")
V55 = Path("scripts/midpoint_v55_boundary_selection_replay.py")
V52 = Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
LIVE_AUDIT = Path("data/live-observation/midpoint-strategy-v1/audit.jsonl")
DEFAULT_OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "normal-b-tier1-classifier-exit-v1"
)
ENTRY_TYPES = {
    "B_ENTRY", "E_ENTRY", "C_ENTRY", "B_REARM_ENTRY", "E_REARM_ENTRY"
}


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def first(rows: list[dict], event_type: str):
    return next((row for row in rows if row.get("event_type") == event_type), None)


def analyze(rows: list[dict], source: str) -> list[dict]:
    indices = [i for i, row in enumerate(rows) if row.get("event_type") in ENTRY_TYPES]
    output = []
    for sequence, index in enumerate(indices):
        end = indices[sequence + 1] if sequence + 1 < len(indices) else len(rows)
        segment = rows[index:end]
        entry = rows[index]
        classifier = first(segment, "RUNNER_CLASSIFICATION")
        started = first(segment, "NORMAL_B_PROVED_STARTED")
        route = first(segment, "MANAGEMENT_ROUTE_SELECTED")
        current_exit = first(segment, "NORMAL_B_PROVED_EXIT_CANDIDATE")
        if current_exit is None:
            current_exit = first(segment, "STRUCTURAL_TERMINAL")
        if not classifier or classifier.get("result") != "NORMAL_B" or not started:
            continue
        classifier_evidence = classifier.get("evidence") or {}
        start_evidence = started.get("evidence") or {}
        mfe = start_evidence.get("mfe_points")
        dual_failure = (
            classifier_evidence.get("condition_progress_positive") is False
            and classifier_evidence.get("condition_vwap_change_positive") is False
        )
        tier1 = mfe is not None and float(mfe) <= 30.0
        eligible = dual_failure and tier1 and route is not None
        current_points = (
            float(current_exit["directional_points"])
            if current_exit and current_exit.get("directional_points") is not None
            else None
        )
        classifier_points = (
            float(route["directional_points"])
            if eligible and route.get("directional_points") is not None
            else None
        )
        output.append({
            "source": source,
            "session_date": entry.get("session_date"),
            "family": entry.get("family"),
            "direction": entry.get("direction"),
            "entry_timestamp": entry.get("event_timestamp"),
            "classifier_timestamp": classifier.get("event_timestamp"),
            "mfe_at_classifier": mfe,
            "progress_positive": classifier_evidence.get(
                "condition_progress_positive"
            ),
            "vwap_change_positive": classifier_evidence.get(
                "condition_vwap_change_positive"
            ),
            "eligible_tier1_dual_failure": eligible,
            "current_exit_timestamp": (
                current_exit.get("event_timestamp") if current_exit else None
            ),
            "current_exit_reason": current_exit.get("reason") if current_exit else None,
            "current_exit_points": current_points,
            "classifier_close_candidate_points": classifier_points,
            "candidate_delta": (
                classifier_points - current_points
                if classifier_points is not None and current_points is not None
                else None
            ),
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        })
    return output


def metric(rows: list[dict]) -> dict:
    eligible = [
        row for row in rows
        if row["eligible_tier1_dual_failure"]
        and row["current_exit_points"] is not None
        and row["classifier_close_candidate_points"] is not None
    ]
    current = [float(row["current_exit_points"]) for row in eligible]
    candidate = [float(row["classifier_close_candidate_points"]) for row in eligible]
    deltas = [new - old for old, new in zip(current, candidate)]
    return {
        "normal_b_trades": len(rows),
        "eligible": len(eligible),
        "current_sum": sum(current),
        "current_mean": statistics.mean(current) if current else None,
        "candidate_sum": sum(candidate),
        "candidate_mean": statistics.mean(candidate) if candidate else None,
        "delta_sum": sum(deltas),
        "improved": sum(value > 0 for value in deltas),
        "equal": sum(value == 0 for value in deltas),
        "harmed": sum(value < 0 for value in deltas),
        "current_positive": sum(value > 0 for value in current),
        "candidate_positive": sum(value > 0 for value in candidate),
    }


def grouped(rows: list[dict], field: str) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    return {key: metric(value) for key, value in sorted(groups.items())}


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--skip-live-audit", action="store_true")
    arguments = parser.parse_args()
    current = import_module(CURRENT, "tier1_exit_current")
    v55 = import_module(V55, "tier1_exit_v55")
    v52 = import_module(V52, "tier1_exit_v52")
    canon = import_module(CANON, "tier1_exit_canon")
    rows = []
    sessions = 0
    for block in v52.BLOCKS:
        underlying, futures, _ = v55.load_block(block, v52, canon)
        for day in sorted(set(underlying).intersection(futures)):
            sessions += 1
            audit = current.replay_session(day, underlying[day], futures[day])
            rows.extend(analyze(audit, block["name"]))
    live_rows = [] if arguments.skip_live_audit else analyze(
        load_jsonl(LIVE_AUDIT), "LIVE_AUDIT"
    )
    report = {
        "model": "NORMAL_B_TIER1_DUAL_FAILURE_CLASSIFIER_EXIT_V1",
        "historical_sessions": sessions,
        "rule": (
            "At exact proof+10 NORMAL_B classification, if existing Tier-1 "
            "MFE <= 30 and both runner checks are false, value an exit at the "
            "completed classifier candle close."
        ),
        "historical": metric(rows),
        "historical_by_family": grouped(rows, "family"),
        "historical_by_source": grouped(rows, "source"),
        "live_audit": metric(live_rows),
        "safety": {
            "research_only": True,
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        },
    }
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(arguments.output_dir / "historical-trades.csv", rows)
    write_csv(arguments.output_dir / "live-audit-trades.csv", live_rows)
    (arguments.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print("HISTORICAL", report["historical"])
    print("BY FAMILY", report["historical_by_family"])
    print("LIVE", report["live_audit"])
    for row in live_rows:
        if row["eligible_tier1_dual_failure"]:
            print("LIVE ELIGIBLE", row)
    print("Output:", arguments.output_dir / "report.json")
    print("Research only: live decisions, exits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
