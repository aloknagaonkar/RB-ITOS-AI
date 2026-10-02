#!/usr/bin/env python3
"""
B FAMILY — 180-SESSION DATA HEALTH AUDIT V14

Purpose:
Verify that the canonical 180-session research foundation is healthy before
running any new trailing-stop characterization.

Checks:
- expected 180 sessions
- underlying coverage
- futures/VWAP coverage
- timestamp continuity / duplicates
- VWAP nulls
- trusted session bounds
- canonical frozen Family-B parity = 45 events
- split parity: older 27 / latest60 18

Research-only. No strategy/runtime/order changes.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from market_lab import opening_candle_midpoint_framework_v1 as framework

FRAMEWORK_JSON = Path(
    "data/historical-evidence/"
    "midpoint-opening-candle-framework-v1-all180.json"
)
FUTURES_CSV = Path(
    "data/historical-evidence/"
    "midpoint-v2-nifty-futures-vwap-v1-all180.csv"
)
CANON_B = Path(
    "scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py"
)

# Fallback patterns because historical underlying artifacts evolved during research.
UNDERLYING_GLOBS = (
    "data/historical-evidence/**/underlying-cache/*.json",
    "data/historical-evidence/**/underlying-*.csv",
)

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "b-family-180-data-health-audit-v14"
)
REPORT_JSON = OUTDIR / "report-v14.json"
SESSION_CSV = OUTDIR / "session-health-v14.csv"
SUMMARY_TXT = OUTDIR / "summary-v14.txt"

EXPECTED_SESSIONS = 180
EXPECTED_B_TOTAL = 45
EXPECTED_B_OLDER = 27
EXPECTED_B_LATEST60 = 18
TRUSTED_START = "09:15"
TRUSTED_END = "15:14"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_ts(v):
    if isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v))


def load_framework_sessions():
    if not FRAMEWORK_JSON.exists():
        raise FileNotFoundError(FRAMEWORK_JSON)
    obj = json.loads(FRAMEWORK_JSON.read_text())

    # tolerate common container shapes
    if isinstance(obj, list):
        events = obj
    elif isinstance(obj, dict):
        events = obj.get("events") or obj.get("rows") or obj.get("sessions") or []
    else:
        events = []

    dates = sorted(
        {
            str(
                e.get("session_date")
                or e.get("date")
                or e.get("_session")
                or ""
            )[:10]
            for e in events
            if isinstance(e, dict)
            and (
                e.get("session_date")
                or e.get("date")
                or e.get("_session")
            )
        }
    )
    return obj, events, dates


def load_futures():
    if not FUTURES_CSV.exists():
        raise FileNotFoundError(FUTURES_CSV)

    by = {}
    with FUTURES_CSV.open(newline="") as fh:
        for r in csv.DictReader(fh):
            d = str(r["session_date"])[:10]
            by.setdefault(d, []).append(r)

    for d in by:
        by[d].sort(key=lambda r: parse_ts(r["timestamp"]))
    return by


def scan_underlying_candidates():
    found = {}
    for pat in UNDERLYING_GLOBS:
        for p in Path(".").glob(pat):
            name = p.name
            for token in name.replace("_", "-").split("-"):
                pass
            # derive date from filename/path text
            s = str(p)
            for part in s.replace("_", "-").split("/"):
                # exact YYYY-MM-DD may appear as complete path part or embedded
                for i in range(max(0, len(part) - 9)):
                    cand = part[i:i+10]
                    try:
                        datetime.strptime(cand, "%Y-%m-%d")
                    except Exception:
                        continue
                    found.setdefault(cand, []).append(p)
    return found


def load_underlying_file(path: Path, session: str):
    if path.suffix.lower() == ".json":
        obj = json.loads(path.read_text())
        rows = obj.get("candles") if isinstance(obj, dict) else obj
        if not isinstance(rows, list):
            return []
        out = []
        for r in rows:
            if not isinstance(r, dict) or not r.get("timestamp"):
                continue
            out.append(r)
        return out

    if path.suffix.lower() == ".csv":
        with path.open(newline="") as fh:
            out = []
            for r in csv.DictReader(fh):
                ts = r.get("timestamp") or r.get("datetime") or r.get("time")
                d = r.get("session_date") or r.get("date")
                if d and str(d)[:10] != session:
                    continue
                if not ts:
                    continue
                r2 = dict(r)
                r2["timestamp"] = ts
                out.append(r2)
            return out

    return []


def choose_underlying(found, session):
    candidates = found.get(session, [])
    scored = []
    for p in candidates:
        rows = load_underlying_file(p, session)
        if not rows:
            continue
        timestamps = sorted(parse_ts(r["timestamp"]) for r in rows)
        # favor 375-row clean 09:15-start files
        score = (
            abs(len(rows) - 375),
            0 if timestamps[0].strftime("%H:%M") == "09:15" else 1,
            len(str(p)),
        )
        scored.append((score, p, rows))
    if not scored:
        return None, []
    scored.sort(key=lambda x: x[0])
    _, p, rows = scored[0]
    return p, rows


def minute_health(rows, start="09:15", end="15:14"):
    if not rows:
        return {
            "rows_total": 0,
            "first": None,
            "last": None,
            "duplicate_timestamps": 0,
            "trusted_expected": 0,
            "trusted_present": 0,
            "trusted_missing": None,
        }

    ts = [parse_ts(r["timestamp"]) for r in rows]
    ts.sort()
    counts = Counter(ts)
    dup = sum(v - 1 for v in counts.values() if v > 1)

    day = ts[0].date()
    s = datetime.fromisoformat(f"{day.isoformat()}T{start}:00")
    e = datetime.fromisoformat(f"{day.isoformat()}T{end}:00")
    # Preserve timezone if source carries one.
    if ts[0].tzinfo is not None:
        s = s.replace(tzinfo=ts[0].tzinfo)
        e = e.replace(tzinfo=ts[0].tzinfo)

    expected = []
    cur = s
    while cur <= e:
        expected.append(cur)
        cur += timedelta(minutes=1)

    present = set(ts)
    missing = [x for x in expected if x not in present]

    return {
        "rows_total": len(rows),
        "first": ts[0].isoformat(),
        "last": ts[-1].isoformat(),
        "duplicate_timestamps": dup,
        "trusted_expected": len(expected),
        "trusted_present": len(expected) - len(missing),
        "trusted_missing": len(missing),
    }


def futures_health(rows):
    h = minute_health(rows)
    vwap_null = 0
    for r in rows:
        if r.get("session_vwap") in (None, ""):
            vwap_null += 1
    h["vwap_null_rows"] = vwap_null
    return h


def framework_event_session(e):
    return str(
        e.get("session_date")
        or e.get("date")
        or e.get("_session")
        or ""
    )[:10]


def normalize_underlying_for_framework(rows, session):
    out = []
    for r in rows:
        out.append(
            {
                "session_date": session,
                "timestamp": r["timestamp"],
                "open": r.get("open"),
                "high": r.get("high"),
                "low": r.get("low"),
                "close": r.get("close"),
                "volume": r.get("volume", 0),
                "open_interest": r.get("open_interest", 0),
            }
        )
    return framework.underlying_by_session(out).get(session, [])


def underlying_index(minute_rows):
    out = {}
    for r in minute_rows:
        ts = r["timestamp"]
        key = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        out[key] = {
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r.get("volume", 0) or 0),
        }
    return out


def futures_index(rows):
    out = {}
    for r in rows:
        if r.get("session_vwap") in (None, ""):
            continue
        c = float(r["close"])
        v = float(r["session_vwap"])
        out[r["timestamp"]] = {
            "close": c,
            "vwap": v,
            "diff": c - v,
            "volume": float(r.get("volume") or 0),
        }
    return out


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
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


def main():
    print("B FAMILY — 180-SESSION DATA HEALTH AUDIT V14")
    print("=" * 118)

    if not CANON_B.exists():
        raise SystemExit(f"MISSING canonical B detector: {CANON_B}")

    bmod = load_module(CANON_B, "canon_b_health_v14")

    framework_obj, framework_events, framework_dates = load_framework_sessions()
    futures = load_futures()
    underlying_candidates = scan_underlying_candidates()

    # If framework JSON container does not expose 180 unique dates, use futures as
    # canonical session universe and still report the framework count separately.
    universe = framework_dates if len(framework_dates) == EXPECTED_SESSIONS else sorted(futures)

    print(f"Framework unique sessions : {len(framework_dates)}")
    print(f"Futures unique sessions   : {len(futures)}")
    print(f"Audit universe            : {len(universe)}")
    if universe:
        print(f"Date range                : {universe[0]} -> {universe[-1]}")
    print()

    events_by_session = {}
    for e in framework_events:
        d = framework_event_session(e)
        if d:
            events_by_session.setdefault(d, []).append(e)

    session_rows = []
    b_events = []

    for d in universe:
        upath, raw_u = choose_underlying(underlying_candidates, d)
        uh = minute_health(raw_u)
        fh = futures_health(futures.get(d, []))

        row = {
            "session_date": d,
            "underlying_found": bool(raw_u),
            "underlying_path": str(upath) if upath else "",
            "underlying_rows": uh["rows_total"],
            "underlying_first": uh["first"],
            "underlying_last": uh["last"],
            "underlying_duplicates": uh["duplicate_timestamps"],
            "underlying_trusted_missing": uh["trusted_missing"],
            "futures_found": d in futures,
            "futures_rows": fh["rows_total"],
            "futures_first": fh["first"],
            "futures_last": fh["last"],
            "futures_duplicates": fh["duplicate_timestamps"],
            "futures_trusted_missing": fh["trusted_missing"],
            "futures_vwap_nulls": fh["vwap_null_rows"],
            "framework_event_count": len(events_by_session.get(d, [])),
        }

        session_rows.append(row)

        if not raw_u or d not in futures:
            continue

        minute_rows = normalize_underlying_for_framework(raw_u, d)
        u = underlying_index(minute_rows)
        fut = futures_index(futures[d])

        for e in events_by_session.get(d, []):
            b = bmod.family_b_for_event(e, u, fut)
            if b:
                b_events.append(b)

    latest60_dates = set(universe[-60:]) if len(universe) >= 60 else set(universe)
    b_latest60 = [b for b in b_events if b["session_date"] in latest60_dates]
    b_older = [b for b in b_events if b["session_date"] not in latest60_dates]

    bad_underlying = [
        r for r in session_rows
        if (
            not r["underlying_found"]
            or r["underlying_duplicates"] != 0
            or r["underlying_trusted_missing"] not in (0, None)
        )
    ]
    bad_futures = [
        r for r in session_rows
        if (
            not r["futures_found"]
            or r["futures_duplicates"] != 0
            or r["futures_trusted_missing"] not in (0, None)
            or r["futures_vwap_nulls"] != 0
        )
    ]

    checks = {
        "expected_session_count": len(universe) == EXPECTED_SESSIONS,
        "underlying_health_all_sessions": len(bad_underlying) == 0,
        "futures_vwap_health_all_sessions": len(bad_futures) == 0,
        "canonical_b_total_45": len(b_events) == EXPECTED_B_TOTAL,
        "canonical_b_older_27": len(b_older) == EXPECTED_B_OLDER,
        "canonical_b_latest60_18": len(b_latest60) == EXPECTED_B_LATEST60,
    }
    status = "PASS" if all(checks.values()) else "FAIL"

    report = {
        "status": status,
        "research_version": "B_FAMILY_180_DATA_HEALTH_AUDIT_V14",
        "expected": {
            "sessions": EXPECTED_SESSIONS,
            "b_total": EXPECTED_B_TOTAL,
            "b_older": EXPECTED_B_OLDER,
            "b_latest60": EXPECTED_B_LATEST60,
        },
        "observed": {
            "sessions": len(universe),
            "framework_sessions": len(framework_dates),
            "futures_sessions": len(futures),
            "b_total": len(b_events),
            "b_older": len(b_older),
            "b_latest60": len(b_latest60),
            "bad_underlying_sessions": len(bad_underlying),
            "bad_futures_sessions": len(bad_futures),
        },
        "checks": checks,
        "bad_underlying_sessions": bad_underlying,
        "bad_futures_sessions": bad_futures,
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    write_csv(SESSION_CSV, session_rows)

    lines = [
        "B FAMILY — 180-SESSION DATA HEALTH AUDIT V14",
        "=" * 118,
        f"STATUS: {status}",
        "",
        f"Sessions              : {len(universe)} / {EXPECTED_SESSIONS}",
        f"Framework sessions    : {len(framework_dates)}",
        f"Futures/VWAP sessions : {len(futures)}",
        f"Bad underlying days   : {len(bad_underlying)}",
        f"Bad futures/VWAP days : {len(bad_futures)}",
        "",
        f"Canonical B total     : {len(b_events)} / {EXPECTED_B_TOTAL}",
        f"Canonical B older     : {len(b_older)} / {EXPECTED_B_OLDER}",
        f"Canonical B latest60  : {len(b_latest60)} / {EXPECTED_B_LATEST60}",
        "",
        "CHECKS",
        "-" * 118,
    ]
    for k, v in checks.items():
        lines.append(f"{k:<40} {'PASS' if v else 'FAIL'}")

    if bad_underlying:
        lines += ["", "BAD UNDERLYING SESSIONS", "-" * 118]
        for r in bad_underlying[:50]:
            lines.append(
                f"{r['session_date']} found={r['underlying_found']} "
                f"rows={r['underlying_rows']} dup={r['underlying_duplicates']} "
                f"trusted_missing={r['underlying_trusted_missing']} "
                f"path={r['underlying_path']}"
            )

    if bad_futures:
        lines += ["", "BAD FUTURES/VWAP SESSIONS", "-" * 118]
        for r in bad_futures[:50]:
            lines.append(
                f"{r['session_date']} found={r['futures_found']} "
                f"rows={r['futures_rows']} dup={r['futures_duplicates']} "
                f"trusted_missing={r['futures_trusted_missing']} "
                f"vwap_nulls={r['futures_vwap_nulls']}"
            )

    lines += [
        "",
        "INTERPRETATION",
        "-" * 118,
        "PASS means the 180-session underlying/futures/VWAP foundation is healthy",
        "and the frozen Family-B detector reproduces the canonical 45 events",
        "(27 older + 18 latest60). Only then should trailing-SL V15 proceed.",
        "",
        "Research only. No strategy/runtime/execution/order settings are changed.",
    ]

    text = "\n".join(lines)
    SUMMARY_TXT.write_text(text)

    print(text)
    print()
    print("REPORT JSON :", REPORT_JSON)
    print("SESSION CSV :", SESSION_CSV)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
