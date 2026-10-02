#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import json
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from market_lab.midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1

V55 = Path("scripts/midpoint_v55_boundary_selection_replay.py")
V52 = Path("scripts/midpoint_mature_boundary_robustness_v52_1.py")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "midpoint-v57-full-historical-be-lifecycle"
)
SESSION_CSV = OUTDIR / "session-summary-v57.csv"
TRADE_CSV = OUTDIR / "trade-lifecycle-v57.csv"
EVENT_CSV = OUTDIR / "audit-events-v57.csv"
REPORT_JSON = OUTDIR / "report-v57.json"
SUMMARY_TXT = OUTDIR / "summary-v57.txt"

EXPECTED_OWNERSHIP = {
    "B1_2024-08-16_to_2025-02-05": {"E": 51, "B": 30, "OTHER_FRESH_A": 101},
    "B2_2025-02-06_to_2025-07-16": {"E": 61, "B": 41, "OTHER_FRESH_A": 70},
    "B3_2025-07-17_to_2025-12-11": {"E": 56, "B": 39, "OTHER_FRESH_A": 82},
    "B4_2025-12-12_to_2026-09-08": {"E": 103, "B": 78, "OTHER_FRESH_A": 148},
}


class DummySources:
    """_process_minute replay does not call provider methods."""
    pass


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def candle(ts: str, row: dict):
    return SimpleNamespace(
        timestamp=dt(ts),
        open=float(row.get("open", row["close"])),
        high=float(row.get("high", row["close"])),
        low=float(row.get("low", row["close"])),
        close=float(row["close"]),
        volume=float(row.get("volume", 0.0) or 0.0),
    )


def directional_points(direction: str, entry: float, exit_: float) -> float:
    if direction == "BULLISH":
        return exit_ - entry
    if direction == "BEARISH":
        return entry - exit_
    raise ValueError(direction)


def load_audit(path: Path):
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def replay_session(session_date: str, u_day: dict, f_day: dict):
    with tempfile.TemporaryDirectory(prefix="midpoint-v57-") as td:
        audit_path = Path(td) / "audit.jsonl"
        c = MidpointLiveShadowCoordinatorV1(
            market_sources=DummySources(),
            audit_path=audit_path,
        )
        c._reset_session(dt(session_date + "T09:15:00+05:30").date())

        underlying_by_ts = {
            dt(ts): candle(ts, row)
            for ts, row in u_day.items()
        }

        common = sorted(set(u_day).intersection(f_day), key=dt)
        for ts_s in common:
            ts = dt(ts_s)
            if ts.time() < dt(session_date + "T09:15:00+05:30").time():
                continue
            u = underlying_by_ts[ts]
            f = f_day[ts_s]
            c._process_minute(
                ts=ts,
                underlying=u,
                futures_close=float(f["close"]),
                futures_vwap=float(f["vwap"]),
                underlying_by_ts=underlying_by_ts,
            )

        rows = load_audit(audit_path)
        state = c.state
        open_active = False
        active_family = None
        if state is not None and state.active_reference_type is not None:
            rr = state.references.get(state.active_reference_type)
            if rr and rr.runtime.lifecycle is not None and not rr.closed:
                open_active = True
                active_family = rr.runtime.family.value

        return rows, open_active, active_family


def normalize_event(block_name: str, row: dict):
    ev = dict(row)
    ev["block"] = block_name
    ev["evidence_json"] = json.dumps(ev.pop("evidence", {}), sort_keys=True)
    return ev


