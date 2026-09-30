#!/usr/bin/env python3
"""Historical observation-only backtest for corrected PM Midpoint B/E entries.

The replay uses the production coordinator on exact completed one-minute NIFTY
and front-future/VWAP data.  Its configuration mirrors the intended live
workspace: B/E enabled, repeated B/E rearm enabled, C/D disabled, and PM B/E
enabled only inside this isolated replay.

For PM_B, the report separates the boundary classification from the delayed
Candidate-A confirmation.  ``pre_entry_move_points`` therefore measures how
far NIFTY travelled directionally between those two completed closes.  The
boundary counterfactual uses the actual selected exit timestamp and price; it
is an entry-price comparison, not an independently simulated strategy.

No live audit, service, environment flag, order, paper order, or quantity is
read or modified.
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
    "midpoint-pm-be-backtest-v1"
)
DEFAULT_FORWARD_ROOT = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-forward-oos-2026-09-09-to-29-v1"
)
DEFAULT_FORWARD_OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-pm-be-backtest-480-plus-forward-v1"
)
PM_ENTRY_TYPES = {"PM_B_ENTRY", "PM_E_ENTRY"}


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


def directional_points(direction: str, entry: float, current: float) -> float:
    return current - entry if direction == "BULLISH" else entry - current


def first(rows: list[dict], event_type: str) -> dict | None:
    return next((row for row in rows if row.get("event_type") == event_type), None)


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


def event_price(event: dict | None) -> float | None:
    if event is None:
        return None
    evidence = event.get("evidence") or {}
    value = evidence.get("valuation_price", event.get("underlying_price"))
    return float(value) if value is not None else None


def replay_session(
    session_date: str,
    underlying: dict[str, dict],
    futures: dict[str, dict],
) -> list[dict]:
    config = MidpointShadowConfig(
        family_b_enabled=True,
        family_e_enabled=True,
        family_c_enabled=False,
        be_rearm_enabled=True,
        family_d_enabled=False,
        pm_e_enabled=True,
        normal_b_proved_candidate_enabled=True,
        degraded_exit_candidate_enabled=True,
        post_rescue_reentry_enabled=False,
    )
    config.assert_safe()
    with tempfile.TemporaryDirectory(prefix="midpoint-pm-be-backtest-") as temp:
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


def validate_pm_chronology(session_date: str, rows: list[dict]) -> None:
    timestamps = [dt(row["event_timestamp"]) for row in rows]
    if timestamps != sorted(timestamps):
        raise AssertionError(f"{session_date} audit chronology is not monotonic")
    for index, entry in enumerate(rows):
        if entry.get("event_type") not in PM_ENTRY_TYPES:
            continue
        prior = rows[:index]
        boundary = next(
            (
                row for row in reversed(prior)
                if row.get("event_type") == "PM_BOUNDARY_CLASSIFIED"
                and row.get("direction") == entry.get("direction")
            ),
            None,
        )
        midpoint = next(
            (
                row for row in reversed(prior)
                if row.get("event_type") == "PM_MIDPOINT_BREAK"
                and row.get("direction") == entry.get("direction")
            ),
            None,
        )
        if midpoint is None or boundary is None:
            raise AssertionError(f"{session_date} PM entry lacks midpoint/boundary")
        if not (
            dt(midpoint["event_timestamp"])
            <= dt(boundary["event_timestamp"])
            <= dt(entry["event_timestamp"])
        ):
            raise AssertionError(f"{session_date} PM entry contains future leakage")
        if entry["event_type"] == "PM_E_ENTRY":
            if boundary.get("result") != "E":
                raise AssertionError(f"{session_date} PM_E owner mismatch")
            if boundary["event_timestamp"] != entry["event_timestamp"]:
                raise AssertionError(f"{session_date} PM_E was not immediate")
        else:
            if boundary.get("result") != "B":
                raise AssertionError(f"{session_date} PM_B owner mismatch")
            checks = [
                row for row in prior
                if row.get("event_type") == "PM_B_CONFIRMATION_CHECK"
                and dt(row["event_timestamp"]) >= dt(boundary["event_timestamp"])
            ]
            if not checks or checks[-1].get("result") != "ENTRY":
                raise AssertionError(f"{session_date} PM_B lacks confirmation")
            delay = (
                dt(entry["event_timestamp"]) - dt(boundary["event_timestamp"])
            ).total_seconds() / 60.0
            if not 1 <= delay <= 10:
                raise AssertionError(f"{session_date} PM_B delay outside 1..10m")


def excursion(
    underlying: dict[str, dict],
    *,
    entry_timestamp: str,
    exit_timestamp: str,
    entry_price: float,
    direction: str,
) -> tuple[float | None, float | None]:
    rows = [
        row for timestamp, row in underlying.items()
        if entry_timestamp < timestamp <= exit_timestamp
    ]
    if not rows:
        return None, None
    if direction == "BULLISH":
        return (
            max(float(row["high"]) - entry_price for row in rows),
            min(float(row["low"]) - entry_price for row in rows),
        )
    return (
        max(entry_price - float(row["low"]) for row in rows),
        min(entry_price - float(row["high"]) for row in rows),
    )


def reconstruct_pm_trades(
    *,
    block: str,
    session_date: str,
    rows: list[dict],
    underlying: dict[str, dict],
) -> list[dict]:
    all_entries = [
        (index, row) for index, row in enumerate(rows)
        if str(row.get("event_type", "")).endswith("_ENTRY")
        and row.get("result") == "SHADOW_ENTRY"
    ]
    output = []
    for position, (index, entry) in enumerate(all_entries):
        if entry.get("event_type") not in PM_ENTRY_TYPES:
            continue
        next_index = all_entries[position + 1][0] if position + 1 < len(all_entries) else len(rows)
        segment = rows[index:next_index]
        boundary = next(
            (
                row for row in reversed(rows[: index + 1])
                if row.get("event_type") == "PM_BOUNDARY_CLASSIFIED"
                and row.get("direction") == entry.get("direction")
            ),
            None,
        )
        if boundary is None:
            raise AssertionError(f"{session_date} PM trade has no boundary event")
        policy, selected = selected_exit(segment)
        structural = first(segment, "STRUCTURAL_TERMINAL")
        proof = first(segment, "PLUS20_PROOF")
        classifier = first(segment, "RUNNER_CLASSIFICATION")
        route = first(segment, "MANAGEMENT_ROUTE_SELECTED")
        if proof is not None and classifier is not None:
            expected = dt(proof["event_timestamp"]) + timedelta(minutes=10)
            if dt(classifier["event_timestamp"]) != expected:
                raise AssertionError(f"{session_date} classifier is not proof+10")

        entry_price = float(entry["underlying_price"])
        boundary_price = float(boundary["underlying_price"])
        exit_price = event_price(selected)
        structural_price = event_price(structural)
        direction = str(entry["direction"])
        exit_points = (
            directional_points(direction, entry_price, exit_price)
            if exit_price is not None else None
        )
        boundary_exit_points = (
            directional_points(direction, boundary_price, exit_price)
            if exit_price is not None else None
        )
        structural_points = (
            directional_points(direction, entry_price, structural_price)
            if structural_price is not None else None
        )
        exit_timestamp = selected.get("event_timestamp", "") if selected else ""
        mfe, mae = (
            excursion(
                underlying,
                entry_timestamp=entry["event_timestamp"],
                exit_timestamp=exit_timestamp,
                entry_price=entry_price,
                direction=direction,
            )
            if exit_timestamp else (None, None)
        )
        delay = (
            dt(entry["event_timestamp"]) - dt(boundary["event_timestamp"])
        ).total_seconds() / 60.0
        pre_entry_move = directional_points(direction, boundary_price, entry_price)
        output.append({
            "block": block,
            "session_date": session_date,
            "month": session_date[:7],
            "family": entry["family"],
            "direction": direction,
            "midpoint_timestamp": (boundary.get("evidence") or {}).get(
                "midpoint_break_timestamp", ""
            ),
            "boundary_timestamp": boundary["event_timestamp"],
            "boundary_price": boundary_price,
            "boundary_owner": boundary.get("result"),
            "entry_timestamp": entry["event_timestamp"],
            "entry_price": entry_price,
            "confirmation_delay_minutes": delay,
            "pre_entry_move_points": pre_entry_move,
            "plus20": proof is not None,
            "plus20_timestamp": proof.get("event_timestamp", "") if proof else "",
            "classifier_result": classifier.get("result", "") if classifier else "",
            "management_route": route.get("result", "") if route else "STRUCTURAL_BASELINE",
            "selected_exit_policy": policy,
            "selected_exit_timestamp": exit_timestamp,
            "selected_exit_price": exit_price,
            "selected_exit_points": exit_points,
            "mfe_points_after_entry": mfe,
            "mae_points_after_entry": mae,
            "boundary_counterfactual_points_same_exit": boundary_exit_points,
            "confirmation_cost_points_same_exit": (
                boundary_exit_points - exit_points
                if boundary_exit_points is not None and exit_points is not None else None
            ),
            "structural_exit_timestamp": structural.get("event_timestamp", "") if structural else "",
            "structural_exit_points": structural_points,
            "status": "CLOSED" if selected else "UNRESOLVED",
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
        })
    return output


def trade_metric(rows: list[dict]) -> dict:
    completed = [row for row in rows if row["selected_exit_points"] is not None]
    points = [float(row["selected_exit_points"]) for row in completed]
    delays = [float(row["confirmation_delay_minutes"]) for row in rows]
    missed = [float(row["pre_entry_move_points"]) for row in rows]
    counterfactual = [
        float(row["boundary_counterfactual_points_same_exit"])
        for row in completed
    ]
    return {
        "entries": len(rows),
        "completed": len(completed),
        "unresolved": len(rows) - len(completed),
        "sum_points": sum(points),
        "mean_points": statistics.mean(points) if points else None,
        "median_points": statistics.median(points) if points else None,
        "positive": sum(value > 0 for value in points),
        "negative": sum(value < 0 for value in points),
        "win_rate_pct": 100.0 * sum(value > 0 for value in points) / len(points)
        if points else None,
        "mean_confirmation_delay_minutes": statistics.mean(delays) if delays else None,
        "mean_pre_entry_move_points": statistics.mean(missed) if missed else None,
        "sum_pre_entry_move_points": sum(missed),
        "boundary_counterfactual_sum_same_exit": sum(counterfactual),
        "boundary_counterfactual_delta_sum": sum(counterfactual) - sum(points),
    }


def grouped(rows: list[dict], field: str) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    return {key: trade_metric(value) for key, value in sorted(groups.items())}


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_forward_sessions(root: Path) -> dict[str, tuple[dict, dict]]:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(
            f"STOP: forward manifest unavailable: {manifest_path}. "
            "Run scripts/materialize_midpoint_forward_market_data.py first."
        )
    manifest = json.loads(manifest_path.read_text())
    output: dict[str, tuple[dict, dict]] = {}
    for item in manifest.get("sessions", []):
        session_date = str(item["session_date"])
        path = root / session_date / "minutes.jsonl"
        if not path.exists():
            raise SystemExit(f"STOP: forward minute file unavailable: {path}")
        rows = [json.loads(line) for line in path.read_text().splitlines() if line]
        if len(rows) != 360:
            raise SystemExit(
                f"STOP: forward session {session_date} has {len(rows)} minutes, expected 360"
            )
        underlying: dict[str, dict] = {}
        futures: dict[str, dict] = {}
        for row in rows:
            timestamp = str(row["timestamp"])
            if timestamp in underlying:
                raise SystemExit(f"STOP: duplicate forward minute {timestamp}")
            underlying[timestamp] = {
                "open": float(row["underlying_open"]),
                "high": float(row["underlying_high"]),
                "low": float(row["underlying_low"]),
                "close": float(row["underlying_close"]),
            }
            futures[timestamp] = {
                "close": float(row["futures_close"]),
                "vwap": float(row["futures_vwap"]),
                "volume": float(row["futures_volume"]),
            }
        output[session_date] = (underlying, futures)
    expected = int(manifest.get("session_count", len(output)))
    if len(output) != expected:
        raise SystemExit(
            f"STOP: forward manifest count={expected}, loaded={len(output)}"
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument(
        "--include-forward",
        action="store_true",
        help="append the separately materialized September 9-29 forward block",
    )
    parser.add_argument(
        "--forward-root", type=Path, default=DEFAULT_FORWARD_ROOT
    )
    arguments = parser.parse_args()
    if arguments.include_forward and arguments.output_dir == DEFAULT_OUTDIR:
        arguments.output_dir = DEFAULT_FORWARD_OUTDIR
    if arguments.start:
        dt(arguments.start + "T00:00:00+05:30")
    if arguments.end:
        dt(arguments.end + "T00:00:00+05:30")
    if arguments.start and arguments.end and arguments.start > arguments.end:
        raise SystemExit("STOP: --start must not be after --end")

    v55 = import_module(V55, "v55_for_pm_be_backtest")
    v52 = import_module(V52, "v52_for_pm_be_backtest")
    canon = import_module(CANON, "canon_for_pm_be_backtest")
    all_trades: list[dict] = []
    event_counts = Counter()
    boundary_outcomes = Counter()
    sessions = 0

    for block in v52.BLOCKS:
        underlying, futures, _ = v55.load_block(block, v52, canon)
        for session_date in sorted(set(underlying).intersection(futures)):
            if arguments.start and session_date < arguments.start:
                continue
            if arguments.end and session_date > arguments.end:
                continue
            sessions += 1
            rows = replay_session(
                session_date, underlying[session_date], futures[session_date]
            )
            validate_pm_chronology(session_date, rows)
            event_counts.update(str(row.get("event_type")) for row in rows)
            for row in rows:
                if row.get("event_type") == "PM_BOUNDARY_CLASSIFIED":
                    boundary_outcomes[str(row.get("result"))] += 1
                elif row.get("event_type") in {
                    "PM_ENTRY_BLOCKED", "PM_ENTRY_REJECTED", "PM_ENTRY_WINDOW_EXPIRED"
                }:
                    boundary_outcomes[str(row.get("reason"))] += 1
            all_trades.extend(reconstruct_pm_trades(
                block=block["name"],
                session_date=session_date,
                rows=rows,
                underlying=underlying[session_date],
            ))

    forward_sessions = 0
    if arguments.include_forward:
        forward = load_forward_sessions(arguments.forward_root)
        for session_date in sorted(forward):
            if arguments.start and session_date < arguments.start:
                continue
            if arguments.end and session_date > arguments.end:
                continue
            underlying, futures = forward[session_date]
            sessions += 1
            forward_sessions += 1
            rows = replay_session(session_date, underlying, futures)
            validate_pm_chronology(session_date, rows)
            event_counts.update(str(row.get("event_type")) for row in rows)
            for row in rows:
                if row.get("event_type") == "PM_BOUNDARY_CLASSIFIED":
                    boundary_outcomes[str(row.get("result"))] += 1
                elif row.get("event_type") in {
                    "PM_ENTRY_BLOCKED", "PM_ENTRY_REJECTED", "PM_ENTRY_WINDOW_EXPIRED"
                }:
                    boundary_outcomes[str(row.get("reason"))] += 1
            all_trades.extend(reconstruct_pm_trades(
                block="FORWARD_OOS_2026-09",
                session_date=session_date,
                rows=rows,
                underlying=underlying,
            ))

    if not sessions:
        raise SystemExit("STOP: no exact NIFTY + futures sessions in requested range")
    report = {
        "model": "MIDPOINT_PM_BE_HISTORICAL_BACKTEST_V1",
        "period": {
            "requested_start": arguments.start,
            "requested_end": arguments.end,
            "sessions": sessions,
            "frozen_historical_sessions": sessions - forward_sessions,
            "forward_oos_sessions": forward_sessions,
        },
        "configuration": {
            "B": True,
            "E": True,
            "BE_REARM": True,
            "C": False,
            "D": False,
            "PM_BE_ISOLATED_REPLAY_GATE": True,
            "LIVE_PM_GATE_CHANGED": False,
            "FORWARD_OOS_INCLUDED": arguments.include_forward,
        },
        "overall": trade_metric(all_trades),
        "by_family": grouped(all_trades, "family"),
        "by_direction": grouped(all_trades, "direction"),
        "by_exit_policy": grouped(all_trades, "selected_exit_policy"),
        "by_block": grouped(all_trades, "block"),
        "by_month": grouped(all_trades, "month"),
        "pm_boundary_outcomes": dict(boundary_outcomes),
        "event_counts": dict(event_counts),
        "acceptance": {
            "completed_minute_only": True,
            "pm_midpoint_before_same_direction_boundary": True,
            "pm_e_immediate_at_boundary": True,
            "pm_b_confirmation_window_1_to_10_minutes": True,
            "exact_proof_plus_10_classifier": True,
            "no_future_leakage_checks": "PASS",
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "orders_sent": False,
        },
        "limitations": [
            "Underlying NIFTY points only; option premiums, spreads, charges and quantity are excluded.",
            "Boundary counterfactual changes only entry price and keeps the actual selected exit fixed.",
            "Candidate exits remain observational while structural terminal releases the baseline lifecycle.",
            "PM may be blocked when an earlier B/E or rearm lifecycle is still structurally active.",
        ],
    }
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(arguments.output_dir / "pm-trades.csv", all_trades)
    (arguments.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )

    print(f"Sessions: {sessions} PM trades: {len(all_trades)}")
    print("OVERALL", report["overall"])
    print("BY FAMILY")
    for family, summary in report["by_family"].items():
        print(family, summary)
    print("BOUNDARY OUTCOMES", report["pm_boundary_outcomes"])
    print(f"Output: {arguments.output_dir / 'report.json'}")
    print(f"Trades: {arguments.output_dir / 'pm-trades.csv'}")
    print("Read only: live gate, services, audits, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
