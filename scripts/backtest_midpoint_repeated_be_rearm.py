#!/usr/bin/env python3
"""Research-only replay of repeated B/E midpoint revalidation.

The live coordinator is not modified.  Internally the existing C detector is
extended recursively, then every resulting C entry is relabelled by its actual
canonical boundary owner as B_REARM or E_REARM with a generation number.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from market_lab.midpoint_strategy.config import MidpointShadowConfig
from market_lab.midpoint_strategy.extended_entry_candidates import CRearmCandidate
from market_lab.midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1
from market_lab.midpoint_strategy.models import MidpointFamily
from market_lab.midpoint_strategy.runtime import MidpointFamilyBRuntime


CURRENT = Path("scripts/backtest_midpoint_current_strategy.py")
V55 = Path("scripts/midpoint_v55_boundary_selection_replay.py")
V52 = Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
DEFAULT_OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-repeated-be-rearm-v1"
)


class DummySources:
    pass


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepeatedBERearmCoordinator(MidpointLiveShadowCoordinatorV1):
    """Allow each completed B/E-derived generation to arm one next generation."""

    def _candidate_key(self, rr) -> str:
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None:
            raise ValueError("rearm candidate requires lifecycle")
        return (
            f"{rr.reference.reference_type}:"
            f"{lifecycle.entry_timestamp.isoformat()}"
        )

    def _ensure_c_rearm(self, rr):
        if not self.config.family_c_enabled or self.state is None:
            return None
        lifecycle = rr.runtime.lifecycle
        if lifecycle is None or rr.runtime.family not in {
            MidpointFamily.B,
            MidpointFamily.E,
            MidpointFamily.C,
        }:
            return None
        key = self._candidate_key(rr)
        candidate = self.state.c_rearms.get(key)
        if candidate is None:
            candidate = CRearmCandidate(
                reference=rr.reference,
                origin_family=rr.runtime.family.value,
                origin_entry_timestamp=lifecycle.entry_timestamp,
            )
            self.state.c_rearms[key] = candidate
            self.state.c_runtimes[key] = MidpointFamilyBRuntime(
                reference=rr.reference,
                family=MidpointFamily.C,
            )
        return candidate

    def _observe_c_touch(self, rr, obs, underlying) -> None:
        candidate = self._ensure_c_rearm(rr)
        if candidate is None or self.state is None:
            return
        key = self._candidate_key(rr)
        action = candidate.observe_active_bar(
            timestamp=datetime.fromisoformat(obs.timestamp),
            high=self._float(underlying, "high"),
            low=self._float(underlying, "low"),
        )
        if action is None:
            return
        runtime = self.state.c_runtimes[key]
        self.engine._audit(
            runtime=runtime,
            timestamp=obs.timestamp,
            event_type=action.event_type,
            direction=action.direction,
            result="ARMED",
            reason=action.reason,
            observation=obs,
            evidence={
                "origin_family": candidate.origin_family,
                "origin_entry_timestamp": (
                    candidate.origin_entry_timestamp.isoformat()
                ),
                "repeated_be_rearm_research": True,
                "candidate_only": True,
                "order_sent": False,
            },
        )


def replay_session(current, session_date, underlying, futures):
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
    with tempfile.TemporaryDirectory(prefix="midpoint-repeated-rearm-") as temp:
        audit_path = Path(temp) / "audit.jsonl"
        coordinator = RepeatedBERearmCoordinator(
            market_sources=DummySources(),
            audit_path=audit_path,
            config=config,
        )
        coordinator._reset_session(
            current.dt(session_date + "T09:15:00+05:30").date()
        )
        underlying_by_ts = {
            current.dt(timestamp): current.candle(timestamp, row)
            for timestamp, row in underlying.items()
        }
        for timestamp in sorted(set(underlying).intersection(futures), key=current.dt):
            moment = current.dt(timestamp)
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
        return current.load_audit(audit_path)


def relabel_trades(trades: list[dict], audit: list[dict]) -> list[dict]:
    owner_by_timestamp = {
        row["event_timestamp"]: (row.get("evidence") or {}).get(
            "qualification_owner"
        )
        for row in audit
        if row.get("event_type") == "C_ENTRY"
    }
    generation_by_reference = defaultdict(int)
    last_family_by_reference = {}
    output = []
    for trade in sorted(trades, key=lambda row: row["entry_timestamp"]):
        reference = str(trade["reference_type"])
        original_family = trade["family"]
        if original_family in {"B", "E"}:
            family = original_family
            generation = 0
            entry_kind = f"{family}_ORIGIN"
        else:
            owner = owner_by_timestamp.get(trade["entry_timestamp"])
            if owner not in {"B", "E"}:
                raise AssertionError(
                    f"missing B/E qualification owner for {trade['entry_timestamp']}"
                )
            generation_by_reference[reference] += 1
            family = owner
            generation = generation_by_reference[reference]
            entry_kind = f"{family}_REARM"
        origin_family = last_family_by_reference.get(reference)
        last_family_by_reference[reference] = family
        output.append({
            **trade,
            "internal_replay_family": original_family,
            "family": family,
            "generation": generation,
            "entry_kind": entry_kind,
            "origin_family": origin_family,
            "rearm_type": (
                "MIDPOINT_TOUCH_REVALIDATION" if generation else "ORIGINAL"
            ),
        })
    return output


def metric(rows: list[dict]) -> dict:
    completed = [row for row in rows if row["selected_exit_points"] is not None]
    points = [float(row["selected_exit_points"]) for row in completed]
    return {
        "entries": len(rows),
        "completed": len(completed),
        "unresolved": len(rows) - len(completed),
        "sum_points": sum(points),
        "mean_points": statistics.mean(points) if points else None,
        "median_points": statistics.median(points) if points else None,
        "positive": sum(value > 0 for value in points),
        "negative": sum(value < 0 for value in points),
        "win_rate_pct": (
            100.0 * sum(value > 0 for value in points) / len(points)
            if points else None
        ),
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
    fields = list(rows[0])
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTDIR)
    arguments = parser.parse_args()
    current = import_module(CURRENT, "repeated_rearm_current")
    v55 = import_module(V55, "repeated_rearm_v55")
    v52 = import_module(V52, "repeated_rearm_v52")
    canon = import_module(CANON, "repeated_rearm_canon")

    all_trades = []
    parity_rows = []
    sessions = 0
    for block in v52.BLOCKS:
        underlying, futures, _ = v55.load_block(block, v52, canon)
        for session_date in sorted(set(underlying).intersection(futures)):
            sessions += 1
            repeated_audit = replay_session(
                current,
                session_date,
                underlying[session_date],
                futures[session_date],
            )
            repeated = current.reconstruct_session(
                block=block["name"],
                session_date=session_date,
                rows=repeated_audit,
                underlying=underlying[session_date],
            )
            repeated = relabel_trades(repeated, repeated_audit)
            all_trades.extend(repeated)

            current_audit = current.replay_session(
                session_date,
                underlying[session_date],
                futures[session_date],
            )
            expected = [
                (row["event_timestamp"], (row.get("evidence") or {}).get("qualification_owner"))
                for row in current_audit if row.get("event_type") == "C_ENTRY"
            ]
            observed = [
                (row["entry_timestamp"], row["family"])
                for row in repeated if row["generation"] == 1
            ]
            parity_rows.append({
                "session_date": session_date,
                "expected_current_c": json.dumps(expected),
                "observed_generation_1": json.dumps(observed),
                "parity": expected == observed,
            })

    generation_counts = Counter(int(row["generation"]) for row in all_trades)
    rearm_rows = [row for row in all_trades if row["generation"] > 0]
    session_totals = defaultdict(float)
    for row in all_trades:
        if row["selected_exit_points"] is not None:
            session_totals[row["session_date"]] += float(row["selected_exit_points"])
    report = {
        "model": "MIDPOINT_REPEATED_BE_REARM_RESEARCH_V1",
        "sessions": sessions,
        "rule": {
            "arm": "intrabar touch of original midpoint during active generation",
            "release": "origin generation structurally closed",
            "trigger": "later completed fresh close beyond original boundary",
            "classification": "canonical B/E boundary classifier",
            "repeat": "each entered generation may arm exactly one next generation",
            "same_candle_reentry": False,
        },
        "overall": metric(all_trades),
        "rearms_only": metric(rearm_rows),
        "by_family": grouped(all_trades, "family"),
        "by_generation": grouped(all_trades, "generation"),
        "by_entry_kind": grouped(all_trades, "entry_kind"),
        "by_exit_policy": grouped(all_trades, "selected_exit_policy"),
        "generation_counts": dict(sorted(generation_counts.items())),
        "maximum_generation": max(generation_counts, default=0),
        "sessions_with_rearm": len({row["session_date"] for row in rearm_rows}),
        "first_generation_parity": {
            "sessions": len(parity_rows),
            "passed": sum(row["parity"] for row in parity_rows),
            "failed": sum(not row["parity"] for row in parity_rows),
        },
        "session_result": {
            "sum": sum(session_totals.values()),
            "mean": statistics.mean(session_totals.values()) if session_totals else None,
            "positive": sum(value > 0 for value in session_totals.values()),
            "negative": sum(value < 0 for value in session_totals.values()),
            "worst": min(session_totals.values()) if session_totals else None,
            "best": max(session_totals.values()) if session_totals else None,
        },
        "safety": {
            "research_only": True,
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "quantity": None,
            "order_sent": False,
            "live_runtime_modified": False,
        },
        "limitations": [
            "Underlying NIFTY points only; option premiums, spreads, charges and quantity excluded.",
            "Rearm generations retain the original reference midpoint and boundary.",
            "Candidate exits remain observational while structural terminal releases the active lifecycle.",
        ],
    }
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(arguments.output_dir / "trades.csv", all_trades)
    write_csv(arguments.output_dir / "first-generation-parity.csv", parity_rows)
    (arguments.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(f"Sessions: {sessions} trades: {len(all_trades)} rearms: {len(rearm_rows)}")
    print("OVERALL", report["overall"])
    print("REARMS", report["rearms_only"])
    print("GENERATIONS", report["generation_counts"])
    print("PARITY", report["first_generation_parity"])
    print("BY FAMILY", report["by_family"])
    print("Output:", arguments.output_dir / "report.json")
    print("Research only: live coordinator, services, orders and quantity untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
