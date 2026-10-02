#!/usr/bin/env python3
"""
B FAMILY — 180-SESSION DATA HEALTH AUDIT V14.1

Fix vs V14:
- Reuses the canonical Family-B validator's exact FRAMEWORK_FILES.
- Reuses its load_framework() and load_underlying() logic.
- Uses its FUTURES_CSV constant.
- Recomputes only health summaries around those canonical inputs.
- Re-runs frozen family_b_for_event() for parity.

Expected parity:
  sessions=180
  B total=45
  older=27
  latest60=18
  underlying duplicate conflicts=0

Research only. No strategy/runtime/order changes.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "b-family-180-data-health-audit-v14-1"
)
REPORT_JSON = OUTDIR / "report-v14-1.json"
SESSION_CSV = OUTDIR / "session-health-v14-1.csv"
SUMMARY_TXT = OUTDIR / "summary-v14-1.txt"

EXPECTED_SESSIONS = 180
EXPECTED_B_TOTAL = 45
EXPECTED_B_OLDER = 27
EXPECTED_B_LATEST60 = 18
TRUSTED_START = "09:15"
TRUSTED_END = "15:14"


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def dt(v):
    if isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v))


def unpack_underlying(result):
    """
    Canonical loaders may return:
      by_session
      (by_session, duplicate_conflicts)
      (files_used, by_session, duplicate_conflicts)
    Handle all without changing canonical logic.
    """
    if isinstance(result, dict):
        return result, 0, []

    if not isinstance(result, tuple):
        raise RuntimeError(
            f"Unexpected load_underlying() return type: {type(result).__name__}"
        )

    dict_items = [x for x in result if isinstance(x, dict)]
    int_items = [x for x in result if isinstance(x, int)]
    list_items = [x for x in result if isinstance(x, list)]

    if not dict_items:
        raise RuntimeError("Could not locate underlying by_session dict")

    by_session = dict_items[0]
    dup = int_items[-1] if int_items else 0
    files = list_items[0] if list_items else []
    return by_session, dup, files


def load_futures_csv(path: Path, is_trusted):
    if not path.exists():
        raise FileNotFoundError(path)

    by = {}
    duplicate_conflicts = 0

    with path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            session = r.get("session_date")
            ts = r.get("timestamp")
            if not session or not ts:
                continue

            by.setdefault(session, {})
            rec = {
                "close": float(r["close"]) if r.get("close") not in (None, "") else None,
                "vwap": (
                    float(r["session_vwap"])
                    if r.get("session_vwap") not in (None, "")
                    else None
                ),
                "diff": (
                    float(r["close"]) - float(r["session_vwap"])
                    if r.get("close") not in (None, "")
                    and r.get("session_vwap") not in (None, "")
                    else None
                ),
                "volume": (
                    float(r["volume"])
                    if r.get("volume") not in (None, "")
                    else None
                ),
                "_trusted": is_trusted(ts),
            }

            if ts in by[session]:
                old = by[session][ts]
                comparable_old = {
                    k: old.get(k) for k in ("close", "vwap", "diff", "volume")
                }
                comparable_new = {
                    k: rec.get(k) for k in ("close", "vwap", "diff", "volume")
                }
                if comparable_old != comparable_new:
                    duplicate_conflicts += 1
                    continue
            by[session][ts] = rec

    return by, duplicate_conflicts


def expected_trusted_timestamps(session: str, tzinfo):
    start = datetime.fromisoformat(f"{session}T{TRUSTED_START}:00")
    end = datetime.fromisoformat(f"{session}T{TRUSTED_END}:00")
    if tzinfo is not None:
        start = start.replace(tzinfo=tzinfo)
        end = end.replace(tzinfo=tzinfo)

    out = []
    cur = start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(minutes=1)
    return out


def session_health_from_map(session, rows, value_kind):
    """
    rows is canonical timestamp->record dict.
    """
    keys = sorted(rows)
    first = keys[0] if keys else None
    last = keys[-1] if keys else None

    tzinfo = dt(first).tzinfo if first else None
    expected = expected_trusted_timestamps(session, tzinfo) if first else []
    present = set(keys)

    missing = [x for x in expected if x not in present]

    nulls = 0
    if value_kind == "futures":
        for r in rows.values():
            if r.get("_trusted") and r.get("vwap") is None:
                nulls += 1

    trusted_present = sum(
        1
        for k in keys
        if TRUSTED_START <= str(k)[11:16] <= TRUSTED_END
    )

    return {
        "rows_total": len(keys),
        "first": first,
        "last": last,
        "trusted_expected": len(expected),
        "trusted_present": trusted_present,
        "trusted_missing": len(missing),
        "vwap_nulls_trusted": nulls,
    }


def normalize_event_session(e):
    return str(e.get("session_date") or "")[:10]


def main():
    print("B FAMILY — 180-SESSION DATA HEALTH AUDIT V14.1")
    print("=" * 118)

    if not CANON.exists():
        raise SystemExit(f"MISSING canonical script: {CANON}")

    c = import_module(CANON, "canonical_b_v14_1")

    # Exact canonical framework loader and exact canonical framework file list.
    framework_files, framework_events = c.load_framework()
    framework_sessions = sorted(
        {normalize_event_session(e) for e in framework_events if e.get("session_date")}
    )

    # Exact canonical underlying loader.
    underlying_result = c.load_underlying()
    underlying, underlying_dup_conflicts, underlying_files = unpack_underlying(
        underlying_result
    )
    underlying_sessions = sorted(underlying)

    # Canonical futures file, parsed without altering values.
    futures, futures_dup_conflicts = load_futures_csv(c.FUTURES_CSV, c.is_trusted)
    futures_sessions = sorted(futures)

    # Canonical session universe = framework sessions.
    universe = framework_sessions

    print("Framework files:")
    for p in framework_files:
        print("  ", p)
    print()
    print("Canonical futures file :", c.FUTURES_CSV)
    print("Framework sessions     :", len(framework_sessions))
    print("Underlying sessions    :", len(underlying_sessions))
    print("Futures sessions       :", len(futures_sessions))
    print("Underlying dup conflicts:", underlying_dup_conflicts)
    print("Futures dup conflicts   :", futures_dup_conflicts)
    if universe:
        print("Date range             :", universe[0], "->", universe[-1])
    print()

    events_by_session = {}
    for e in framework_events:
        d = normalize_event_session(e)
        events_by_session.setdefault(d, []).append(e)

    session_rows = []
    b_events = []

    for session in universe:
        u = underlying.get(session, {})
        f = futures.get(session, {})

        uh = session_health_from_map(session, u, "underlying")
        fh = session_health_from_map(session, f, "futures")

        # Family B sees the same mapping values expected by canonical detector.
        for e in events_by_session.get(session, []):
            b = c.family_b_for_event(e, u, f)
            if b is not None:
                b_events.append(b)

        session_rows.append(
            {
                "session_date": session,
                "framework_event_count": len(events_by_session.get(session, [])),
                "underlying_found": bool(u),
                "underlying_rows": uh["rows_total"],
                "underlying_first": uh["first"],
                "underlying_last": uh["last"],
                "underlying_trusted_expected": uh["trusted_expected"],
                "underlying_trusted_present": uh["trusted_present"],
                "underlying_trusted_missing": uh["trusted_missing"],
                "futures_found": bool(f),
                "futures_rows": fh["rows_total"],
                "futures_first": fh["first"],
                "futures_last": fh["last"],
                "futures_trusted_expected": fh["trusted_expected"],
                "futures_trusted_present": fh["trusted_present"],
                "futures_trusted_missing": fh["trusted_missing"],
                "futures_vwap_nulls_trusted": fh["vwap_nulls_trusted"],
            }
        )

    latest60_dates = set(universe[-60:])
    b_latest60 = [
        x for x in b_events if x.get("session_date") in latest60_dates
    ]
    b_older = [
        x for x in b_events if x.get("session_date") not in latest60_dates
    ]

    bad_underlying = [
        r for r in session_rows
        if (
            not r["underlying_found"]
            or r["underlying_trusted_missing"] != 0
        )
    ]

    bad_futures = [
        r for r in session_rows
        if (
            not r["futures_found"]
            or r["futures_trusted_missing"] != 0
            or r["futures_vwap_nulls_trusted"] != 0
        )
    ]

    checks = {
        "framework_sessions_180": len(framework_sessions) == EXPECTED_SESSIONS,
        "underlying_sessions_180": len(underlying_sessions) == EXPECTED_SESSIONS,
        "futures_sessions_180": len(futures_sessions) == EXPECTED_SESSIONS,
        "underlying_duplicate_conflicts_0": underlying_dup_conflicts == 0,
        "futures_duplicate_conflicts_0": futures_dup_conflicts == 0,
        "underlying_trusted_coverage_all": len(bad_underlying) == 0,
        "futures_vwap_trusted_coverage_all": len(bad_futures) == 0,
        "canonical_b_total_45": len(b_events) == EXPECTED_B_TOTAL,
        "canonical_b_older_27": len(b_older) == EXPECTED_B_OLDER,
        "canonical_b_latest60_18": len(b_latest60) == EXPECTED_B_LATEST60,
    }

    status = "PASS" if all(checks.values()) else "FAIL"

    report = {
        "status": status,
        "version": "B_FAMILY_180_DATA_HEALTH_AUDIT_V14_1",
        "canonical_inputs": {
            "framework_files": [str(p) for p in framework_files],
            "futures_csv": str(c.FUTURES_CSV),
            "underlying_glob": str(c.UNDERLYING_GLOB),
        },
        "observed": {
            "framework_sessions": len(framework_sessions),
            "framework_events": len(framework_events),
            "underlying_sessions": len(underlying_sessions),
            "futures_sessions": len(futures_sessions),
            "underlying_duplicate_conflicts": underlying_dup_conflicts,
            "futures_duplicate_conflicts": futures_dup_conflicts,
            "bad_underlying_sessions": len(bad_underlying),
            "bad_futures_sessions": len(bad_futures),
            "b_total": len(b_events),
            "b_older": len(b_older),
            "b_latest60": len(b_latest60),
        },
        "checks": checks,
        "bad_underlying_sessions": bad_underlying,
        "bad_futures_sessions": bad_futures,
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2))

    fields = list(session_rows[0]) if session_rows else []
    with SESSION_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(session_rows)

    lines = [
        "B FAMILY — 180-SESSION DATA HEALTH AUDIT V14.1",
        "=" * 118,
        f"STATUS: {status}",
        "",
        f"Framework sessions      : {len(framework_sessions)} / 180",
        f"Framework events        : {len(framework_events)}",
        f"Underlying sessions     : {len(underlying_sessions)} / 180",
        f"Futures/VWAP sessions   : {len(futures_sessions)} / 180",
        f"Underlying dup conflicts: {underlying_dup_conflicts}",
        f"Futures dup conflicts   : {futures_dup_conflicts}",
        f"Bad underlying sessions : {len(bad_underlying)}",
        f"Bad futures/VWAP sessions: {len(bad_futures)}",
        "",
        f"Canonical B total       : {len(b_events)} / 45",
        f"Canonical B older       : {len(b_older)} / 27",
        f"Canonical B latest60    : {len(b_latest60)} / 18",
        "",
        "CHECKS",
        "-" * 118,
    ]

    for name, ok in checks.items():
        lines.append(f"{name:<42} {'PASS' if ok else 'FAIL'}")

    if bad_underlying:
        lines += ["", "BAD UNDERLYING SESSIONS", "-" * 118]
        for r in bad_underlying[:50]:
            lines.append(
                f"{r['session_date']} rows={r['underlying_rows']} "
                f"trusted={r['underlying_trusted_present']}/"
                f"{r['underlying_trusted_expected']} "
                f"missing={r['underlying_trusted_missing']}"
            )

    if bad_futures:
        lines += ["", "BAD FUTURES/VWAP SESSIONS", "-" * 118]
        for r in bad_futures[:50]:
            lines.append(
                f"{r['session_date']} rows={r['futures_rows']} "
                f"trusted={r['futures_trusted_present']}/"
                f"{r['futures_trusted_expected']} "
                f"missing={r['futures_trusted_missing']} "
                f"vwap_nulls={r['futures_vwap_nulls_trusted']}"
            )

    lines += [
        "",
        "GATE",
        "-" * 118,
        "Proceed to B trailing-SL V15 only if STATUS=PASS.",
        "No strategy parameter was changed by this audit.",
    ]

    summary = "\n".join(lines)
    SUMMARY_TXT.write_text(summary)

    print(summary)
    print()
    print("REPORT JSON :", REPORT_JSON)
    print("SESSION CSV :", SESSION_CSV)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
