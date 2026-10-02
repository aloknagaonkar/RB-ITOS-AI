#!/usr/bin/env python3
"""
B FAMILY — 100-SESSION PRE-RESEARCH HISTORICAL OOS VALIDATION V22

Inputs are produced using the repository's existing collectors:
- NIFTY underlying 1m
- NIFTY futures 1m + prospective cumulative session VWAP

This script imports the frozen canonical Family-B detector unchanged and
applies the frozen V20 post-+20 classifier unchanged.

Frozen V20 classifier
---------------------
A B event first has to reach +20 before structural invalidation and survive
the fixed 10-minute observation window.

RUNNER_STRENGTHENING iff:
  net directional progress from +20 at +10m > 0
AND
  directional futures-VWAP change from proof to +10m > 0

Otherwise NORMAL_B.

Important
---------
No B-entry changes.
No classifier threshold changes.
No exit optimization.
No production/runtime/order changes.
Underlying NIFTY points only, not option-premium P&L.

"Pre-research OOS" means prior to the canonical Family-B 180-session universe
that begins 2025-12-12.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

from market_lab import opening_candle_midpoint_framework_v1 as fw

CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")

MANIFEST = Path(
    "data/historical-validation/manifest-b-v22-untouched-100.json"
)
UNDERLYING_CSV = Path(
    "data/historical-evidence/b-v22-untouched-100-underlying.csv"
)
FUTURES_CSV = Path(
    "data/historical-evidence/b-v22-untouched-100-futures-vwap.csv"
)

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "b-family-pre-research-oos-100-v22"
)
SESSION_CSV = OUTDIR / "session-summary-v22.csv"
EVENT_CSV = OUTDIR / "b-events-v22.csv"
CLASSIFIED_CSV = OUTDIR / "post-proof-classification-v22.csv"
REPORT_JSON = OUTDIR / "report-v22.json"
SUMMARY_TXT = OUTDIR / "summary-v22.txt"

EXPECTED_SESSIONS = 100
PROOF_POINTS = 20.0
OBS_MINUTES = 10
MILESTONES = (20, 30, 50, 75, 100)


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_dt(ts):
    return datetime.fromisoformat(ts)


def minute_key(dt):
    return dt.isoformat()


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def favorable_move(direction, entry, bar):
    px = float(bar["high"]) if direction == "BULLISH" else float(bar["low"])
    return directional(direction, entry, px)


def directional_close(direction, entry, bar):
    return directional(direction, entry, float(bar["close"]))


def load_sessions():
    obj = json.loads(MANIFEST.read_text())
    sessions = sorted(x["session_date"] for x in obj["sessions"])
    if len(sessions) != EXPECTED_SESSIONS:
        raise SystemExit(
            f"STOP: manifest has {len(sessions)} sessions, expected {EXPECTED_SESSIONS}"
        )
    if len(set(sessions)) != EXPECTED_SESSIONS:
        raise SystemExit("STOP: duplicate session dates in manifest")
    if sessions[-1] >= "2025-12-12":
        raise SystemExit(
            f"STOP: V22 session crosses research boundary: {sessions[-1]}"
        )
    return sessions


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
    out = defaultdict(dict)
    conflicts = 0

    with FUTURES_CSV.open(newline="") as fh:
        for r in csv.DictReader(fh):
            d = r["session_date"]
            ts = r["timestamp"]
            close = float(r["close"])
            vwap = (
                float(r["session_vwap"])
                if r.get("session_vwap") not in ("", None)
                else None
            )
            diff = close - vwap if vwap is not None else None
            rec = {
                "close": close,
                "vwap": vwap,
                "diff": diff,
                "volume": (
                    float(r["volume"])
                    if r.get("volume") not in ("", None)
                    else None
                ),
            }
            if ts in out[d] and out[d][ts] != rec:
                conflicts += 1
                continue
            out[d][ts] = rec

    return dict(out), conflicts


def build_framework(session_date, minute_rows):
    bars = fw.aggregate_5m(minute_rows)
    red = fw.select_reference_bar(bars, "RED")
    green = fw.select_reference_bar(bars, "GREEN")
    events = []

    if red is not None:
        events.append(
            fw.build_event(
                block="V22_PRE_RESEARCH_OOS",
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
                block="V22_PRE_RESEARCH_OOS",
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
    invalid = ev.get("structural_invalidation_timestamp")

    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if not canon.is_trusted(ts):
            continue
        if invalid and ts >= invalid:
            break
        if favorable_move(ev["direction"], entry, u[ts]) >= PROOF_POINTS:
            return ts

    return None


def directional_vwap(direction, row):
    if not row or row.get("diff") is None:
        return None
    d = float(row["diff"])
    return d if direction == "BULLISH" else -d


def classify_v20(ev, u, fut, proof_ts, canon):
    if proof_ts is None:
        return {
            "classification_status": "NOT_APPLICABLE_NO_PLUS20",
            "classification": None,
            "incomplete_reason": None,
        }

    end_ts = minute_key(parse_dt(proof_ts) + timedelta(minutes=OBS_MINUTES))
    invalid = ev.get("structural_invalidation_timestamp")

    if not canon.is_trusted(end_ts):
        return {
            "classification_status": "INCOMPLETE",
            "classification": None,
            "incomplete_reason": "OBSERVATION_END_AFTER_TRUSTED_CUTOFF",
        }

    if invalid and end_ts >= invalid:
        return {
            "classification_status": "INCOMPLETE",
            "classification": None,
            "incomplete_reason": "STRUCTURAL_INVALIDATION_BEFORE_10M_BOUNDARY",
        }

    if end_ts not in u:
        return {
            "classification_status": "INCOMPLETE",
            "classification": None,
            "incomplete_reason": "MISSING_UNDERLYING_AT_10M_BOUNDARY",
        }

    proof_v = directional_vwap(ev["direction"], fut.get(proof_ts))
    end_v = directional_vwap(ev["direction"], fut.get(end_ts))
    if proof_v is None or end_v is None:
        return {
            "classification_status": "INCOMPLETE",
            "classification": None,
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
        "classification": label,
        "incomplete_reason": None,
        "observation_end_timestamp": end_ts,
        "net_directional_progress_from_plus20": net_progress,
        "proof_directional_vwap_diff": proof_v,
        "end_directional_vwap_diff": end_v,
        "directional_vwap_change": vwap_change,
    }


def milestones(ev, u, canon):
    entry_ts = ev["entry_timestamp"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])
    invalid = ev.get("structural_invalidation_timestamp")
    out = {m: None for m in MILESTONES}

    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if not canon.is_trusted(ts):
            continue
        if invalid and ts >= invalid:
            break
        fav = favorable_move(ev["direction"], entry, u[ts])
        for m in MILESTONES:
            if out[m] is None and fav >= m:
                out[m] = ts

    return out


def stats(xs):
    vals = [float(x) for x in xs if x is not None]
    if not vals:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "n": len(vals),
        "mean": mean(vals),
        "median": median(vals),
        "min": min(vals),
        "max": max(vals),
    }


def write_csv(path, rows):
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


def fmt(x):
    return "-" if x is None else f"{float(x):+.2f}"


def main():
    print("B FAMILY — 100-SESSION PRE-RESEARCH HISTORICAL OOS V22")
    print("=" * 118)

    canon = import_module(CANON, "canonical_b_v22")
    sessions = load_sessions()
    by_session_rows, underlying = load_underlying()
    futures, conflicts = load_futures()

    if conflicts:
        raise SystemExit(f"STOP: futures duplicate conflicts={conflicts}")

    session_rows = []
    event_rows = []
    classified_rows = []

    for n, session in enumerate(sessions, 1):
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
        if any(r.get("diff") is None for r in fut.values()):
            raise SystemExit(f"STOP: {session} has missing futures VWAP diff")

        framework = build_framework(session, minute_rows)
        detected = []

        for e in framework:
            b = canon.family_b_for_event(e, u, fut)
            if not b:
                continue

            ev = canon.measure_event(dict(b), u)
            ms = milestones(ev, u, canon)
            proof = ms[20]

            row = dict(ev)
            for m in MILESTONES:
                row[f"plus{m}_timestamp"] = ms[m]
                row[f"reached_plus{m}"] = ms[m] is not None

            cls = classify_v20(ev, u, fut, proof, canon)
            row.update(cls)

            detected.append(row)
            event_rows.append(row)

            if cls["classification_status"] == "CLASSIFIED":
                classified_rows.append(row)

        session_rows.append({
            "session_date": session,
            "underlying_rows": len(u),
            "futures_rows": len(fut),
            "framework_event_count": len(framework),
            "b_event_count": len(detected),
        })

        print(
            f"{n:3d}/{len(sessions)} {session} "
            f"framework={len(framework)} B={len(detected)}"
        )

    bulls = [r for r in event_rows if r["direction"] == "BULLISH"]
    bears = [r for r in event_rows if r["direction"] == "BEARISH"]

    mfe = stats(r.get("mfe") for r in event_rows)
    mae = stats(r.get("mae") for r in event_rows)

    labels = {
        "RUNNER_STRENGTHENING": [
            r for r in classified_rows
            if r["classification"] == "RUNNER_STRENGTHENING"
        ],
        "NORMAL_B": [
            r for r in classified_rows
            if r["classification"] == "NORMAL_B"
        ],
    }

    lines = [
        "B FAMILY — 100-SESSION PRE-RESEARCH HISTORICAL OOS V22",
        "=" * 118,
        f"session_range={sessions[0]} -> {sessions[-1]}",
        f"sessions={len(sessions)}",
        f"framework_events={sum(r['framework_event_count'] for r in session_rows)}",
        f"b_events={len(event_rows)}",
        f"bullish={len(bulls)} bearish={len(bears)}",
        f"futures_duplicate_conflicts={conflicts}",
        "",
        "B GEOMETRY",
        "-" * 118,
        f"MFE n={mfe['n']} mean={fmt(mfe['mean'])} median={fmt(mfe['median'])} min={fmt(mfe['min'])} max={fmt(mfe['max'])}",
        f"MAE n={mae['n']} mean={fmt(mae['mean'])} median={fmt(mae['median'])} min={fmt(mae['min'])} max={fmt(mae['max'])}",
        "",
        "MILESTONE REACH",
        "-" * 118,
    ]

    for m in MILESTONES:
        hits = sum(bool(r[f"reached_plus{m}"]) for r in event_rows)
        pct = 100.0 * hits / len(event_rows) if event_rows else 0.0
        lines.append(f"+{m:<3} {hits}/{len(event_rows)} ({pct:.1f}%)")

    no20 = sum(not bool(r["reached_plus20"]) for r in event_rows)
    incomplete = sum(
        r.get("classification_status") == "INCOMPLETE"
        for r in event_rows
    )

    lines += [
        "",
        "FROZEN V20 CLASSIFIER",
        "-" * 118,
        f"B events reaching +20       : {len(event_rows) - no20}",
        f"Classified after +20/+10m   : {len(classified_rows)}",
        f"Incomplete +10m observation : {incomplete}",
    ]

    for label, rows in labels.items():
        lines.append("")
        lines.append(f"{label} n={len(rows)}")
        for m in (30, 50, 75, 100):
            hits = sum(bool(r[f"reached_plus{m}"]) for r in rows)
            pct = 100.0 * hits / len(rows) if rows else 0.0
            lines.append(f"  reached +{m:<3}: {hits}/{len(rows)} ({pct:.1f}%)")

        label_mfe = stats(r.get("mfe") for r in rows)
        lines.append(
            f"  MFE median={fmt(label_mfe['median'])} "
            f"mean={fmt(label_mfe['mean'])}"
        )

    # Descriptive difference only; no threshold creation.
    rs = labels["RUNNER_STRENGTHENING"]
    nb = labels["NORMAL_B"]
    rs75 = (sum(bool(r["reached_plus75"]) for r in rs) / len(rs)) if rs else None
    nb75 = (sum(bool(r["reached_plus75"]) for r in nb) / len(nb)) if nb else None

    lines += [
        "",
        "DESCRIPTIVE +75 SEPARATION",
        "-" * 118,
        f"RUNNER_STRENGTHENING +75 rate = {fmt(None if rs75 is None else rs75 * 100)}%",
        f"NORMAL_B             +75 rate = {fmt(None if nb75 is None else nb75 * 100)}%",
        f"difference                 = {fmt(None if rs75 is None or nb75 is None else (rs75-nb75)*100)} percentage points",
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- Frozen canonical Family-B entry imported unchanged.",
        "- Frozen V20 sign-only classifier applied unchanged.",
        "- Zero-B sessions retained.",
        "- No threshold search or reclassification.",
        "- No exit optimization.",
        "- This is pre-research historical OOS relative to the canonical B 180-session universe.",
        "- Do not modify B/V20 rules based on this run.",
        "- Underlying NIFTY points only, not CE/PE premium P&L.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_PRE_RESEARCH_HISTORICAL_OOS_V22",
        "session_range": [sessions[0], sessions[-1]],
        "session_count": len(sessions),
        "framework_event_count": sum(
            r["framework_event_count"] for r in session_rows
        ),
        "b_event_count": len(event_rows),
        "bullish_count": len(bulls),
        "bearish_count": len(bears),
        "mfe": mfe,
        "mae": mae,
        "milestones": {
            str(m): sum(bool(r[f"reached_plus{m}"]) for r in event_rows)
            for m in MILESTONES
        },
        "classifier": {
            "classified_count": len(classified_rows),
            "incomplete_count": incomplete,
            "groups": {
                label: {
                    "count": len(rows),
                    "plus30": sum(bool(r["reached_plus30"]) for r in rows),
                    "plus50": sum(bool(r["reached_plus50"]) for r in rows),
                    "plus75": sum(bool(r["reached_plus75"]) for r in rows),
                    "plus100": sum(bool(r["reached_plus100"]) for r in rows),
                    "mfe": stats(r.get("mfe") for r in rows),
                }
                for label, rows in labels.items()
            },
        },
        "guards": {
            "family_b_changed": False,
            "v20_classifier_changed": False,
            "exit_optimized": False,
            "production_code_changed": False,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(SESSION_CSV, session_rows)
    write_csv(EVENT_CSV, event_rows)
    write_csv(CLASSIFIED_CSV, classified_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines))

    print()
    print("\n".join(lines))
    print()
    print("SESSION CSV    :", SESSION_CSV)
    print("EVENT CSV      :", EVENT_CSV)
    print("CLASSIFIED CSV :", CLASSIFIED_CSV)
    print("REPORT JSON    :", REPORT_JSON)
    print("SUMMARY        :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
