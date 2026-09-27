#!/usr/bin/env python3
"""
B FAMILY — FROZEN POST-PROOF RUNNER FORWARD VALIDATOR V20

Forward-only validation starts 2026-09-29.

Frozen classifier
-----------------
A canonical Family-B event must:
1) reach +20 points before structural invalidation;
2) survive a fixed 10-minute observation window after that +20 proof.

At the +10m boundary classify:

RUNNER_STRENGTHENING iff
    net_directional_progress_from_plus20 > 0
AND directional_futures_vwap_change > 0

Otherwise:
    NORMAL_B

No numerical magnitude thresholds beyond sign.
No exit action is attached to the classification.

Goal
----
Test whether RUNNER_STRENGTHENING predicts later large B continuation on
untouched future sessions before any differentiated exit logic is designed.

Forward gate
------------
Minimum validation horizon: 20 distinct trading sessions.
All supplied sessions count, including sessions with zero B events.

Research only.
No production runtime/order changes.
Underlying NIFTY points only, not option-premium P&L.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

from market_lab import opening_candle_midpoint_framework_v1 as fw

CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")

FORWARD_START_DATE = "2026-09-29"
MIN_FORWARD_SESSIONS = 20
PROOF_POINTS = 20.0
OBSERVATION_MINUTES = 10
MILESTONES = (30, 50, 75, 100)

DEFAULT_OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "b-family-runner-forward-v20"
)


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_session_spec(value: str):
    parts = value.split("|")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            "--session must be DATE|UNDERLYING_CSV|FUTURES_CSV"
        )
    return parts[0], Path(parts[1]), Path(parts[2])


def parse_dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def minute_key(dt: datetime) -> str:
    return dt.isoformat()


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def favorable_move(direction, entry, bar):
    px = float(bar["high"]) if direction == "BULLISH" else float(bar["low"])
    return directional(direction, entry, px)


def directional_close(direction, entry, bar):
    return directional(direction, entry, float(bar["close"]))


def first_nonempty(row, names):
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return v
    return None


def load_underlying_session(path: Path, session_date: str):
    if not path.exists():
        raise FileNotFoundError(path)

    rows = fw.load_csv(path)
    by_session = fw.underlying_by_session(rows)
    minute_rows = by_session.get(session_date, [])
    if not minute_rows:
        raise ValueError(
            f"NO_UNDERLYING_ROWS_FOR_SESSION:{session_date}:{path}"
        )

    u = {}
    for r in minute_rows:
        raw_ts = r.get("timestamp")
        if isinstance(raw_ts, datetime):
            ts = raw_ts.isoformat()
        elif raw_ts:
            ts = str(raw_ts)
        else:
            # Framework-normalized rows may use datetime key "dt".
            raw_dt = r.get("dt")
            if isinstance(raw_dt, datetime):
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

    return minute_rows, u


def load_futures_session(path: Path, session_date: str):
    if not path.exists():
        raise FileNotFoundError(path)

    out = {}
    duplicate_conflicts = 0

    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            row_session = first_nonempty(
                row, ("session_date", "date", "trading_date")
            )
            if row_session and str(row_session)[:10] != session_date:
                continue

            ts = first_nonempty(
                row, ("timestamp", "ts", "datetime", "time")
            )
            if not ts:
                continue

            # If a HH:MM-only timestamp is supplied, promote to ISO.
            ts = str(ts)
            if len(ts) <= 8 and ":" in ts and "T" not in ts:
                ts = f"{session_date}T{ts}"
            if " " in ts and "T" not in ts:
                ts = ts.replace(" ", "T", 1)

            close_raw = first_nonempty(
                row, ("close", "futures_close", "ltp")
            )
            vwap_raw = first_nonempty(
                row, ("session_vwap", "vwap", "futures_vwap")
            )
            diff_raw = first_nonempty(
                row, ("diff", "vwap_diff", "futures_vwap_diff")
            )

            close = float(close_raw) if close_raw is not None else None
            vwap = float(vwap_raw) if vwap_raw is not None else None
            diff = (
                float(diff_raw)
                if diff_raw is not None
                else close - vwap
                if close is not None and vwap is not None
                else None
            )

            if diff is None:
                continue

            rec = {
                "close": close,
                "vwap": vwap,
                "diff": diff,
            }

            if ts in out and out[ts] != rec:
                duplicate_conflicts += 1
                continue
            out[ts] = rec

    if not out:
        raise ValueError(
            f"NO_FUTURES_VWAP_ROWS_FOR_SESSION:{session_date}:{path}"
        )

    if duplicate_conflicts:
        raise ValueError(
            f"FUTURES_DUPLICATE_CONFLICTS:{duplicate_conflicts}"
        )

    return out


def build_framework_events(session_date: str, minute_rows):
    """
    Reuse the frozen opening-candle midpoint framework itself.
    Empty evidence/positioning context is intentional because Family B depends
    only on the structural event fields, not attached PCR/OI context.
    """
    bars = fw.aggregate_5m(minute_rows)
    red = fw.select_reference_bar(bars, "RED")
    green = fw.select_reference_bar(bars, "GREEN")

    events = []

    if red is not None:
        events.append(
            fw.build_event(
                block="V20_FORWARD",
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
                block="V20_FORWARD",
                session_date=session_date,
                minute_rows=minute_rows,
                bar=green,
                colour="GREEN",
                evidence_idx={},
                atm_idx={},
            )
        )

    return events


def first_proof_20(ev, u, canon):
    entry_ts = ev["entry_timestamp"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])
    invalid_ts = ev.get("structural_invalidation_timestamp")
    direction = ev["direction"]

    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if not canon.is_trusted(ts):
            continue
        if invalid_ts and ts >= invalid_ts:
            break
        if favorable_move(direction, entry, u[ts]) >= PROOF_POINTS:
            return ts

    return None


def directional_vwap(direction, fut_row):
    if not fut_row or fut_row.get("diff") is None:
        return None
    d = float(fut_row["diff"])
    return d if direction == "BULLISH" else -d


def classify_at_10m(ev, u, fut, proof_ts, canon):
    end_ts = minute_key(parse_dt(proof_ts) + timedelta(minutes=OBSERVATION_MINUTES))
    invalid_ts = ev.get("structural_invalidation_timestamp")

    if not canon.is_trusted(end_ts):
        return {
            "classification_status": "INCOMPLETE",
            "incomplete_reason": "OBSERVATION_END_AFTER_TRUSTED_CUTOFF",
        }

    if invalid_ts and end_ts >= invalid_ts:
        return {
            "classification_status": "INCOMPLETE",
            "incomplete_reason": "STRUCTURAL_INVALIDATION_BEFORE_10M_BOUNDARY",
        }

    if end_ts not in u:
        return {
            "classification_status": "INCOMPLETE",
            "incomplete_reason": "MISSING_UNDERLYING_AT_10M_BOUNDARY",
        }

    proof_v = directional_vwap(ev["direction"], fut.get(proof_ts))
    end_v = directional_vwap(ev["direction"], fut.get(end_ts))

    if proof_v is None or end_v is None:
        return {
            "classification_status": "INCOMPLETE",
            "incomplete_reason": "MISSING_FUTURES_VWAP_AT_PROOF_OR_10M",
        }

    entry_ts = ev["entry_timestamp"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])

    end_move = directional_close(ev["direction"], entry, u[end_ts])
    net_progress = end_move - PROOF_POINTS
    vwap_change = end_v - proof_v

    label = (
        "RUNNER_STRENGTHENING"
        if net_progress > 0 and vwap_change > 0
        else "NORMAL_B"
    )

    return {
        "classification_status": "CLASSIFIED",
        "incomplete_reason": None,
        "classification": label,
        "observation_end_timestamp": end_ts,
        "net_directional_progress_from_plus20": net_progress,
        "proof_directional_vwap_diff": proof_v,
        "end_directional_vwap_diff": end_v,
        "directional_vwap_change": vwap_change,
    }


def milestone_timestamps(ev, u, canon):
    entry_ts = ev["entry_timestamp"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])
    invalid_ts = ev.get("structural_invalidation_timestamp")
    out = {m: None for m in MILESTONES}

    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if not canon.is_trusted(ts):
            continue
        if invalid_ts and ts >= invalid_ts:
            break

        fav = favorable_move(ev["direction"], entry, u[ts])
        for m in MILESTONES:
            if out[m] is None and fav >= m:
                out[m] = ts

    return out


def load_existing_csv(path: Path):
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


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


def boolish(v):
    return str(v).lower() in ("true", "1", "yes")


def summarize(outdir: Path, session_rows, event_rows):
    sessions = sorted({r["session_date"] for r in session_rows})
    classified = [
        r for r in event_rows
        if r.get("classification_status") == "CLASSIFIED"
    ]
    strengthening = [
        r for r in classified
        if r.get("classification") == "RUNNER_STRENGTHENING"
    ]
    normal = [
        r for r in classified
        if r.get("classification") == "NORMAL_B"
    ]

    def outcome(rows, milestone):
        eligible = [
            r for r in rows
            if r.get(f"reached_plus{milestone}") not in (None, "")
        ]
        hits = sum(boolish(r[f"reached_plus{milestone}"]) for r in eligible)
        return hits, len(eligible)

    gate = (
        "MINIMUM_20_SESSION_GATE_REACHED"
        if len(sessions) >= MIN_FORWARD_SESSIONS
        else "PENDING_MINIMUM_20_SESSIONS"
    )

    lines = [
        "B FAMILY — FROZEN POST-PROOF RUNNER FORWARD VALIDATOR V20",
        "=" * 118,
        f"Forward start date         : {FORWARD_START_DATE}",
        f"Distinct sessions recorded : {len(sessions)} / minimum {MIN_FORWARD_SESSIONS}",
        f"Forward gate               : {gate}",
        f"Canonical B events         : {len(event_rows)}",
        f"Classified after +20/+10m  : {len(classified)}",
        f"  RUNNER_STRENGTHENING     : {len(strengthening)}",
        f"  NORMAL_B                 : {len(normal)}",
        "",
        "FROZEN CLASSIFIER",
        "-" * 118,
        "At +20 proof, observe exactly 10 minutes.",
        "RUNNER_STRENGTHENING iff net progress > 0 AND directional VWAP change > 0.",
        "Otherwise NORMAL_B.",
        "",
        "FORWARD OUTCOMES",
        "-" * 118,
    ]

    for label, rows in (
        ("RUNNER_STRENGTHENING", strengthening),
        ("NORMAL_B", normal),
    ):
        lines.append(label)
        for m in MILESTONES:
            hits, n = outcome(rows, m)
            pct = 100.0 * hits / n if n else None
            lines.append(
                f"  reached +{m:<3}: {hits}/{n}"
                + (f" ({pct:.1f}%)" if pct is not None else "")
            )

    lines += [
        "",
        "GUARDS",
        "-" * 118,
        "- Sessions before 2026-09-29 are rejected.",
        "- Zero-B sessions still count toward the forward session horizon.",
        "- No tuning is allowed during the minimum 20-session gate.",
        "- No exit action is attached to the classifier.",
        "- Do not change the classifier based on interim results.",
        "- Underlying NIFTY points only; not CE/PE premium P&L.",
        "- No production/runtime/order code changed.",
    ]

    summary_path = outdir / "summary-v20.txt"
    summary_path.write_text("\n".join(lines))
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--session",
        action="append",
        type=parse_session_spec,
        required=True,
        help="DATE|UNDERLYING_CSV|FUTURES_CSV; repeat for multiple sessions",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=DEFAULT_OUTDIR,
    )
    args = parser.parse_args()

    canon = import_module(CANON, "canonical_b_v20")
    args.outdir.mkdir(parents=True, exist_ok=True)

    session_csv = args.outdir / "forward-sessions-v20.csv"
    event_csv = args.outdir / "forward-b-events-v20.csv"
    freeze_json = args.outdir / "freeze-contract-v20.json"

    freeze_contract = {
        "version": "B_FAMILY_RUNNER_FORWARD_V20",
        "frozen_on": "2026-09-28",
        "forward_start_date": FORWARD_START_DATE,
        "minimum_forward_sessions": MIN_FORWARD_SESSIONS,
        "proof_points": PROOF_POINTS,
        "observation_minutes": OBSERVATION_MINUTES,
        "runner_strengthening_rule": {
            "net_directional_progress_from_plus20": "> 0",
            "directional_vwap_change": "> 0",
            "combine": "AND",
        },
        "normal_b_rule": "otherwise",
        "exit_action_attached": False,
        "research_only": True,
    }
    freeze_json.write_text(json.dumps(freeze_contract, indent=2))

    existing_sessions = load_existing_csv(session_csv)
    existing_events = load_existing_csv(event_csv)

    session_by_date = {r["session_date"]: r for r in existing_sessions}
    event_by_key = {
        (r["session_date"], r.get("entry_timestamp", "")): r
        for r in existing_events
    }

    for session_date, underlying_path, futures_path in args.session:
        if session_date < FORWARD_START_DATE:
            raise SystemExit(
                f"STOP: {session_date} is before frozen forward start {FORWARD_START_DATE}"
            )

        minute_rows, u = load_underlying_session(
            underlying_path, session_date
        )
        fut = load_futures_session(
            futures_path, session_date
        )

        framework_events = build_framework_events(
            session_date, minute_rows
        )

        b_events = []
        for fe in framework_events:
            b = canon.family_b_for_event(fe, u, fut)
            if b:
                b_events.append(
                    canon.measure_event(dict(b), u)
                )

        session_by_date[session_date] = {
            "session_date": session_date,
            "underlying_path": str(underlying_path),
            "futures_path": str(futures_path),
            "framework_event_count": len(framework_events),
            "b_event_count": len(b_events),
            "status": "RECORDED",
        }

        # Replace any prior records for this session deterministically.
        for k in list(event_by_key):
            if k[0] == session_date:
                del event_by_key[k]

        for ev in b_events:
            proof_ts = first_proof_20(ev, u, canon)
            milestones = milestone_timestamps(ev, u, canon)

            row = {
                "session_date": session_date,
                "direction": ev["direction"],
                "origin_timestamp": ev["origin_timestamp"],
                "entry_timestamp": ev["entry_timestamp"],
                "delay_minutes": ev["delay_minutes"],
                "entry_close": ev.get("entry_close"),
                "entry_fut_vwap": ev.get("entry_fut_vwap"),
                "canonical_mfe": ev.get("mfe"),
                "canonical_mae": ev.get("mae"),
                "structural_invalidation_timestamp": ev.get(
                    "structural_invalidation_timestamp"
                ),
                "reached_plus20": proof_ts is not None,
                "proof20_timestamp": proof_ts,
            }

            if proof_ts is None:
                row.update({
                    "classification_status": "NOT_APPLICABLE_NO_PLUS20",
                    "classification": None,
                    "incomplete_reason": None,
                })
            else:
                row.update(
                    classify_at_10m(
                        ev, u, fut, proof_ts, canon
                    )
                )

            for m in MILESTONES:
                row[f"plus{m}_timestamp"] = milestones[m]
                row[f"reached_plus{m}"] = milestones[m] is not None

            event_by_key[(session_date, ev["entry_timestamp"])] = row

        print(
            f"{session_date}: "
            f"framework={len(framework_events)} "
            f"B={len(b_events)}"
        )

    final_sessions = sorted(
        session_by_date.values(),
        key=lambda r: r["session_date"],
    )
    final_events = sorted(
        event_by_key.values(),
        key=lambda r: (
            r["session_date"],
            r.get("entry_timestamp") or "",
        ),
    )

    write_csv(session_csv, final_sessions)
    write_csv(event_csv, final_events)

    summarize(args.outdir, final_sessions, final_events)

    print()
    print("SESSIONS CSV :", session_csv)
    print("EVENTS CSV   :", event_csv)
    print("FREEZE JSON  :", freeze_json)
    print("SUMMARY      :", args.outdir / "summary-v20.txt")


if __name__ == "__main__":
    main()