def reconstruct_lifecycles(block_name: str, session_date: str, rows: list[dict], open_active: bool):
    entries = [
        (i, r) for i, r in enumerate(rows)
        if r.get("event_type") in ("B_ENTRY", "E_ENTRY")
    ]
    out = []

    for seq, (idx, entry) in enumerate(entries, start=1):
        family = entry["family"]
        direction = entry["direction"]
        entry_ts = entry["event_timestamp"]
        entry_px = float(entry["underlying_price"])

        # Lifecycle ends at the first STRUCTURAL_TERMINAL after this entry,
        # or immediately before the next strategy entry if no terminal is present.
        next_idx = entries[seq][0] if seq < len(entries) else len(rows)
        segment = rows[idx:next_idx]
        terminal = next(
            (r for r in segment if r.get("event_type") == "STRUCTURAL_TERMINAL"),
            None,
        )
        rescue = next(
            (r for r in segment if r.get("event_type") == "CAP20_RESCUE_TRIGGERED"),
            None,
        )
        reentry = next(
            (r for r in segment if r.get("event_type") == "POST_CAP20_REENTRY_TRIGGERED"),
            None,
        )
        plus20 = next(
            (r for r in segment if r.get("event_type") == "PLUS20_PROOF"),
            None,
        )
        classifier = next(
            (r for r in segment if r.get("event_type") == "RUNNER_CLASSIFICATION"),
            None,
        )
        classifier_unavail = next(
            (r for r in segment if r.get("event_type") == "RUNNER_CLASSIFICATION_UNAVAILABLE"),
            None,
        )
        degraded = next(
            (r for r in segment if r.get("event_type") == "DEGRADED_STARTED"),
            None,
        )
        recovered = next(
            (r for r in segment if r.get("event_type") == "DEGRADED_TARGET_RECOVERED"),
            None,
        )

        leg1_exit = rescue or terminal
        leg1_exit_reason = (
            "CAP20_RESCUE"
            if rescue is not None
            else ("STRUCTURAL_TERMINAL" if terminal is not None else "OPEN_AT_SESSION_END")
        )
        leg1_points = None
        if leg1_exit is not None and leg1_exit.get("underlying_price") is not None:
            leg1_points = directional_points(
                direction, entry_px, float(leg1_exit["underlying_price"])
            )

        leg2_points = None
        if reentry is not None and terminal is not None:
            leg2_points = directional_points(
                direction,
                float(reentry["underlying_price"]),
                float(terminal["underlying_price"]),
            )

        realized_shadow_points = None
        if rescue is None:
            realized_shadow_points = leg1_points
        elif reentry is None:
            realized_shadow_points = leg1_points
        elif terminal is not None:
            realized_shadow_points = (leg1_points or 0.0) + (leg2_points or 0.0)

        out.append({
            "block": block_name,
            "session_date": session_date,
            "lifecycle_seq": seq,
            "family": family,
            "direction": direction,
            "entry_timestamp": entry_ts,
            "entry_price": entry_px,
            "plus20": plus20 is not None,
            "plus20_timestamp": plus20["event_timestamp"] if plus20 else "",
            "runner_classified": classifier is not None,
            "runner_result": classifier.get("result", "") if classifier else "",
            "classifier_unavailable": classifier_unavail is not None,
            "degraded": degraded is not None,
            "degraded_timestamp": degraded["event_timestamp"] if degraded else "",
            "recovered": recovered is not None,
            "cap20_rescue": rescue is not None,
            "cap20_timestamp": rescue["event_timestamp"] if rescue else "",
            "reentry": reentry is not None,
            "reentry_timestamp": reentry["event_timestamp"] if reentry else "",
            "structural_terminal": terminal is not None,
            "terminal_timestamp": terminal["event_timestamp"] if terminal else "",
            "terminal_reason": terminal.get("reason", "") if terminal else "",
            "leg1_exit_reason": leg1_exit_reason,
            "leg1_directional_points": leg1_points,
            "leg2_directional_points": leg2_points,
            "realized_shadow_points": realized_shadow_points,
            "open_at_session_end": terminal is None and open_active,
        })
    return out


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        path.write_text("")
        return
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def pct(n, d):
    return round(100.0 * n / d, 2) if d else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def summarize_trades(trades):
    pts = [r["realized_shadow_points"] for r in trades if r["realized_shadow_points"] is not None]
    return {
        "entries": len(trades),
        "B_entries": sum(r["family"] == "B" for r in trades),
        "E_entries": sum(r["family"] == "E" for r in trades),
        "plus20": sum(r["plus20"] for r in trades),
        "plus20_pct": pct(sum(r["plus20"] for r in trades), len(trades)),
        "runner_classified": sum(r["runner_classified"] for r in trades),
        "runner_strengthening": sum(r["runner_result"] == "RUNNER_STRENGTHENING" for r in trades),
        "classifier_unavailable": sum(r["classifier_unavailable"] for r in trades),
        "degraded": sum(r["degraded"] for r in trades),
        "cap20_rescue": sum(r["cap20_rescue"] for r in trades),
        "reentry": sum(r["reentry"] for r in trades),
        "structural_terminal": sum(r["structural_terminal"] for r in trades),
        "open_at_session_end": sum(r["open_at_session_end"] for r in trades),
        "realized_points_mean": mean(pts),
        "realized_points_median": median(pts),
        "realized_points_positive": sum(x > 0 for x in pts),
        "realized_points_positive_pct": pct(sum(x > 0 for x in pts), len(pts)),
        "realized_points_sum": sum(pts) if pts else None,
    }


