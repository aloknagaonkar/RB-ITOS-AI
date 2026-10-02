#!/usr/bin/env python3
"""Full offline backtest of the currently enabled Midpoint shadow strategy.

Included entry families: B, E and C.
Excluded entry families: D, PM_E and DHANUSH.

Selected observation-only exit routing:
- no +20 proof / unavailable classification: structural midpoint invalidation;
- exact proof+10 NORMAL_B: NORMAL_B_PROVED three-tier candidate;
- exact proof+10 RUNNER_STRENGTHENING: first DEGRADED_STARTED-close candidate;
- if the selected candidate never fires: structural midpoint invalidation.

The production coordinator is replayed using completed exact one-minute NIFTY
and futures-VWAP evidence. No service, live audit, configuration, order, paper
order, or quantity is modified.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from market_lab.midpoint_strategy.config import MidpointShadowConfig
from market_lab.midpoint_strategy.live_shadow_v1 import (
    MidpointLiveShadowCoordinatorV1,
)


V55 = Path("scripts/midpoint_v55_boundary_selection_replay.py")
V52 = Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
DEFAULT_OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-current-strategy-full-backtest-v1"
)
ENTRY_TYPES = {"B_ENTRY", "E_ENTRY", "C_ENTRY"}
EXIT_CANDIDATES = {
    "NORMAL_B_PROVED_EXIT_CANDIDATE",
    "DEGRADED_EXIT_CANDIDATE_TRIGGERED",
}


class DummySources:
    pass


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def candle(timestamp: str, row: dict) -> SimpleNamespace:
    return SimpleNamespace(
        timestamp=dt(timestamp),
        open=float(row.get("open", row["close"])),
        high=float(row.get("high", row["close"])),
        low=float(row.get("low", row["close"])),
        close=float(row["close"]),
        volume=float(row.get("volume", 0.0) or 0.0),
    )


def load_audit(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def replay_session(
    session_date: str,
    underlying: dict[str, dict],
    futures: dict[str, dict],
) -> list[dict]:
    config = MidpointShadowConfig(
        family_b_enabled=True,
        family_e_enabled=True,
        family_c_enabled=True,
        family_d_enabled=False,
        pm_e_enabled=False,
        normal_b_proved_candidate_enabled=True,
        degraded_exit_candidate_enabled=True,
        post_rescue_reentry_enabled=False,
    )
    config.assert_safe()
    with tempfile.TemporaryDirectory(prefix="midpoint-current-backtest-") as temp:
        audit_path = Path(temp) / "audit.jsonl"
        coordinator = MidpointLiveShadowCoordinatorV1(
            market_sources=DummySources(),
            audit_path=audit_path,
            config=config,
        )
        coordinator._reset_session(dt(session_date + "T09:15:00+05:30").date())
        underlying_by_ts = {
            dt(timestamp): candle(timestamp, row)
            for timestamp, row in underlying.items()
        }
        for timestamp in sorted(set(underlying).intersection(futures), key=dt):
            moment = dt(timestamp)
            if moment.strftime("%H:%M") < "09:15":
                continue
            future = futures[timestamp]
            coordinator._process_minute(
                ts=moment,
                underlying=underlying_by_ts[moment],
                futures_close=float(future["close"]),
                futures_vwap=float(future["vwap"]),
                underlying_by_ts=underlying_by_ts,
            )
        return load_audit(audit_path)


def directional_points(direction: str, entry: float, current: float) -> float:
    return current - entry if direction == "BULLISH" else entry - current


def first(segment: list[dict], event_type: str) -> dict | None:
    return next(
        (row for row in segment if row.get("event_type") == event_type), None
    )


def selected_exit(segment: list[dict]) -> tuple[str, dict | None]:
    route = first(segment, "MANAGEMENT_ROUTE_SELECTED")
    route_name = route.get("result") if route else None
    if route_name == "NORMAL_B_PROVED_THREE_TIER":
        candidate = first(segment, "NORMAL_B_PROVED_EXIT_CANDIDATE")
        if candidate is not None:
            return "NORMAL_B_PROVED_THREE_TIER", candidate
    if route_name == "RUNNER_DEGRADED_EXIT":
        candidate = first(segment, "DEGRADED_EXIT_CANDIDATE_TRIGGERED")
        if candidate is not None:
            return "DEGRADED_EXIT_CANDIDATE", candidate
    return "STRUCTURAL_BASELINE", first(segment, "STRUCTURAL_TERMINAL")


def valuation(event: dict | None) -> tuple[float | None, float | None, str]:
    if event is None:
        return None, None, "UNRESOLVED"
    evidence = event.get("evidence") or {}
    price = evidence.get("valuation_price", event.get("underlying_price"))
    points = event.get("directional_points")
    basis = str(
        evidence.get("valuation_basis")
        or (
            "OBSERVED_CANDLE_CLOSE"
            if event.get("underlying_price") is not None else "UNAVAILABLE"
        )
    )
    return (
        float(price) if price is not None else None,
        float(points) if points is not None else None,
        basis,
    )


def excursion(
    underlying: dict[str, dict],
    *,
    entry_timestamp: str,
    exit_timestamp: str,
    entry_price: float,
    direction: str,
) -> dict:
    rows = [
        row for timestamp, row in underlying.items()
        if entry_timestamp < timestamp <= exit_timestamp
    ]
    if not rows:
        return {
            "mfe_points": None,
            "mae_points": None,
            "observed_minutes": 0,
        }
    if direction == "BULLISH":
        favorable = max(float(row["high"]) - entry_price for row in rows)
        adverse = min(float(row["low"]) - entry_price for row in rows)
    else:
        favorable = max(entry_price - float(row["low"]) for row in rows)
        adverse = min(entry_price - float(row["high"]) for row in rows)
    return {
        "mfe_points": favorable,
        "mae_points": adverse,
        "observed_minutes": len(rows),
    }


def validate_c_entry(rows: list[dict], entry_index: int, entry: dict) -> None:
    prior = rows[:entry_index]
    reference_type = entry.get("reference_type")
    touch = next(
        (
            row for row in reversed(prior)
            if row.get("event_type") == "C_MIDPOINT_TOUCH_ARMED"
            and row.get("reference_type") == reference_type
        ),
        None,
    )
    terminal = next(
        (
            row for row in reversed(prior)
            if row.get("event_type") == "STRUCTURAL_TERMINAL"
            and row.get("reference_type") == reference_type
        ),
        None,
    )
    if touch is None or terminal is None:
        raise AssertionError(
            f"{entry['session_date']} C entry lacks touch/terminal chronology"
        )
    if not (
        dt(touch["event_timestamp"])
        <= dt(terminal["event_timestamp"])
        < dt(entry["event_timestamp"])
    ):
        raise AssertionError(
            f"{entry['session_date']} C entry contains future leakage"
        )


def reconstruct_session(
    *,
    block: str,
    session_date: str,
    rows: list[dict],
    underlying: dict[str, dict],
) -> list[dict]:
    indexed_entries = [
        (index, row) for index, row in enumerate(rows)
        if row.get("event_type") in ENTRY_TYPES
    ]
    trades = []
    for sequence, (index, entry) in enumerate(indexed_entries, start=1):
        if sequence > 1:
            previous_index = indexed_entries[sequence - 2][0]
            between = rows[previous_index:index]
            if not any(
                row.get("event_type") == "STRUCTURAL_TERMINAL"
                for row in between
            ):
                raise AssertionError(
                    f"{session_date} overlapping baseline entry lifecycles"
                )
        if entry["family"] == "C":
            validate_c_entry(rows, index, entry)
        next_index = (
            indexed_entries[sequence][0]
            if sequence < len(indexed_entries) else len(rows)
        )
        segment = rows[index:next_index]
        proof = first(segment, "PLUS20_PROOF")
        classifier = first(segment, "RUNNER_CLASSIFICATION")
        unavailable = first(segment, "RUNNER_CLASSIFICATION_UNAVAILABLE")
        route = first(segment, "MANAGEMENT_ROUTE_SELECTED")
        degraded = first(segment, "DEGRADED_STARTED")
        structural = first(segment, "STRUCTURAL_TERMINAL")
        policy, selected = selected_exit(segment)

        if proof is not None and classifier is not None:
            expected = dt(proof["event_timestamp"]) + timedelta(minutes=10)
            if dt(classifier["event_timestamp"]) != expected:
                raise AssertionError(
                    f"{session_date} classifier is not exact proof+10"
                )
        if selected is not None and structural is not None:
            if dt(selected["event_timestamp"]) > dt(structural["event_timestamp"]):
                raise AssertionError(
                    f"{session_date} selected exit occurs after structural terminal"
                )

        entry_price = float(entry["underlying_price"])
        selected_price, selected_points, selected_basis = valuation(selected)
        baseline_price, baseline_points, baseline_basis = valuation(structural)
        if selected is not None and selected_points is None and selected_price is not None:
            selected_points = directional_points(
                entry["direction"], entry_price, selected_price
            )
        if structural is not None and baseline_points is None and baseline_price is not None:
            baseline_points = directional_points(
                entry["direction"], entry_price, baseline_price
            )
        selected_timestamp = selected["event_timestamp"] if selected else ""
        x = (
            excursion(
                underlying,
                entry_timestamp=entry["event_timestamp"],
                exit_timestamp=selected_timestamp,
                entry_price=entry_price,
                direction=entry["direction"],
            )
            if selected_timestamp else {
                "mfe_points": None, "mae_points": None, "observed_minutes": 0
            }
        )
        duration = (
            (dt(selected_timestamp) - dt(entry["event_timestamp"])).total_seconds()
            / 60.0
            if selected_timestamp else None
        )
        trades.append({
            "block": block,
            "session_date": session_date,
            "month": session_date[:7],
            "sequence": sequence,
            "family": entry["family"],
            "direction": entry["direction"],
            "reference_type": entry.get("reference_type"),
            "reference_high": entry.get("reference_high"),
            "reference_low": entry.get("reference_low"),
            "midpoint": entry.get("midpoint"),
            "original_boundary": entry.get("original_boundary"),
            "entry_timestamp": entry["event_timestamp"],
            "entry_price": entry_price,
            "entry_reason": entry.get("reason"),
            "plus20": proof is not None,
            "plus20_timestamp": proof["event_timestamp"] if proof else "",
            "classifier_timestamp": classifier["event_timestamp"] if classifier else "",
            "classifier_result": classifier.get("result", "") if classifier else "",
            "classifier_unavailable": unavailable is not None,
            "management_route": route.get("result", "") if route else "STRUCTURAL_BASELINE",
            "degraded_timestamp": degraded["event_timestamp"] if degraded else "",
            "selected_exit_policy": policy,
            "selected_exit_event": selected.get("event_type", "") if selected else "",
            "selected_exit_reason": selected.get("reason", "") if selected else "",
            "selected_exit_timestamp": selected_timestamp,
            "selected_exit_price": selected_price,
            "selected_exit_points": selected_points,
            "selected_valuation_basis": selected_basis,
            "duration_minutes": duration,
            **x,
            "structural_exit_timestamp": structural["event_timestamp"] if structural else "",
            "structural_exit_price": baseline_price,
            "structural_exit_points": baseline_points,
            "structural_valuation_basis": baseline_basis,
            "candidate_delta_vs_structural": (
                selected_points - baseline_points
                if selected_points is not None and baseline_points is not None
                else None
            ),
            "status": "CLOSED" if selected is not None else "UNRESOLVED",
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        })
    return trades


def metric(rows: list[dict]) -> dict:
    completed = [
        row for row in rows if row["selected_exit_points"] is not None
    ]
    points = [float(row["selected_exit_points"]) for row in completed]
    common = [
        row for row in completed if row["structural_exit_points"] is not None
    ]
    deltas = [float(row["candidate_delta_vs_structural"]) for row in common]
    return {
        "entries": len(rows),
        "completed": len(completed),
        "unresolved": len(rows) - len(completed),
        "sum_points": sum(points),
        "mean_points": statistics.mean(points) if points else None,
        "median_points": statistics.median(points) if points else None,
        "positive": sum(value > 0 for value in points),
        "zero": sum(value == 0 for value in points),
        "negative": sum(value < 0 for value in points),
        "win_rate_pct": 100.0 * sum(value > 0 for value in points) / len(points)
        if points else None,
        "common_structural_comparisons": len(common),
        "delta_vs_structural_sum": sum(deltas),
        "improved_vs_structural": sum(value > 0 for value in deltas),
        "equal_to_structural": sum(value == 0 for value in deltas),
        "harmed_vs_structural": sum(value < 0 for value in deltas),
    }


def grouped(rows: list[dict], field: str) -> dict:
    values: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        values[str(row[field])].append(row)
    return {key: metric(value) for key, value in sorted(values.items())}


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    fields = list(rows[0])
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTDIR)
    arguments = parser.parse_args()
    if arguments.start:
        dt(arguments.start + "T00:00:00+05:30")
    if arguments.end:
        dt(arguments.end + "T00:00:00+05:30")
    if arguments.start and arguments.end and arguments.start > arguments.end:
        raise SystemExit("STOP: --start must not be after --end")

    v55 = import_module(V55, "v55_for_current_strategy_backtest")
    v52 = import_module(V52, "v52_for_current_strategy_backtest")
    canon = import_module(CANON, "canon_for_current_strategy_backtest")
    all_trades: list[dict] = []
    event_counts = Counter()
    sessions = 0

    for block in v52.BLOCKS:
        underlying, futures, _ = v55.load_block(block, v52, canon)
        session_dates = sorted(set(underlying).intersection(futures))
        for session_date in session_dates:
            if arguments.start and session_date < arguments.start:
                continue
            if arguments.end and session_date > arguments.end:
                continue
            sessions += 1
            rows = replay_session(
                session_date, underlying[session_date], futures[session_date]
            )
            event_counts.update(str(row.get("event_type")) for row in rows)
            all_trades.extend(reconstruct_session(
                block=block["name"],
                session_date=session_date,
                rows=rows,
                underlying=underlying[session_date],
            ))

    if not sessions:
        raise SystemExit("STOP: no exact NIFTY + futures sessions in requested range")
    if any(row["family"] not in {"B", "E", "C"} for row in all_trades):
        raise AssertionError("excluded family entered current-strategy backtest")

    report = {
        "model": "MIDPOINT_CURRENT_STRATEGY_FULL_BACKTEST_V1",
        "period": {
            "requested_start": arguments.start,
            "requested_end": arguments.end,
            "sessions": sessions,
        },
        "strategy": {
            "entry_families": ["B", "E", "C"],
            "excluded_families": ["D", "PM_E", "DHANUSH"],
            "exit_routing": {
                "UNPROVED_OR_UNAVAILABLE": "STRUCTURAL_BASELINE",
                "NORMAL_B": "NORMAL_B_PROVED_THREE_TIER",
                "RUNNER_STRENGTHENING": "DEGRADED_EXIT_CANDIDATE",
                "CANDIDATE_NOT_TRIGGERED": "STRUCTURAL_BASELINE",
            },
            "operational_gating": (
                "Candidate exit is valued independently, while the replayed live "
                "baseline lifecycle remains active until structural terminal."
            ),
        },
        "overall": metric(all_trades),
        "by_family": grouped(all_trades, "family"),
        "by_direction": grouped(all_trades, "direction"),
        "by_management_route": grouped(all_trades, "management_route"),
        "by_exit_policy": grouped(all_trades, "selected_exit_policy"),
        "by_exit_reason": grouped(all_trades, "selected_exit_reason"),
        "by_block": grouped(all_trades, "block"),
        "by_month": grouped(all_trades, "month"),
        "event_counts": dict(event_counts),
        "acceptance": {
            "completed_minute_only": True,
            "exact_proof_plus_10_classifier": True,
            "fresh_boundary_required_for_c": True,
            "one_active_baseline_lifecycle": True,
            "no_future_leakage_checks": "PASS",
            "family_d_excluded": True,
            "pm_e_excluded": True,
            "dhanush_excluded": True,
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "orders_sent": False,
        },
        "limitations": [
            "Underlying NIFTY points only; no option premium, bid/ask, slippage, charges or quantity.",
            "The +50 NORMAL_B target uses the existing assumed exact intrabar target fill.",
            "Candidate exits do not free the baseline lifecycle for additional entries before its structural terminal.",
            "Unresolved trades are reported and excluded from completed-return statistics.",
        ],
    }
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(arguments.output_dir / "trades.csv", all_trades)
    (arguments.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(f"Sessions: {sessions} trades: {len(all_trades)}")
    print("OVERALL", report["overall"])
    for family, summary in report["by_family"].items():
        print(family, summary)
    print("EXIT POLICIES")
    for policy, summary in report["by_exit_policy"].items():
        print(policy, summary)
    print(f"Output: {arguments.output_dir / 'report.json'}")
    print("Read only: services, live audit, configuration, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
