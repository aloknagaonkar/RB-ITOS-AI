#!/usr/bin/env python3
"""
MIDPOINT + VWAP — FAMILY C REJECTION AUDIT — LATEST 60 SESSIONS — V1

Research-only comparison of:
- V1 Family C events (before opposite-structure lifecycle termination)
- V1.1 Family C events retained after the lifecycle correction

Purpose:
Determine whether the Family C events removed by V1.1 were genuinely stale
continuation chains after a regime change, or whether potentially useful
same-direction continuation events were discarded.

No strategy/runtime/Candidate-A/Hilega changes.
No threshold search.
15:15 onward remains excluded.

Expected from the preceding 60-session runs:
- old C ~= 70
- retained C ~= 13
- rejected former-C ~= 57
"""

from __future__ import annotations

import csv
import glob
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")

OLD_EVENTS = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-setup-family-60-session-validation-v1"
    / "setup-family-events-v1.csv"
)

NEW_EVENTS = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-setup-family-60-session-validation-v1-1"
    / "setup-family-events-v1-1.csv"
)

FRAMEWORK_FILES = [
    ROOT / "opening-candle-midpoint-framework-v1-1-development.json",
    ROOT / "opening-candle-midpoint-framework-v1-1-oos-efg.json",
    ROOT / "opening-candle-midpoint-framework-v1-1-oos-h.json",
]

UNDERLYING_GLOB = str(ROOT / "underlying-ohlc-*.csv")

OUTDIR = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-family-c-rejection-audit-60-session-v1"
)

RETAINED_CSV = OUTDIR / "retained-family-c-v1.csv"
REJECTED_CSV = OUTDIR / "rejected-former-family-c-v1.csv"
SESSION_CSV = OUTDIR / "family-c-rejection-session-summary-v1.csv"
SUMMARY_TXT = OUTDIR / "summary-v1.txt"

C_FAMILY = "C_FAILED_MIDPOINT_RECLAIM_REBREAK"
D_FAMILY = "D_FULL_RANGE_OPPOSITE_RECOVERY_REBREAK"
TRUSTED_END = "15:14"


def parse_ts(ts):
    return datetime.fromisoformat(ts)


def mins(a, b):
    return (parse_ts(b) - parse_ts(a)).total_seconds() / 60.0


def is_trusted(ts):
    return ts and ts[11:16] <= TRUSTED_END


def fnum(v):
    if v in (None, ""):
        return None
    return float(v)


def qdesc(vals):
    xs = sorted(float(x) for x in vals if x not in (None, ""))
    if not xs:
        return "n=0"

    def q(p):
        return xs[round((len(xs) - 1) * p)]

    return (
        f"n={len(xs)} mean={mean(xs):+.2f} median={median(xs):+.2f} "
        f"p25={q(.25):+.2f} p75={q(.75):+.2f} "
        f"min={xs[0]:+.2f} max={xs[-1]:+.2f}"
    )


def load_csv(path):
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


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

    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Framework
# ---------------------------------------------------------------------------

