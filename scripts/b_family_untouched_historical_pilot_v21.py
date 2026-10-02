#!/usr/bin/env python3
"""
B FAMILY — UNTOUCHED HISTORICAL PILOT V21

Purpose
-------
Run the already-frozen Family-B detector on five untouched Jan-2025 sessions.

This is NOT tuning.
This is NOT production logic.
No Family-B rules are changed.

Inputs
------
Underlying:
  data/historical-evidence/b-v21-pilot-underlying-2025-01-13-to-17.csv

Futures/VWAP:
  data/historical-evidence/b-v21-pilot-futures-vwap-2025-01-13-to-17.csv

Expected sessions:
  2025-01-13 .. 2025-01-17 (5 sessions)

Method
------
1. Build frozen RED/GREEN opening midpoint framework events from the raw
   underlying 1m data.
2. Reconstruct futures directional VWAP diff as:
      close - session_vwap
3. Run frozen canonical Family-B detector unchanged.
4. Measure canonical MFE/MAE unchanged.
5. Report all sessions including zero-B sessions.

No exit model is evaluated in V21.
No post-+20 runner classifier is evaluated in V21 yet.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from collections import defaultdict
from pathlib import Path

from market_lab import opening_candle_midpoint_framework_v1 as fw

CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")

UNDERLYING_CSV = Path(
    "data/historical-evidence/"
    "b-v21-pilot-underlying-2025-01-13-to-17.csv"
)
FUTURES_CSV = Path(
    "data/historical-evidence/"
    "b-v21-pilot-futures-vwap-2025-01-13-to-17.csv"
)

SESSIONS = [
    "2025-01-13",
    "2025-01-14",
    "2025-01-15",
    "2025-01-16",
    "2025-01-17",
]

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "b-family-untouched-historical-pilot-v21"
)

EVENTS_CSV = OUTDIR / "b-events-v21.csv"
SESSIONS_CSV = OUTDIR / "session-summary-v21.csv"
REPORT_JSON = OUTDIR / "report-v21.json"
SUMMARY_TXT = OUTDIR / "summary-v21.txt"


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_underlying():
    rows = fw.load_csv(UNDERLYING_CSV)
    by_session = fw.underlying_by_session(rows)

    minute_maps = {}
    for session, minute_rows in by_session.items():
        u = {}
        for r in minute_rows:
            raw_ts = r.get("timestamp")
            if hasattr(raw_ts, "isoformat"):
                ts = raw_ts.isoformat()
            elif raw_ts:
                ts = str(raw_ts)
            else:
                raw_dt = r.get("dt")
                if hasattr(raw_dt, "isoformat"):
                    ts = raw_dt.isoformat()
                elif raw_dt:
                    ts = str(raw_dt)
                else:
                    raise ValueError("UNDERLYING_ROW_MISSING_TIMESTAMP")

            u[ts] = {
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("volume") or 0.0),
            }

        minute_maps[session] = u

    return by_session, minute_maps


def load_futures():
    by_session = defaultdict(dict)
    conflicts = 0

    with FUTURES_CSV.open(newline="") as fh:
        for r in csv.DictReader(fh):
            session = r["session_date"]
            ts = r["timestamp"]

            close = float(r["close"])
            vwap = (
                float(r["session_vwap"])
                if r.get("session_vwap") not in (None, "")
                else None
            )
            diff = close - vwap if vwap is not None else None

            rec = {
                "close": close,
                "vwap": vwap,
                "diff": diff,
                "volume": (
                    float(r["volume"])
                    if r.get("volume") not in (None, "")
                    else None
                ),
            }

            if ts in by_session[session] and by_session[session][ts] != rec:
                conflicts += 1
                continue

            by_session[session][ts] = rec

    return dict(by_session), conflicts


def build_framework(session_date, minute_rows):
    bars = fw.aggregate_5m(minute_rows)
    red = fw.select_reference_bar(bars, "RED")
    green = fw.select_reference_bar(bars, "GREEN")

    events = []

    if red is not None:
        events.append(
            fw.build_event(
                block="V21_UNTOUCHED_PILOT",
                session_date=session_date,
                minute_rows=minute_rows,
                bar=red,
                colour="RED",
                evidence_idx={},
                atm_idx={},
            )
        )

    if green is not None:
        events.append(
            fw.build_event(
                block="V21_UNTOUCHED_PILOT",
                session_date=session_date,
                minute_rows=minute_rows,
                bar=green,
                colour="GREEN",
                evidence_idx={},
                atm_idx={},
            )
        )

    return events


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("")
        return

    fields = []
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)

    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    print("B FAMILY — UNTOUCHED HISTORICAL PILOT V21")
    print("=" * 118)

    canon = import_module(CANON, "canonical_b_v21")

    by_session_rows, underlying = load_underlying()
    futures, fut_conflicts = load_futures()

    if fut_conflicts:
        raise SystemExit(
            f"STOP: futures duplicate conflicts={fut_conflicts}"
        )

    session_rows = []
    event_rows = []

    for session in SESSIONS:
        minute_rows = by_session_rows.get(session, [])
        u = underlying.get(session, {})
        fut = futures.get(session, {})

        if len(u) != 375:
            raise SystemExit(
                f"STOP: {session} underlying rows={len(u)} expected=375"
            )

        if len(fut) != 375:
            raise SystemExit(
                f"STOP: {session} futures rows={len(fut)} expected=375"
            )

        if any(v.get("diff") is None for v in fut.values()):
            raise SystemExit(
                f"STOP: {session} futures VWAP diff missing"
            )

        framework = build_framework(session, minute_rows)

        detected = []
        for e in framework:
            b = canon.family_b_for_event(e, u, fut)
            if b:
                measured = canon.measure_event(dict(b), u)
                detected.append(measured)
                event_rows.append(measured)

        session_rows.append({
            "session_date": session,
            "underlying_rows": len(u),
            "futures_rows": len(fut),
            "framework_event_count": len(framework),
            "b_event_count": len(detected),
        })

        print()
        print(session)
        print("-" * 118)
        print(
            f"underlying={len(u)} futures={len(fut)} "
            f"framework={len(framework)} B={len(detected)}"
        )

        for e in framework:
            print(
                f"  {e.get('setup_type')} "
                f"status={e.get('status')} "
                f"ref={str(e.get('reference_start'))[11:16]}-"
                f"{str(e.get('reference_end'))[11:16]} "
                f"midBreak={str(e.get('midpoint_break_timestamp'))[11:16] if e.get('midpoint_break_timestamp') else '-'} "
                f"boundaryBreak={str(e.get('boundary_break_timestamp'))[11:16] if e.get('boundary_break_timestamp') else '-'} "
                f"primary={e.get('primary_outcome')}"
            )

        if not detected:
            print("  Family B: NO_B_EVENT")
        else:
            for b in detected:
                print(
                    "  Family B: "
                    f"{b['direction']} "
                    f"entry={b['entry_timestamp'][11:16]} "
                    f"origin={b['origin_timestamp'][11:16]} "
                    f"delay={b['delay_minutes']} "
                    f"entry_close={b.get('entry_close')} "
                    f"entry_fut_vwap={b.get('entry_fut_vwap')} "
                    f"MFE={b.get('mfe')} "
                    f"MAE={b.get('mae')} "
                    f"invalid={str(b.get('structural_invalidation_timestamp'))[11:16] if b.get('structural_invalidation_timestamp') else '-'}"
                )

    report = {
        "version": "B_FAMILY_UNTOUCHED_HISTORICAL_PILOT_V21",
        "sessions": SESSIONS,
        "session_count": len(SESSIONS),
        "b_event_count": len(event_rows),
        "futures_duplicate_conflicts": fut_conflicts,
        "no_tuning": True,
        "family_b_detector_changed": False,
        "production_code_changed": False,
        "session_summary": session_rows,
        "events": event_rows,
    }

    lines = [
        "B FAMILY — UNTOUCHED HISTORICAL PILOT V21",
        "=" * 118,
        f"sessions={len(SESSIONS)}",
        f"framework_events={sum(r['framework_event_count'] for r in session_rows)}",
        f"b_events={len(event_rows)}",
        f"futures_duplicate_conflicts={fut_conflicts}",
        "",
        "SESSION COUNTS",
        "-" * 118,
    ]

    for r in session_rows:
        lines.append(
            f"{r['session_date']} "
            f"underlying={r['underlying_rows']} "
            f"futures={r['futures_rows']} "
            f"framework={r['framework_event_count']} "
            f"B={r['b_event_count']}"
        )

    lines += [
        "",
        "B EVENTS",
        "-" * 118,
    ]

    if not event_rows:
        lines.append("NO_B_EVENTS")
    else:
        for b in event_rows:
            lines.append(
                f"{b['session_date']} {b['direction']} "
                f"entry={b['entry_timestamp']} "
                f"origin={b['origin_timestamp']} "
                f"delay={b['delay_minutes']} "
                f"entry_close={b.get('entry_close')} "
                f"entry_fut_vwap={b.get('entry_fut_vwap')} "
                f"MFE={b.get('mfe')} "
                f"MAE={b.get('mae')} "
                f"invalid={b.get('structural_invalidation_timestamp')}"
            )

    lines += [
        "",
        "GUARDS",
        "-" * 118,
        "- Frozen canonical Family-B detector imported unchanged.",
        "- Frozen opening midpoint framework logic reused unchanged.",
        "- Futures VWAP is prospective cumulative session VWAP from the existing collector.",
        "- All five sessions are before the original 2025-12-12 research universe.",
        "- Zero-B sessions are retained.",
        "- No exit rule tested.",
        "- No runner classifier tested.",
        "- No production/runtime/order code changed.",
    ]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENTS_CSV, event_rows)
    write_csv(SESSIONS_CSV, session_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str))
    SUMMARY_TXT.write_text("\n".join(lines))

    print()
    print("\n".join(lines))
    print()
    print("EVENTS CSV :", EVENTS_CSV)
    print("SESSIONS   :", SESSIONS_CSV)
    print("REPORT JSON:", REPORT_JSON)
    print("SUMMARY    :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