def main():
    v55 = import_module(V55, "v55_for_v57")
    v52 = import_module(V52, "v52_for_v57")
    canon = import_module(CANON, "canon_for_v57")

    print("MIDPOINT V57 — FULL HISTORICAL B+E COORDINATOR/LIFECYCLE REPLAY")
    print("=" * 100)
    print("Uses current live coordinator logic offline via _process_minute")
    print("No runtime/live mutation")
    print()

    all_events = []
    all_trades = []
    session_rows = []
    block_reports = {}

    for block in v52.BLOCKS:
        u, fut, framework = v55.load_block(block, v52, canon)
        sessions = sorted(set(u).intersection(fut))
        ownership = Counter()
        block_trades = []
        block_sessions = []

        for i, d in enumerate(sessions, start=1):
            rows, open_active, active_family = replay_session(d, u[d], fut[d])

            for r in rows:
                if r.get("event_type") == "BOUNDARY_CLASSIFIED":
                    ownership[str(r.get("result"))] += 1

            trades = reconstruct_lifecycles(
                block["name"], d, rows, open_active
            )
            all_trades.extend(trades)
            block_trades.extend(trades)
            all_events.extend(normalize_event(block["name"], r) for r in rows)

            sr = {
                "block": block["name"],
                "session_date": d,
                "boundary_classified": sum(r.get("event_type") == "BOUNDARY_CLASSIFIED" for r in rows),
                "owner_E": sum(
                    r.get("event_type") == "BOUNDARY_CLASSIFIED" and r.get("result") == "E"
                    for r in rows
                ),
                "owner_B": sum(
                    r.get("event_type") == "BOUNDARY_CLASSIFIED" and r.get("result") == "B"
                    for r in rows
                ),
                "owner_OTHER_FRESH_A": sum(
                    r.get("event_type") == "BOUNDARY_CLASSIFIED" and r.get("result") == "OTHER_FRESH_A"
                    for r in rows
                ),
                "B_entries": sum(t["family"] == "B" for t in trades),
                "E_entries": sum(t["family"] == "E" for t in trades),
                "plus20": sum(t["plus20"] for t in trades),
                "cap20_rescue": sum(t["cap20_rescue"] for t in trades),
                "reentry": sum(t["reentry"] for t in trades),
                "open_at_session_end": open_active,
                "active_family_at_session_end": active_family or "",
            }
            session_rows.append(sr)
            block_sessions.append(sr)

        actual = {
            "E": ownership["E"],
            "B": ownership["B"],
            "OTHER_FRESH_A": ownership["OTHER_FRESH_A"],
        }
        expected = EXPECTED_OWNERSHIP[block["name"]]
        parity = actual == expected
        if not parity:
            raise SystemExit(
                f"STOP: ownership parity failed {block['name']} actual={actual} expected={expected}"
            )

        trade_summary = summarize_trades(block_trades)
        block_reports[block["name"]] = {
            "sessions": len(sessions),
            "framework_events": len(framework),
            "ownership_actual": actual,
            "ownership_expected": expected,
            "ownership_parity": parity,
            "trade_summary": trade_summary,
            "zero_entry_sessions": sum(
                (r["B_entries"] + r["E_entries"]) == 0 for r in block_sessions
            ),
        }

        print(block["name"])
        print("-" * 100)
        print(f"sessions={len(sessions)} framework_events={len(framework)}")
        print(f"ownership actual={actual}")
        print(f"ownership parity={'PASS' if parity else 'FAIL'}")
        print(f"trades={trade_summary}")
        print()

    combined = summarize_trades(all_trades)
    zero_entry_sessions = sum(
        (r["B_entries"] + r["E_entries"]) == 0 for r in session_rows
    )
    multi_entry_sessions = sum(
        (r["B_entries"] + r["E_entries"]) > 1 for r in session_rows
    )

    report = {
        "model": "MIDPOINT_V57_FULL_HISTORICAL_BE_LIFECYCLE_REPLAY",
        "scope": "FULL_OFFLINE_REPLAY_OF_CURRENT_LIVE_COORDINATOR",
        "safety": {
            "live_mutation": False,
            "orders": False,
            "quantity": None,
        },
        "block_reports": block_reports,
        "combined_trade_summary": combined,
        "sessions_total": len(session_rows),
        "zero_entry_sessions": zero_entry_sessions,
        "multi_entry_sessions": multi_entry_sessions,
        "acceptance": {
            "ownership_parity_all_blocks": all(
                r["ownership_parity"] for r in block_reports.values()
            ),
            "one_active_reference_enforced_by_live_coordinator": True,
            "shared_management_path_used_for_B_and_E": True,
        },
        "notes": [
            "Replay calls MidpointLiveShadowCoordinatorV1._process_minute with historical exact-minute underlying and precomputed futures VWAP.",
            "No nearest-minute substitution or interpolation is used.",
            "CAP20 rescue is treated as first-leg shadow exit.",
            "A post-rescue reentry creates a second shadow leg; second rescue remains disabled.",
            "If no structural terminal is emitted before session end, lifecycle is reported open_at_session_end rather than inventing an exit.",
            "Realized shadow points are underlying directional points, not option P&L.",
        ],
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENT_CSV, all_events)
    write_csv(TRADE_CSV, all_trades)
    write_csv(SESSION_CSV, session_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True))

    lines = []
    lines.append("MIDPOINT V57 — FULL HISTORICAL B+E COORDINATOR/LIFECYCLE REPLAY")
    lines.append("=" * 100)
    lines.append("Offline replay of current live coordinator; no live mutation.")
    lines.append("")
    for name, br in block_reports.items():
        lines.append(name)
        lines.append("-" * 100)
        lines.append(
            f"sessions={br['sessions']} framework_events={br['framework_events']} "
            f"ownership_parity=PASS actual={br['ownership_actual']}"
        )
        ts = br["trade_summary"]
        lines.append(
            f"entries={ts['entries']} B={ts['B_entries']} E={ts['E_entries']} "
            f"+20={ts['plus20']} ({ts['plus20_pct']}%) "
            f"runner_strengthening={ts['runner_strengthening']} "
            f"degraded={ts['degraded']} cap20={ts['cap20_rescue']} reentry={ts['reentry']}"
        )
        lines.append(
            f"terminal={ts['structural_terminal']} open_session_end={ts['open_at_session_end']} "
            f"realized points mean/median={ts['realized_points_mean']}/{ts['realized_points_median']} "
            f"positive={ts['realized_points_positive']} ({ts['realized_points_positive_pct']}%) "
            f"sum={ts['realized_points_sum']}"
        )
        lines.append(f"zero-entry sessions={br['zero_entry_sessions']}")
        lines.append("")

    lines.append("COMBINED")
    lines.append("-" * 100)
    lines.append(
        f"sessions={len(session_rows)} zero-entry={zero_entry_sessions} "
        f"multi-entry={multi_entry_sessions}"
    )
    lines.append(
        f"entries={combined['entries']} B={combined['B_entries']} E={combined['E_entries']} "
        f"+20={combined['plus20']} ({combined['plus20_pct']}%)"
    )
    lines.append(
        f"runner_classified={combined['runner_classified']} "
        f"runner_strengthening={combined['runner_strengthening']} "
        f"classifier_unavailable={combined['classifier_unavailable']} "
        f"degraded={combined['degraded']} cap20={combined['cap20_rescue']} "
        f"reentry={combined['reentry']}"
    )
    lines.append(
        f"terminal={combined['structural_terminal']} "
        f"open_session_end={combined['open_at_session_end']}"
    )
    lines.append(
        f"realized underlying directional points mean/median="
        f"{combined['realized_points_mean']}/{combined['realized_points_median']} "
        f"positive={combined['realized_points_positive']} "
        f"({combined['realized_points_positive_pct']}%) "
        f"sum={combined['realized_points_sum']}"
    )
    lines.append("")
    lines.append("ACCEPTANCE")
    lines.append("- ownership parity all four historical blocks: PASS")
    lines.append("- one-active-reference behavior: live coordinator")
    lines.append("- shared B/E management: live coordinator")
    lines.append("- no order execution / no option P&L")
    lines.append("")
    lines.append(f"SESSION CSV = {SESSION_CSV}")
    lines.append(f"TRADE CSV   = {TRADE_CSV}")
    lines.append(f"EVENT CSV   = {EVENT_CSV}")
    lines.append(f"REPORT JSON = {REPORT_JSON}")
    lines.append(f"SUMMARY     = {SUMMARY_TXT}")

    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
