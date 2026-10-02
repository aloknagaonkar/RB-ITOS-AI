#!/usr/bin/env python3
"""Causal initial-risk research for the Midpoint B/E/C strategy.

This runner is deliberately separate from the live coordinator.  It evaluates
four standalone exits only while a trade is causally unproved, preserves the
current proved-runner result, and enforces a chronological 70/30 development /
OOS workflow.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


CURRENT = Path("scripts/backtest_midpoint_current_strategy.py")
V55 = Path("scripts/midpoint_v55_boundary_selection_replay.py")
V52 = Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
DEFAULT_OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-initial-risk-v1"
)
POLICIES = {
    "BOUNDARY_RECAPTURE": {
        "rule": "first completed close back inside original boundary",
    },
    "FIXED_CLOSE_LOSS_15": {
        "rule": "first completed close at directional points <= -15.00",
    },
    "BOUNDARY_VWAP_ZERO_FAILURE": {
        "rule": (
            "boundary recapture and futures-minus-VWAP sign reversal on the "
            "same completed minute"
        ),
    },
    "INACTIVITY_12M_NO_PLUS10": {
        "rule": (
            "at exact entry+12 completed close, running intrabar MFE < +10"
        ),
    },
}
AMBIGUITY_CHOICES = {"proof-first", "stop-first"}
SAFETY = {
    "observation_only": True,
    "execution_enabled": False,
    "paper_order_enabled": False,
    "quantity": None,
    "order_sent": False,
}


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def directional(direction: str, entry: float, price: float) -> float:
    return price - entry if direction == "BULLISH" else entry - price


def script_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_universe():
    current = import_module(CURRENT, "initial_risk_current")
    v55 = import_module(V55, "initial_risk_v55")
    v52 = import_module(V52, "initial_risk_v52")
    canon = import_module(CANON, "initial_risk_canon")
    sessions = []
    for block in v52.BLOCKS:
        underlying, futures, _ = v55.load_block(block, v52, canon)
        for day in sorted(set(underlying).intersection(futures)):
            sessions.append({
                "session_date": day,
                "block": block["name"],
                "underlying": underlying[day],
                "futures": futures[day],
            })
    sessions.sort(key=lambda row: row["session_date"])
    dates = [row["session_date"] for row in sessions]
    if len(dates) != 480 or len(set(dates)) != 480:
        raise SystemExit(
            f"STOP: expected 480 unique sessions, found {len(dates)} "
            f"({len(set(dates))} unique)"
        )
    split = int(len(sessions) * 0.70)
    if split != 336:
        raise AssertionError(f"unexpected chronological split index {split}")
    return current, sessions, split


def segment_entries(rows: list[dict]) -> list[tuple[dict, list[dict]]]:
    indices = [
        index for index, row in enumerate(rows)
        if row.get("event_type") in {"B_ENTRY", "E_ENTRY", "C_ENTRY"}
    ]
    output = []
    for sequence, index in enumerate(indices):
        end = indices[sequence + 1] if sequence + 1 < len(indices) else len(rows)
        output.append((rows[index], rows[index:end]))
    return output


def cohort(trade: dict, segment: list[dict]) -> str:
    if trade["status"] == "UNRESOLVED":
        return "SESSION_UNRESOLVED"
    if not trade["plus20"]:
        return "UNPROVED"
    if trade["classifier_unavailable"] or not trade["classifier_timestamp"]:
        return "PROVED_CLASSIFIER_MISSING"
    if trade["selected_exit_policy"] == "STRUCTURAL_BASELINE":
        return "PROVED_CANDIDATE_NOT_TRIGGERED"
    return "PROVED_CANDIDATE_MANAGED"


def boundary_recaptured(direction: str, close: float, boundary: float) -> bool:
    return close >= boundary if direction == "BEARISH" else close <= boundary


def running_excursion(
    direction: str,
    entry_price: float,
    prior: float,
    row: dict,
) -> float:
    if direction == "BULLISH":
        favorable = float(row["high"]) - entry_price
    else:
        favorable = entry_price - float(row["low"])
    return max(prior, favorable)


def candidate_signal(
    policy: str,
    *,
    direction: str,
    entry_price: float,
    boundary: float,
    close: float,
    running_mfe: float,
    timestamp: datetime,
    entry_timestamp: datetime,
    future: dict | None,
) -> tuple[bool, str]:
    points = directional(direction, entry_price, close)
    recaptured = boundary_recaptured(direction, close, boundary)
    if policy == "BOUNDARY_RECAPTURE":
        return recaptured, "BOUNDARY_RECAPTURE_CLOSE"
    if policy == "FIXED_CLOSE_LOSS_15":
        return points <= -15.0, "FIXED_CLOSE_LOSS_15"
    if policy == "BOUNDARY_VWAP_ZERO_FAILURE":
        if future is None:
            return False, "FUTURES_MINUTE_UNAVAILABLE"
        raw_diff = float(future["close"]) - float(future["vwap"])
        failed = raw_diff >= 0.0 if direction == "BEARISH" else raw_diff <= 0.0
        return recaptured and failed, "BOUNDARY_AND_VWAP_ZERO_FAILURE"
    if policy == "INACTIVITY_12M_NO_PLUS10":
        due = entry_timestamp + timedelta(minutes=12)
        return timestamp == due and running_mfe < 10.0, "ENTRY_PLUS12_NO_PLUS10"
    raise AssertionError(policy)


def evaluate_policy(
    policy: str,
    *,
    trade: dict,
    underlying: dict[str, dict],
    futures: dict[str, dict],
) -> dict:
    entry_at = parse_dt(trade["entry_timestamp"])
    proof_at = parse_dt(trade["plus20_timestamp"]) if trade["plus20_timestamp"] else None
    original_exit_at = (
        parse_dt(trade["selected_exit_timestamp"])
        if trade["selected_exit_timestamp"] else None
    )
    direction = trade["direction"]
    entry_price = float(trade["entry_price"])
    boundary = float(trade["original_boundary"])
    running_mfe = 0.0
    trigger = None
    ambiguity = False
    missing_exact_minute = False
    due = entry_at + timedelta(minutes=12)

    timestamps = sorted(underlying, key=parse_dt)
    for timestamp_text in timestamps:
        timestamp = parse_dt(timestamp_text)
        if timestamp <= entry_at:
            continue
        if original_exit_at is not None and timestamp > original_exit_at:
            break
        if proof_at is not None and timestamp > proof_at:
            break
        row = underlying[timestamp_text]
        running_mfe = running_excursion(
            direction, entry_price, running_mfe, row
        )
        signal, reason = candidate_signal(
            policy,
            direction=direction,
            entry_price=entry_price,
            boundary=boundary,
            close=float(row["close"]),
            running_mfe=running_mfe,
            timestamp=timestamp,
            entry_timestamp=entry_at,
            future=futures.get(timestamp_text),
        )
        if signal:
            trigger = {
                "timestamp": timestamp_text,
                "price": float(row["close"]),
                "points": directional(direction, entry_price, float(row["close"])),
                "reason": reason,
                "running_mfe": running_mfe,
            }
            ambiguity = proof_at is not None and timestamp == proof_at
            break

    if policy == "INACTIVITY_12M_NO_PLUS10":
        due_text = due.isoformat()
        if (
            (original_exit_at is None or due <= original_exit_at)
            and (proof_at is None or due <= proof_at)
            and due_text not in underlying
        ):
            missing_exact_minute = True

    original_points = trade["selected_exit_points"]
    stop_points = trigger["points"] if trigger else original_points
    proof_first_points = original_points if ambiguity else stop_points
    stop_first_points = stop_points
    return {
        "policy": policy,
        "candidate_triggered": trigger is not None,
        "candidate_timestamp": trigger["timestamp"] if trigger else "",
        "candidate_price": trigger["price"] if trigger else None,
        "candidate_points": trigger["points"] if trigger else None,
        "candidate_reason": trigger["reason"] if trigger else "",
        "running_mfe_at_trigger": trigger["running_mfe"] if trigger else None,
        "chronology_status": (
            "SIMULTANEOUS_PROOF_STOP_AMBIGUITY"
            if ambiguity else "CAUSAL"
        ),
        "missing_exact_minute": missing_exact_minute,
        "proof_first_points": proof_first_points,
        "stop_first_points": stop_first_points,
    }


def reconstruct_block(current, source_sessions: list[dict]) -> list[dict]:
    output = []
    for session in source_sessions:
        day = session["session_date"]
        audit = current.replay_session(day, session["underlying"], session["futures"])
        trades = current.reconstruct_session(
            block=session["block"],
            session_date=day,
            rows=audit,
            underlying=session["underlying"],
        )
        segments = segment_entries(audit)
        segment_by_key = {
            (entry["event_timestamp"], entry["family"]): segment
            for entry, segment in segments
        }
        for trade in trades:
            key = (trade["entry_timestamp"], trade["family"])
            segment = segment_by_key.get(key)
            if segment is None:
                raise AssertionError(f"{day} cannot align trade {key}")
            base = {
                **trade,
                "cohort": cohort(trade, segment),
            }
            for policy in POLICIES:
                output.append({
                    **base,
                    **evaluate_policy(
                        policy,
                        trade=trade,
                        underlying=session["underlying"],
                        futures=session["futures"],
                    ),
                })
    return output


def numerical(values: list[float]) -> dict:
    return {
        "n": len(values),
        "sum": sum(values),
        "mean": statistics.mean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "positive": sum(value > 0 for value in values),
        "zero": sum(value == 0 for value in values),
        "negative": sum(value < 0 for value in values),
    }


def policy_metric(rows: list[dict], scenario: str) -> dict:
    points_field = f"{scenario}_points"
    comparable = [
        row for row in rows
        if row["selected_exit_points"] is not None and row[points_field] is not None
    ]
    original = [float(row["selected_exit_points"]) for row in comparable]
    candidate = [float(row[points_field]) for row in comparable]
    deltas = [new - old for new, old in zip(candidate, original)]
    stopped = [row for row in rows if row["candidate_triggered"]]
    premature = [
        row for row in stopped
        if row["plus20"] and row["candidate_timestamp"] <= row["plus20_timestamp"]
    ]
    winner_sacrifice = sum(
        max(0.0, float(row["selected_exit_points"]) - float(row[points_field]))
        for row in comparable
        if float(row["selected_exit_points"]) > 0
    )
    structural = [
        row for row in comparable
        if row["selected_exit_policy"] == "STRUCTURAL_BASELINE"
    ]
    unresolved_rescued = [
        row for row in rows
        if row["selected_exit_points"] is None
        and row["candidate_triggered"]
        and row[points_field] is not None
    ]
    return {
        "entries": len(rows),
        "comparable": len(comparable),
        "candidate_triggers": len(stopped),
        "simultaneous_proof_stop_ambiguities": sum(
            row["chronology_status"] == "SIMULTANEOUS_PROOF_STOP_AMBIGUITY"
            for row in rows
        ),
        "missing_exact_minutes": sum(row["missing_exact_minute"] for row in rows),
        "original": numerical(original),
        "candidate": numerical(candidate),
        "net_point_recovery": sum(deltas),
        "improved": sum(delta > 0 for delta in deltas),
        "equal": sum(delta == 0 for delta in deltas),
        "harmed": sum(delta < 0 for delta in deltas),
        "premature_proved_runner_stops": len(premature),
        "winner_points_sacrificed": winner_sacrifice,
        "structural_baseline_point_recovery": sum(
            float(row[points_field]) - float(row["selected_exit_points"])
            for row in structural
        ),
        "proved_candidate_managed_affected": sum(
            row["candidate_triggered"]
            and row["cohort"] == "PROVED_CANDIDATE_MANAGED"
            for row in rows
        ),
        "originally_unresolved_candidate_exits": len(unresolved_rescued),
        "originally_unresolved_candidate_points": numerical([
            float(row[points_field]) for row in unresolved_rescued
        ]),
    }


def grouped_metric(rows: list[dict], field: str, scenario: str) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    return {
        key: policy_metric(value, scenario)
        for key, value in sorted(groups.items())
    }


def build_report(rows: list[dict], *, phase: str, dates: list[str]) -> dict:
    unique_trades = {}
    for row in rows:
        key = (row["session_date"], row["entry_timestamp"], row["family"])
        unique_trades.setdefault(key, row)
    report = {
        "model": "MIDPOINT_CAUSAL_INITIAL_RISK_RESEARCH_V1",
        "phase": phase,
        "sessions": len(dates),
        "first_session": dates[0],
        "last_session": dates[-1],
        "families": ["B", "E", "C"],
        "policy_contract": POLICIES,
        "cohort_counts": dict(Counter(
            row["cohort"] for row in unique_trades.values()
        )),
        "results": {},
        "script_sha256": script_sha256(),
        "dataset_fingerprint": stable_hash(dates),
        "safety": SAFETY,
        "limitations": [
            "Underlying NIFTY points only; no option premiums, spreads, charges or quantity.",
            "Policies are standalone and are not combined or threshold-searched.",
            "Same-minute proof and stop ordering is reported under both causal sensitivities.",
        ],
    }
    for policy in POLICIES:
        policy_rows = [row for row in rows if row["policy"] == policy]
        report["results"][policy] = {}
        for scenario in ("proof_first", "stop_first"):
            report["results"][policy][scenario] = {
                "overall": policy_metric(policy_rows, scenario),
                "by_family": grouped_metric(policy_rows, "family", scenario),
                "by_cohort": grouped_metric(policy_rows, "cohort", scenario),
                "by_block": grouped_metric(policy_rows, "block", scenario),
            }
    return report


def development(outdir: Path) -> int:
    current, sessions, split = load_universe()
    selected = sessions[:split]
    rows = reconstruct_block(current, selected)
    dates = [row["session_date"] for row in selected]
    report = build_report(rows, phase="DEVELOPMENT_IS_ONLY", dates=dates)
    target = outdir / "development"
    target.mkdir(parents=True, exist_ok=True)
    write_csv(target / "trade-policy-results.csv", rows)
    matrix = []
    for policy, result in report["results"].items():
        for scenario, sections in result.items():
            overall = sections["overall"]
            matrix.append({
                "policy": policy,
                "ambiguity_scenario": scenario,
                "entries": overall["entries"],
                "comparable": overall["comparable"],
                "candidate_triggers": overall["candidate_triggers"],
                "net_point_recovery": overall["net_point_recovery"],
                "structural_baseline_point_recovery": (
                    overall["structural_baseline_point_recovery"]
                ),
                "premature_proved_runner_stops": (
                    overall["premature_proved_runner_stops"]
                ),
                "winner_points_sacrificed": overall["winner_points_sacrificed"],
                "improved": overall["improved"],
                "equal": overall["equal"],
                "harmed": overall["harmed"],
                "ambiguities": overall[
                    "simultaneous_proof_stop_ambiguities"
                ],
                "missing_exact_minutes": overall["missing_exact_minutes"],
            })
    write_csv(target / "elimination-matrix.csv", matrix)
    (target / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"DEVELOPMENT ONLY sessions={len(dates)} rows={len(rows)}")
    print(f"OOS hidden sessions={len(sessions) - split}")
    for policy, result in report["results"].items():
        print(policy, "proof-first", result["proof_first"]["overall"])
        print(policy, "stop-first", result["stop_first"]["overall"])
    print(f"Output: {target / 'report.json'}")
    print("Read only: live runtime, audits, orders and proved exits untouched.")
    return 0


def lock_policy(outdir: Path, policy: str, ambiguity: str) -> int:
    if policy not in POLICIES:
        raise SystemExit(f"STOP: unknown policy {policy}")
    if ambiguity not in AMBIGUITY_CHOICES:
        raise SystemExit(f"STOP: unknown ambiguity convention {ambiguity}")
    report_path = outdir / "development" / "report.json"
    if not report_path.exists():
        raise SystemExit("STOP: run --phase develop before locking a policy")
    report = json.loads(report_path.read_text())
    current, sessions, split = load_universe()
    del current
    dates = [row["session_date"] for row in sessions]
    expected = {
        "script_sha256": script_sha256(),
        "dataset_fingerprint": stable_hash(dates[:split]),
    }
    for field, value in expected.items():
        if report.get(field) != value:
            raise SystemExit(f"STOP: development {field} no longer matches source")
    lock_path = outdir / "policy-lock.json"
    if lock_path.exists():
        raise SystemExit(f"STOP: policy already locked at {lock_path}")
    lock = {
        "model": "MIDPOINT_INITIAL_RISK_POLICY_LOCK_V1",
        "policy": policy,
        "ambiguity_convention": ambiguity,
        "policy_contract": POLICIES[policy],
        "script_sha256": script_sha256(),
        "all_dataset_fingerprint": stable_hash(dates),
        "development_dataset_fingerprint": stable_hash(dates[:split]),
        "oos_dataset_fingerprint": stable_hash(dates[split:]),
        "development_sessions": len(dates[:split]),
        "oos_sessions": len(dates[split:]),
        "development_first": dates[0],
        "development_last": dates[split - 1],
        "oos_first": dates[split],
        "oos_last": dates[-1],
        "safety": SAFETY,
    }
    outdir.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")
    print(f"LOCKED {policy} ambiguity={ambiguity}")
    print(f"Lock: {lock_path}")
    print("OOS has not been evaluated.")
    return 0


def validate_oos(outdir: Path) -> int:
    lock_path = outdir / "policy-lock.json"
    receipt_path = outdir / "oos" / "validation-receipt.json"
    if not lock_path.exists():
        raise SystemExit("STOP: create policy lock before OOS validation")
    if receipt_path.exists():
        raise SystemExit(f"STOP: OOS was already validated; receipt={receipt_path}")
    lock = json.loads(lock_path.read_text())
    if lock["script_sha256"] != script_sha256():
        raise SystemExit("STOP: source changed after policy lock")
    current, sessions, split = load_universe()
    dates = [row["session_date"] for row in sessions]
    checks = {
        "all_dataset_fingerprint": stable_hash(dates),
        "development_dataset_fingerprint": stable_hash(dates[:split]),
        "oos_dataset_fingerprint": stable_hash(dates[split:]),
    }
    for field, value in checks.items():
        if lock.get(field) != value:
            raise SystemExit(f"STOP: locked {field} does not match data")
    selected = sessions[split:]
    all_rows = reconstruct_block(current, selected)
    rows = [row for row in all_rows if row["policy"] == lock["policy"]]
    scenario = lock["ambiguity_convention"].replace("-", "_")
    report = build_report(
        rows,
        phase="LOCKED_OOS_SINGLE_POLICY",
        dates=dates[split:],
    )
    report["locked_policy"] = lock["policy"]
    report["locked_ambiguity_convention"] = lock["ambiguity_convention"]
    report["locked_result"] = report["results"][lock["policy"]][scenario]
    target = outdir / "oos"
    target.mkdir(parents=True, exist_ok=True)
    write_csv(target / "trade-policy-results.csv", rows)
    (target / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    receipt = {
        "status": "OOS_VALIDATED",
        "policy": lock["policy"],
        "ambiguity_convention": lock["ambiguity_convention"],
        "sessions": len(selected),
        "first_session": dates[split],
        "last_session": dates[-1],
        "script_sha256": script_sha256(),
        "oos_dataset_fingerprint": stable_hash(dates[split:]),
        "report_sha256": hashlib.sha256(
            (target / "report.json").read_bytes()
        ).hexdigest(),
        "safety": SAFETY,
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        f"LOCKED OOS sessions={len(selected)} policy={lock['policy']} "
        f"ambiguity={lock['ambiguity_convention']}"
    )
    print("RESULT", report["locked_result"]["overall"])
    print(f"Output: {target / 'report.json'}")
    print(f"Receipt: {receipt_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("develop", "lock", "validate-oos"),
        required=True,
    )
    parser.add_argument("--policy", choices=tuple(POLICIES))
    parser.add_argument("--ambiguity", choices=tuple(sorted(AMBIGUITY_CHOICES)))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTDIR)
    arguments = parser.parse_args()
    if arguments.phase == "develop":
        if arguments.policy or arguments.ambiguity:
            raise SystemExit("STOP: development evaluates all policies and sensitivities")
        return development(arguments.output_dir)
    if arguments.phase == "lock":
        if not arguments.policy or not arguments.ambiguity:
            raise SystemExit("STOP: lock requires --policy and --ambiguity")
        return lock_policy(arguments.output_dir, arguments.policy, arguments.ambiguity)
    if arguments.policy or arguments.ambiguity:
        raise SystemExit("STOP: OOS reads policy and ambiguity from policy-lock.json")
    return validate_oos(arguments.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
