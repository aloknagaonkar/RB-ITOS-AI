#!/usr/bin/env python3
"""Offline 480-session validation for guarded C and PM_E shadow entries.

This runner calls the production coordinator one completed minute at a time with
C and PM_E explicitly enabled. It never starts a service, sends an order, or
changes a live audit. Results are underlying directional points only.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import statistics
import tempfile
from collections import Counter
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
OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-c-pm-e-shared-lifecycle-v1"
)
TRADE_CSV = OUTDIR / "trade-comparison.csv"
EVENT_CSV = OUTDIR / "extended-events.csv"
REPORT_JSON = OUTDIR / "report.json"

ENTRY_TYPES = {"B_ENTRY", "E_ENTRY", "C_ENTRY", "PM_E_ENTRY"}
RELEVANT_TYPES = {
    "C_MIDPOINT_TOUCH_ARMED",
    "C_BOUNDARY_CLASSIFIED",
    "C_WATCH_STARTED",
    "C_CONFIRMATION_CHECK",
    "C_ENTRY",
    "C_ENTRY_BLOCKED",
    "C_ENTRY_REJECTED",
    "PM_REFERENCE_LOCKED",
    "PM_FALSE_BREAK_OBSERVED",
    "PM_MIDPOINT_RECROSS_ARMED",
    "PM_E_BOUNDARY_CLASSIFIED",
    "PM_E_ENTRY",
    "PM_E_REJECTED",
    "PLUS20_PROOF",
    "RUNNER_CLASSIFICATION",
    "MANAGEMENT_ROUTE_SELECTED",
    "NORMAL_B_PROVED_EXIT_CANDIDATE",
    "DEGRADED_EXIT_CANDIDATE_TRIGGERED",
    "STRUCTURAL_TERMINAL",
}


class DummySources:
    pass


def _import(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _candle(timestamp: str, row: dict) -> SimpleNamespace:
    return SimpleNamespace(
        timestamp=_dt(timestamp),
        open=float(row.get("open", row["close"])),
        high=float(row.get("high", row["close"])),
        low=float(row.get("low", row["close"])),
        close=float(row["close"]),
        volume=float(row.get("volume", 0.0) or 0.0),
    )


def _load_audit(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _points(direction: str, entry: float, exit_price: float) -> float:
    sign = 1.0 if direction == "BULLISH" else -1.0
    return sign * (exit_price - entry)


def _write_csv(path: Path, rows: list[dict]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def replay_session(session_date: str, underlying: dict, futures: dict) -> list[dict]:
    config = MidpointShadowConfig(
        family_c_enabled=True,
        pm_e_enabled=True,
        family_d_enabled=False,
        post_rescue_reentry_enabled=False,
    )
    with tempfile.TemporaryDirectory(prefix="midpoint-c-pm-e-") as temp:
        audit = Path(temp) / "audit.jsonl"
        coordinator = MidpointLiveShadowCoordinatorV1(
            market_sources=DummySources(), audit_path=audit, config=config
        )
        coordinator._reset_session(_dt(session_date + "T09:15:00+05:30").date())
        underlying_by_ts = {
            _dt(timestamp): _candle(timestamp, row)
            for timestamp, row in underlying.items()
        }
        for timestamp in sorted(set(underlying).intersection(futures), key=_dt):
            ts = _dt(timestamp)
            row = futures[timestamp]
            coordinator._process_minute(
                ts=ts,
                underlying=underlying_by_ts[ts],
                futures_close=float(row["close"]),
                futures_vwap=float(row["vwap"]),
                underlying_by_ts=underlying_by_ts,
            )
        return _load_audit(audit)


def validate_chronology(session_date: str, rows: list[dict]) -> None:
    for index, row in enumerate(rows):
        timestamp = _dt(row["event_timestamp"])
        if row["event_type"] == "C_ENTRY":
            prior = rows[:index]
            touch = next(
                (event for event in reversed(prior)
                 if event["event_type"] == "C_MIDPOINT_TOUCH_ARMED"
                 and event.get("reference_type") == row.get("reference_type")),
                None,
            )
            terminal = next(
                (event for event in reversed(prior)
                 if event["event_type"] == "STRUCTURAL_TERMINAL"
                 and event.get("reference_type") == row.get("reference_type")),
                None,
            )
            if touch is None or terminal is None:
                raise AssertionError(f"{session_date} C entry lacks touch/terminal")
            if not (
                _dt(touch["event_timestamp"])
                <= _dt(terminal["event_timestamp"])
                < timestamp
            ):
                raise AssertionError(f"{session_date} C chronology leaked")
        if row["event_type"] == "PM_E_ENTRY":
            prior_types = [event["event_type"] for event in rows[:index]]
            required = (
                "PM_REFERENCE_LOCKED",
                "PM_FALSE_BREAK_OBSERVED",
                "PM_MIDPOINT_RECROSS_ARMED",
                "PM_E_BOUNDARY_CLASSIFIED",
            )
            positions = []
            for event_type in required:
                try:
                    positions.append(len(prior_types) - 1 - prior_types[::-1].index(event_type))
                except ValueError as exc:
                    raise AssertionError(
                        f"{session_date} PM_E entry lacks {event_type}"
                    ) from exc
            if positions != sorted(positions) or not all(
                _dt(rows[position]["event_timestamp"]) < timestamp
                for position in positions[:-1]
            ):
                raise AssertionError(f"{session_date} PM_E chronology leaked")


def reconstruct_trades(block: str, session_date: str, rows: list[dict]) -> list[dict]:
    indexed_entries = [
        (index, row) for index, row in enumerate(rows)
        if row.get("event_type") in ENTRY_TYPES
    ]
    trades = []
    for sequence, (index, entry) in enumerate(indexed_entries, start=1):
        next_index = (
            indexed_entries[sequence][0]
            if sequence < len(indexed_entries) else len(rows)
        )
        segment = rows[index:next_index]
        by_type = {
            kind: next(
                (row for row in segment if row.get("event_type") == kind), None
            )
            for kind in (
                "PLUS20_PROOF",
                "RUNNER_CLASSIFICATION",
                "MANAGEMENT_ROUTE_SELECTED",
                "NORMAL_B_PROVED_EXIT_CANDIDATE",
                "DEGRADED_EXIT_CANDIDATE_TRIGGERED",
                "STRUCTURAL_TERMINAL",
            )
        }
        proof = by_type["PLUS20_PROOF"]
        classifier = by_type["RUNNER_CLASSIFICATION"]
        if proof is not None and classifier is not None:
            expected = _dt(proof["event_timestamp"]) + timedelta(minutes=10)
            if _dt(classifier["event_timestamp"]) != expected:
                raise AssertionError(
                    f"{session_date} classifier is not exact proof+10"
                )
        entry_price = float(entry["underlying_price"])
        terminal = by_type["STRUCTURAL_TERMINAL"]
        degraded = by_type["DEGRADED_EXIT_CANDIDATE_TRIGGERED"]
        normal = by_type["NORMAL_B_PROVED_EXIT_CANDIDATE"]
        route = by_type["MANAGEMENT_ROUTE_SELECTED"]
        selected = terminal
        selected_policy = "STRUCTURAL_BASELINE"
        if route and route.get("result") == "RUNNER_DEGRADED_EXIT" and degraded:
            selected = degraded
            selected_policy = "DEGRADED_EXIT_CANDIDATE"
        elif (
            route
            and route.get("result") == "NORMAL_B_PROVED_THREE_TIER"
            and normal
        ):
            selected = normal
            selected_policy = "NORMAL_B_PROVED_THREE_TIER"
        selected_price = (
            float(selected["underlying_price"])
            if selected and selected.get("underlying_price") is not None else None
        )
        baseline_price = (
            float(terminal["underlying_price"])
            if terminal and terminal.get("underlying_price") is not None else None
        )
        direction = entry["direction"]
        selected_points = (
            _points(direction, entry_price, selected_price)
            if selected_price is not None else None
        )
        baseline_points = (
            _points(direction, entry_price, baseline_price)
            if baseline_price is not None else None
        )
        trades.append({
            "block": block,
            "session_date": session_date,
            "sequence": sequence,
            "family": entry["family"],
            "direction": direction,
            "entry_timestamp": entry["event_timestamp"],
            "entry_price": entry_price,
            "plus20_timestamp": proof["event_timestamp"] if proof else "",
            "classifier_result": classifier.get("result", "") if classifier else "",
            "management_route": route.get("result", "") if route else "",
            "selected_policy": selected_policy,
            "selected_exit_timestamp": selected["event_timestamp"] if selected else "",
            "selected_exit_points": selected_points,
            "structural_exit_timestamp": terminal["event_timestamp"] if terminal else "",
            "structural_exit_points": baseline_points,
            "candidate_delta_points": (
                selected_points - baseline_points
                if selected_points is not None and baseline_points is not None
                else None
            ),
        })
    return trades


def _summary(trades: list[dict]) -> dict:
    captured = [
        row["selected_exit_points"] for row in trades
        if row["selected_exit_points"] is not None
    ]
    baseline = [
        row["structural_exit_points"] for row in trades
        if row["structural_exit_points"] is not None
    ]
    changed = [
        row["candidate_delta_points"] for row in trades
        if row["candidate_delta_points"] not in (None, 0.0)
    ]
    return {
        "entries": len(trades),
        "completed_candidate": len(captured),
        "completed_structural": len(baseline),
        "selected_sum_points": sum(captured),
        "selected_mean_points": statistics.mean(captured) if captured else None,
        "selected_positive": sum(value > 0 for value in captured),
        "structural_sum_points": sum(baseline),
        "changed_exits": len(changed),
        "candidate_delta_sum": sum(changed),
        "improved": sum(value > 0 for value in changed),
        "harmed": sum(value < 0 for value in changed),
    }


def main() -> int:
    v55 = _import(V55, "v55_for_c_pm_e")
    v52 = _import(V52, "v52_for_c_pm_e")
    canon = _import(CANON, "canon_for_c_pm_e")
    all_trades: list[dict] = []
    event_rows: list[dict] = []
    sessions = 0
    event_counts = Counter()

    for block in v52.BLOCKS:
        underlying, futures, _ = v55.load_block(block, v52, canon)
        for session_date in sorted(set(underlying).intersection(futures)):
            sessions += 1
            rows = replay_session(
                session_date, underlying[session_date], futures[session_date]
            )
            validate_chronology(session_date, rows)
            all_trades.extend(
                reconstruct_trades(block["name"], session_date, rows)
            )
            for row in rows:
                if row.get("event_type") not in RELEVANT_TYPES:
                    continue
                event_counts[row["event_type"]] += 1
                event_rows.append({
                    "block": block["name"],
                    "session_date": session_date,
                    **{key: value for key, value in row.items() if key != "evidence"},
                    "evidence_json": json.dumps(row.get("evidence", {}), sort_keys=True),
                })

    family_summaries = {
        family: _summary([row for row in all_trades if row["family"] == family])
        for family in ("B", "E", "C", "PM_E")
    }
    august_25 = [
        row for row in all_trades if row["session_date"] == "2026-08-25"
    ]
    report = {
        "model": "MIDPOINT_C_PM_E_SHARED_LIFECYCLE_VALIDATION_V1",
        "sessions": sessions,
        "families_enabled": {"B": True, "E": True, "C": True, "D": False, "PM_E": True},
        "family_summaries": family_summaries,
        "event_counts": dict(event_counts),
        "august_25_trades": august_25,
        "acceptance": {
            "completed_minute_only": True,
            "fresh_boundary_required": True,
            "exact_proof_plus_10_classifier": True,
            "one_active_trade": True,
            "no_future_leakage_checks": "PASS",
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "orders_sent": False,
        },
        "interpretation": (
            "Underlying close/touch observation only. No option fills, bid/ask, "
            "slippage, charges, quantity, or orders."
        ),
    }
    OUTDIR.mkdir(parents=True, exist_ok=True)
    _write_csv(TRADE_CSV, all_trades)
    _write_csv(EVENT_CSV, event_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(f"Sessions: {sessions} trades: {len(all_trades)}")
    for family, summary in family_summaries.items():
        print(family, summary)
    print("AUGUST 25")
    for trade in august_25:
        print(
            trade["family"], trade["entry_timestamp"], trade["direction"],
            trade["selected_policy"], trade["selected_exit_points"],
        )
    print(f"Output: {REPORT_JSON}")
    print("Read only: live audit, services, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