def walk_framework(obj):
    if isinstance(obj, dict):
        if obj.get("session_date") and obj.get("setup_type") in {
            "RED_BREAK", "GREEN_BREAK"
        }:
            yield obj
        for v in obj.values():
            yield from walk_framework(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_framework(v)


def event_key(e):
    return (
        e.get("session_date"),
        e.get("setup_type"),
        e.get("reference_start"),
        e.get("reference_end"),
        e.get("reference_high"),
        e.get("reference_low"),
        e.get("reference_midpoint"),
        e.get("midpoint_break_timestamp"),
        e.get("boundary_break_timestamp"),
    )


def load_framework():
    out = defaultdict(list)
    seen = set()

    for p in FRAMEWORK_FILES:
        if not p.exists():
            continue
        with p.open() as f:
            obj = json.load(f)

        for e in walk_framework(obj):
            k = event_key(e)
            if k in seen:
                continue
            seen.add(k)
            out[e["session_date"]].append(e)

    return out


def find_opposite_event(framework_by_session, row):
    session = row["session_date"]
    direction = row["direction"]
    events = framework_by_session.get(session, [])

    wanted = "RED_BREAK" if direction == "BULLISH" else "GREEN_BREAK"
    candidates = [e for e in events if e.get("setup_type") == wanted]

    if not candidates:
        return None

    # There should normally be one opening structure of each type.
    candidates.sort(
        key=lambda e: (
            e.get("boundary_break_timestamp")
            or e.get("midpoint_break_timestamp")
            or ""
        )
    )
    return candidates[0]


# ---------------------------------------------------------------------------
# Underlying
# ---------------------------------------------------------------------------

def load_underlying():
    by_session = defaultdict(dict)

    files = sorted(glob.glob(UNDERLYING_GLOB))
    if not files:
        raise FileNotFoundError(UNDERLYING_GLOB)

    for p in files:
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                session = r.get("session_date")
                ts = r.get("timestamp")
                if not session or not ts or not is_trusted(ts):
                    continue

                close = fnum(r.get("close"))
                if close is None:
                    continue

                by_session[session][ts] = {
                    "open": fnum(r.get("open")),
                    "high": fnum(r.get("high")),
                    "low": fnum(r.get("low")),
                    "close": close,
                }

    return files, by_session


def first_opposite_termination(row, opposite_event, u):
    """
    Same V1.1 lifecycle rule:
      bullish C dies when price closes below opposite RED low
      bearish C dies when price closes above opposite GREEN high
    Search after original C origin and no later than the old would-be C entry.
    """
    if not opposite_event:
        return None, None

    direction = row["direction"]
    origin = row.get("origin_timestamp")
    would_be_entry = row.get("entry_timestamp")

    if not origin or not would_be_entry:
        return None, None

    if direction == "BULLISH":
        level = float(opposite_event["reference_low"])
        predicate = lambda c: c < level
        label = "CLOSE_BELOW_OPPOSITE_RED_LOW"
    else:
        level = float(opposite_event["reference_high"])
        predicate = lambda c: c > level
        label = "CLOSE_ABOVE_OPPOSITE_GREEN_HIGH"

    for ts in sorted(u):
        if ts <= origin:
            continue
        if ts > would_be_entry:
            break
        if predicate(u[ts]["close"]):
            return ts, {
                "termination_reason": label,
                "termination_level": level,
                "termination_close": u[ts]["close"],
            }

    return None, None


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def c_key(r):
    return (
        r.get("session_date"),
        r.get("direction"),
        r.get("entry_timestamp"),
    )


def d_after_termination(new_rows, session, direction, term_ts):
    any_d = []
    same_dir = []

    for r in new_rows:
        if r.get("family") != D_FAMILY:
            continue
        if r.get("session_date") != session:
            continue

        entry = r.get("entry_timestamp")
        if not entry or entry < term_ts:
            continue

        any_d.append(r)
        if r.get("direction") == direction:
            same_dir.append(r)

    any_d.sort(key=lambda r: r["entry_timestamp"])
    same_dir.sort(key=lambda r: r["entry_timestamp"])

    return (
        any_d[0]["entry_timestamp"] if any_d else None,
        same_dir[0]["entry_timestamp"] if same_dir else None,
    )


def time_bucket(v):
    if v is None:
        return "NO_TERMINATION_FOUND"
    if v <= 5:
        return "LE_5M"
    if v <= 15:
        return "6_15M"
    if v <= 30:
        return "16_30M"
    if v <= 60:
        return "31_60M"
    if v <= 120:
        return "61_120M"
    return "GT_120M"


def main():
    old_rows = load_csv(OLD_EVENTS)
    new_rows = load_csv(NEW_EVENTS)

    old_c = [r for r in old_rows if r.get("family") == C_FAMILY]
    new_c = [r for r in new_rows if r.get("family") == C_FAMILY]

    new_c_keys = {c_key(r) for r in new_c}
    retained = [r for r in old_c if c_key(r) in new_c_keys]
    rejected = [r.copy() for r in old_c if c_key(r) not in new_c_keys]

    framework = load_framework()
    underlying_files, underlying = load_underlying()

    for r in rejected:
        opposite = find_opposite_event(framework, r)
        term_ts, meta = first_opposite_termination(
            r,
            opposite,
            underlying.get(r["session_date"], {}),
        )

        r["opposite_structure_termination_timestamp"] = term_ts or ""

        if meta:
            r.update(meta)
        else:
            r["termination_reason"] = ""
            r["termination_level"] = ""
            r["termination_close"] = ""

        if term_ts:
            gap = mins(term_ts, r["entry_timestamp"])
            r["termination_to_would_be_rebreak_minutes"] = gap
            r["termination_gap_bucket"] = time_bucket(gap)

            any_d, same_d = d_after_termination(
                new_rows,
                r["session_date"],
                r["direction"],
                term_ts,
            )
            r["first_any_family_d_after_termination"] = any_d or ""
            r["first_same_direction_family_d_after_termination"] = same_d or ""
            r["same_direction_d_exists_after_termination"] = bool(same_d)
            if same_d:
                r["minutes_termination_to_same_direction_d"] = mins(
                    term_ts, same_d
                )
            else:
                r["minutes_termination_to_same_direction_d"] = ""
        else:
            r["termination_to_would_be_rebreak_minutes"] = ""
            r["termination_gap_bucket"] = "NO_TERMINATION_FOUND"
            r["first_any_family_d_after_termination"] = ""
            r["first_same_direction_family_d_after_termination"] = ""
            r["same_direction_d_exists_after_termination"] = False
            r["minutes_termination_to_same_direction_d"] = ""

    # Add a retained label without changing original measurement fields.
    retained_out = []
    for r in retained:
        x = r.copy()
        x["v1_1_status"] = "RETAINED_C"
        retained_out.append(x)

    for r in rejected:
        r["v1_1_status"] = "REJECTED_FORMER_C"

    write_csv(RETAINED_CSV, retained_out)
    write_csv(REJECTED_CSV, rejected)

    # Session-level comparison.
    sessions = sorted({
        r["session_date"] for r in old_c
    } | {
        r["session_date"] for r in new_c
    })

    session_rows = []
    for s in sessions:
        old_s = [r for r in old_c if r["session_date"] == s]
        ret_s = [r for r in retained if r["session_date"] == s]
        rej_s = [r for r in rejected if r["session_date"] == s]

        session_rows.append({
            "session_date": s,
            "old_c_count": len(old_s),
            "retained_c_count": len(ret_s),
            "rejected_former_c_count": len(rej_s),
            "rejected_with_termination_count": sum(
                bool(r.get("opposite_structure_termination_timestamp"))
                for r in rej_s
            ),
            "rejected_with_same_direction_d_after_count": sum(
                str(r.get("same_direction_d_exists_after_termination")).lower()
                == "true"
                for r in rej_s
            ),
        })

    write_csv(SESSION_CSV, session_rows)

    # Reporting.
    lines = []
    lines.append("MIDPOINT + VWAP — FAMILY C REJECTION AUDIT — 60 SESSIONS — V1")
    lines.append("=" * 112)
    lines.append("Research only. No strategy/runtime/event-rule changes in this audit.")
    lines.append("15:15 onward excluded.")
    lines.append("")
    lines.append(f"old Family C events          = {len(old_c)}")
    lines.append(f"retained V1.1 Family C       = {len(retained)}")
    lines.append(f"rejected former-C            = {len(rejected)}")
    if old_c:
        lines.append(
            f"rejected share               = "
            f"{100.0 * len(rejected) / len(old_c):.2f}%"
        )
    lines.append(f"underlying source files      = {len(underlying_files)}")
    lines.append("")

    term_found = [
        r for r in rejected
        if r.get("opposite_structure_termination_timestamp")
    ]
    no_term = [
        r for r in rejected
        if not r.get("opposite_structure_termination_timestamp")
    ]

    lines.append("REJECTION MECHANICS")
    lines.append("-" * 112)
    lines.append(
        f"rejected with opposite-structure termination found = "
        f"{len(term_found)}/{len(rejected)}"
    )
    lines.append(
        f"rejected with NO termination found                  = "
        f"{len(no_term)}"
    )
    lines.append(
        "termination -> would-be C rebreak minutes: "
        + qdesc(
            r.get("termination_to_would_be_rebreak_minutes")
            for r in term_found
        )
    )

    buckets = Counter(
        r.get("termination_gap_bucket")
        for r in rejected
    )
    for b in (
        "LE_5M",
        "6_15M",
        "16_30M",
        "31_60M",
        "61_120M",
        "GT_120M",
        "NO_TERMINATION_FOUND",
    ):
        lines.append(f"  {b:<22} = {buckets.get(b, 0):3d}")
    lines.append("")

    same_d_rows = [
        r for r in rejected
        if str(r.get("same_direction_d_exists_after_termination")).lower()
        == "true"
    ]
    lines.append("FAMILY D RELATIONSHIP")
    lines.append("-" * 112)
    lines.append(
        f"rejected former-C with same-direction D later = "
        f"{len(same_d_rows)}/{len(rejected)}"
    )
    lines.append(
        "termination -> same-direction D minutes: "
        + qdesc(
            r.get("minutes_termination_to_same_direction_d")
            for r in same_d_rows
        )
    )
    lines.append("")

    lines.append("RETAINED C vs REJECTED FORMER-C — DESCRIPTIVE OUTCOMES")
    lines.append("-" * 112)
    for label, rows in (
        ("RETAINED C", retained),
        ("REJECTED FORMER-C", rejected),
    ):
        lines.append(
            f"{label:<18} n={len(rows):3d} "
            f"MFE[{qdesc(r.get('mfe') for r in rows)}] "
            f"MAE[{qdesc(r.get('mae') for r in rows)}]"
        )
        for h in (1, 3, 5, 10, 15):
            lines.append(
                f"  +{h:2d}m directional move: "
                f"{qdesc(r.get(f'move_{h}m') for r in rows)}"
            )
    lines.append("")

    lines.append("REJECTED COUNTS BY DIRECTION")
    lines.append("-" * 112)
    dc = Counter(r["direction"] for r in rejected)
    lines.append(
        f"BEARISH={dc.get('BEARISH', 0)} "
        f"BULLISH={dc.get('BULLISH', 0)}"
    )
    lines.append("")

    lines.append("25 AUG 2026")
    lines.append("-" * 112)
    aug_rej = [r for r in rejected if r["session_date"] == "2026-08-25"]
    aug_ret = [r for r in retained if r["session_date"] == "2026-08-25"]

    for r in aug_ret:
        lines.append(
            f"RETAINED {r['entry_timestamp']} {r['direction']} "
            f"C MFE={r.get('mfe')} MAE={r.get('mae')}"
        )

    for r in aug_rej:
        lines.append(
            f"REJECTED {r['entry_timestamp']} {r['direction']} "
            f"termination={r.get('opposite_structure_termination_timestamp')} "
            f"gap={r.get('termination_to_would_be_rebreak_minutes')}m "
            f"same_dir_D={r.get('first_same_direction_family_d_after_termination')} "
            f"MFE={r.get('mfe')} MAE={r.get('mae')}"
        )

    if not aug_ret and not aug_rej:
        lines.append("No Family C rows on 25 Aug.")
    lines.append("")

    lines.append("LONGEST STALE CHAINS")
    lines.append("-" * 112)
    ranked = sorted(
        term_found,
        key=lambda r: float(r.get("termination_to_would_be_rebreak_minutes") or 0),
        reverse=True,
    )[:15]

    for r in ranked:
        lines.append(
            f"{r['session_date']} {r['direction']:<7} "
            f"termination={r['opposite_structure_termination_timestamp']} "
            f"would_be_C={r['entry_timestamp']} "
            f"gap={float(r['termination_to_would_be_rebreak_minutes']):.0f}m "
            f"same_dir_D={r.get('first_same_direction_family_d_after_termination') or '-'}"
        )
    lines.append("")

    lines.append("INTERPRETATION GUARD")
    lines.append("-" * 112)
    lines.append(
        "This audit does not decide whether V1.1 Family C is correct. "
        "It quantifies what the structural termination rule removed. "
        "Do not create time cutoffs, MFE filters, or VWAP filters from this run."
    )
    lines.append("")
    lines.append(f"RETAINED CSV = {RETAINED_CSV}")
    lines.append(f"REJECTED CSV = {REJECTED_CSV}")
    lines.append(f"SESSION CSV  = {SESSION_CSV}")
    lines.append(f"SUMMARY      = {SUMMARY_TXT}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
