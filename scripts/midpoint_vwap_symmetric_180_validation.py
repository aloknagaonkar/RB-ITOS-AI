#!/usr/bin/env python3
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import csv
import json
import math
import sys

# ============================================================
# MIDPOINT + VWAP SYMMETRIC 180-SESSION VALIDATION V1
# ============================================================
#
# Goals:
# 1) Validate frozen bearish Candidate A on RED_BREAK events.
# 2) Validate the exact bullish mirror on GREEN_BREAK events.
# 3) Report both directions separately and combined.
# 4) Report the previously frozen 18 bullish + 18 bearish
#    directional sessions separately.
#
# IMPORTANT:
# - No threshold search.
# - No rule tuning.
# - No assumption that the frozen 36 sessions must be 100%.
# - Uses ONLY existing opening-candle framework event artifacts.
# - If exact framework coverage is <180 distinct sessions,
#   the script DOES NOT silently synthesize missing events.
#
# Frozen Candidate A:
# BEARISH RED:
#   event price < VWAP - 5 points
#   AND within previous 5m price was >= VWAP - 5
#
# BULLISH GREEN mirror:
#   event price > VWAP + 5 points
#   AND within previous 5m price was <= VWAP + 5
#
# ============================================================

EVIDENCE = Path("data/historical-evidence")

VWAP_CSV = EVIDENCE / "midpoint-v2-nifty-futures-vwap-v1-all180.csv"

OUT_DIR = (
    EVIDENCE
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-symmetric-180-validation-v1"
)
OUT_DIR.mkdir(parents=True, exist_ok=True)

EVENTS_CSV = OUT_DIR / "midpoint-vwap-symmetric-events-v1.csv"
SUMMARY_TXT = OUT_DIR / "midpoint-vwap-symmetric-summary-v1.txt"
COVERAGE_JSON = OUT_DIR / "midpoint-vwap-symmetric-coverage-v1.json"

FROZEN_BULLISH_18 = {
    "2026-05-18","2026-05-20","2026-05-25","2026-06-02",
    "2026-06-12","2026-06-16","2026-06-17","2026-06-18",
    "2026-06-24","2026-07-06","2026-07-10","2026-07-13",
    "2026-07-17","2026-07-27","2026-07-29","2026-08-03",
    "2026-08-25","2026-09-02",
}

FROZEN_BEARISH_18 = {
    "2026-05-12","2026-05-19","2026-05-29","2026-06-01",
    "2026-06-23","2026-06-29","2026-07-07","2026-07-08",
    "2026-07-14","2026-07-16","2026-07-22","2026-08-18",
    "2026-08-24","2026-08-26","2026-08-27","2026-09-03",
    "2026-09-07","2026-09-08",
}

BULL_CONT = {
    "GREEN_BULLISH_BREAK_AND_GO",
    "GREEN_BULLISH_BASE_THEN_GO",
}
BULL_RECLAIM = {
    "GREEN_BREAK_BEARISH_RECLAIM",
}

BEAR_CONT = {
    "RED_BEARISH_BREAK_AND_GO",
    "RED_BEARISH_BASE_THEN_GO",
}
BEAR_RECLAIM = {
    "RED_BREAK_BULLISH_RECLAIM",
}


def f(v):
    try:
        if v in (None, ""):
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def parse_ts(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v))
    except Exception:
        return None


def walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)


def write_csv(path, rows):
    if not rows:
        return
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def load_vwap():
    if not VWAP_CSV.exists():
        raise SystemExit(f"MISSING VWAP FILE: {VWAP_CSV}")

    by_session = defaultdict(list)
    with VWAP_CSV.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ts = parse_ts(r.get("timestamp"))
            close = f(r.get("close"))
            vw = f(r.get("session_vwap"))
            if ts is None or close is None or vw is None:
                continue
            by_session[str(r.get("session_date"))].append({
                "timestamp": ts,
                "close": close,
                "vwap": vw,
                "distance": close - vw,
            })

    for d in by_session:
        by_session[d].sort(key=lambda x: x["timestamp"])

    return by_session


def at_or_before(series, target):
    chosen = None
    for r in series:
        if r["timestamp"] <= target:
            chosen = r
        else:
            break
    return chosen


def framework_files():
    # Use all V1_1 framework artifacts that exist.
    # Development holds TRAIN + OOS_A/B/C/D; OOS_H may be separate.
    # If future OOS_E/F/G framework artifacts exist, they are included.
    candidates = sorted(
        EVIDENCE.glob("opening-candle-midpoint-framework-v1-1*.json")
    )

    # Avoid accidental unrelated derived artifacts.
    return [
        p for p in candidates
        if p.name.startswith("opening-candle-midpoint-framework-v1-1")
    ]


def extract_events(paths):
    events = []
    seen = set()
    per_file_sessions = {}

    for path in paths:
        try:
            obj = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue

        sessions_here = set()

        for d in walk(obj):
            setup = d.get("setup_type")
            if setup not in {"RED_BREAK", "GREEN_BREAK"}:
                continue

            sd = d.get("session_date")
            if not sd:
                continue

            sd = str(sd)
            sessions_here.add(sd)

            midpoint_ts = d.get("midpoint_break_timestamp")
            boundary_ts = d.get("boundary_break_timestamp")
            outcome = d.get("primary_outcome")

            # Require an actual event-like record.
            if not (midpoint_ts or boundary_ts or outcome):
                continue

            key = (
                sd,
                setup,
                str(midpoint_ts),
                str(boundary_ts),
                str(outcome),
            )
            if key in seen:
                continue
            seen.add(key)

            events.append({
                "framework_file": path.name,
                "session_date": sd,
                "setup_type": setup,
                "direction": "BEARISH" if setup == "RED_BREAK" else "BULLISH",
                "reference_colour": d.get("reference_colour"),
                "reference_high": d.get("reference_high"),
                "reference_low": d.get("reference_low"),
                "reference_midpoint": d.get("reference_midpoint"),
                "midpoint_break_timestamp": midpoint_ts,
                "boundary_break_timestamp": boundary_ts,
                "primary_outcome": outcome,
                "status": d.get("status"),
            })

        per_file_sessions[path.name] = sorted(sessions_here)

    return events, per_file_sessions


def classify(direction, outcome):
    s = str(outcome or "")
    if direction == "BEARISH":
        if s in BEAR_CONT:
            return "CONTINUATION"
        if s in BEAR_RECLAIM or "RECLAIM" in s:
            return "RECLAIM"
    else:
        if s in BULL_CONT:
            return "CONTINUATION"
        if s in BULL_RECLAIM or "RECLAIM" in s:
            return "RECLAIM"
    return "OTHER"


def enrich(event, by_session):
    sd = event["session_date"]
    series = by_session.get(sd, [])
    if not series:
        return None

    raw_ts = (
        event.get("boundary_break_timestamp")
        or event.get("midpoint_break_timestamp")
    )
    t0 = parse_ts(raw_ts)
    if t0 is None:
        return None

    cur = at_or_before(series, t0)
    if cur is None:
        return None

    recent = [
        x for x in series
        if t0 - timedelta(minutes=5) <= x["timestamp"] <= t0
    ]
    if not recent:
        return None

    dist = cur["distance"]
    direction = event["direction"]

    if direction == "BEARISH":
        # exact frozen bearish Candidate A
        touched_zone = any(x["distance"] >= -5 for x in recent)
        candidate_a = bool(dist < -5 and touched_zone)
    else:
        # exact bullish mirror
        touched_zone = any(x["distance"] <= 5 for x in recent)
        candidate_a = bool(dist > 5 and touched_zone)

    x = dict(event)
    x.update({
        "event_timestamp": cur["timestamp"].isoformat(),
        "futures_close": cur["close"],
        "session_vwap": cur["vwap"],
        "price_minus_vwap_points": dist,
        "candidate_a": candidate_a,
        "outcome_class": classify(direction, event.get("primary_outcome")),
        "in_frozen_bullish_18": sd in FROZEN_BULLISH_18,
        "in_frozen_bearish_18": sd in FROZEN_BEARISH_18,
        "in_frozen_directional_36": (
            sd in FROZEN_BULLISH_18 or sd in FROZEN_BEARISH_18
        ),
        "expected_direction_for_frozen_36": (
            "BULLISH" if sd in FROZEN_BULLISH_18
            else "BEARISH" if sd in FROZEN_BEARISH_18
            else None
        ),
        "matches_frozen_day_direction": (
            (sd in FROZEN_BULLISH_18 and direction == "BULLISH")
            or (sd in FROZEN_BEARISH_18 and direction == "BEARISH")
        ),
    })
    return x


def stats(rows):
    n = len(rows)
    c = sum(r.get("outcome_class") == "CONTINUATION" for r in rows)
    q = sum(r.get("outcome_class") == "RECLAIM" for r in rows)
    o = n - c - q
    return {
        "n": n,
        "continuation": c,
        "reclaim": q,
        "other": o,
        "continuation_rate": (100*c/n) if n else None,
        "reclaim_rate": (100*q/n) if n else None,
    }


def fmt(label, s):
    if not s["n"]:
        return f"{label:68s} n=0"
    return (
        f"{label:68s} "
        f"n={s['n']:3d} "
        f"continuation={s['continuation']:3d} "
        f"({s['continuation_rate']:6.2f}%) "
        f"reclaim={s['reclaim']:3d} "
        f"({s['reclaim_rate']:6.2f}%) "
        f"other={s['other']:2d}"
    )


def section(lines, title):
    lines.append("")
    lines.append("=" * 132)
    lines.append(title)
    lines.append("=" * 132)


def add_direction_report(lines, rows, direction):
    rr = [r for r in rows if r["direction"] == direction]
    a = [r for r in rr if r["candidate_a"]]
    nota = [r for r in rr if not r["candidate_a"]]

    lines.append(fmt(f"{direction} BASELINE", stats(rr)))
    lines.append(fmt(f"{direction} CANDIDATE A", stats(a)))
    lines.append(fmt(f"{direction} NOT A", stats(nota)))


def main():
    paths = framework_files()
    if not paths:
        raise SystemExit(
            "No opening-candle-midpoint-framework-v1-1*.json artifacts found."
        )

    by_session = load_vwap()
    raw_events, per_file_sessions = extract_events(paths)

    framework_sessions = sorted(
        {e["session_date"] for e in raw_events}
    )
    vwap_sessions = sorted(by_session.keys())

    rows = []
    for e in raw_events:
        x = enrich(e, by_session)
        if x is not None:
            rows.append(x)

    joined_sessions = sorted({r["session_date"] for r in rows})

    coverage = {
        "framework_files": [str(p) for p in paths],
        "framework_sessions_per_file": per_file_sessions,
        "framework_distinct_session_count": len(framework_sessions),
        "vwap_distinct_session_count": len(vwap_sessions),
        "joined_distinct_session_count": len(joined_sessions),
        "joined_event_count": len(rows),
        "target_session_count": 180,
        "full_180_framework_coverage": len(framework_sessions) >= 180,
        "missing_vwap_sessions_from_framework": sorted(
            set(framework_sessions) - set(vwap_sessions)
        ),
        "frozen_36_session_count": 36,
        "frozen_36_present_in_joined": len(
            (FROZEN_BULLISH_18 | FROZEN_BEARISH_18) & set(joined_sessions)
        ),
        "frozen_36_missing_from_joined": sorted(
            (FROZEN_BULLISH_18 | FROZEN_BEARISH_18) - set(joined_sessions)
        ),
    }

    COVERAGE_JSON.write_text(
        json.dumps(coverage, indent=2),
        encoding="utf-8",
    )
    write_csv(EVENTS_CSV, rows)

    lines = []
    lines.append("=" * 132)
    lines.append("MIDPOINT + VWAP SYMMETRIC 180-SESSION VALIDATION V1")
    lines.append("=" * 132)
    lines.append("")
    lines.append(f"framework files discovered = {len(paths)}")
    for p in paths:
        lines.append(f"  {p}")
    lines.append(f"framework distinct sessions = {len(framework_sessions)}")
    lines.append(f"VWAP distinct sessions      = {len(vwap_sessions)}")
    lines.append(f"joined distinct sessions    = {len(joined_sessions)}")
    lines.append(f"joined structural events    = {len(rows)}")
    lines.append(
        f"full exact 180 framework coverage = {coverage['full_180_framework_coverage']}"
    )
    lines.append("")
    lines.append(
        "No threshold search. Bearish Candidate A is unchanged; bullish uses the exact mirror."
    )

    section(lines, "ALL AVAILABLE EXACT FRAMEWORK SESSIONS")
    add_direction_report(lines, rows, "BEARISH")
    add_direction_report(lines, rows, "BULLISH")

    combined_a = [r for r in rows if r["candidate_a"]]
    combined_not = [r for r in rows if not r["candidate_a"]]
    lines.append(fmt("COMBINED CANDIDATE A", stats(combined_a)))
    lines.append(fmt("COMBINED NOT A", stats(combined_not)))

    section(lines, "FROZEN 36 DIRECTIONAL SESSIONS — EXPECTED DIRECTION ONLY")
    frozen_expected = [
        r for r in rows
        if r["in_frozen_directional_36"]
        and r["matches_frozen_day_direction"]
    ]
    frozen_expected_a = [r for r in frozen_expected if r["candidate_a"]]
    frozen_expected_not = [r for r in frozen_expected if not r["candidate_a"]]

    lines.append(
        f"frozen 36 session dates present = "
        f"{coverage['frozen_36_present_in_joined']}/36"
    )
    lines.append(fmt("EXPECTED-DIRECTION BASELINE", stats(frozen_expected)))
    lines.append(fmt("EXPECTED-DIRECTION CANDIDATE A", stats(frozen_expected_a)))
    lines.append(fmt("EXPECTED-DIRECTION NOT A", stats(frozen_expected_not)))

    section(lines, "FROZEN 36 DIRECTIONAL SESSIONS — COUNTER-DIRECTION CONTROL")
    frozen_counter = [
        r for r in rows
        if r["in_frozen_directional_36"]
        and not r["matches_frozen_day_direction"]
    ]
    lines.append(fmt("COUNTER-DIRECTION BASELINE", stats(frozen_counter)))
    lines.append(
        fmt(
            "COUNTER-DIRECTION CANDIDATE A",
            stats([r for r in frozen_counter if r["candidate_a"]]),
        )
    )
    lines.append(
        fmt(
            "COUNTER-DIRECTION NOT A",
            stats([r for r in frozen_counter if not r["candidate_a"]]),
        )
    )

    section(lines, "COVERAGE GUARD")
    if len(framework_sessions) < 180:
        lines.append(
            f"WARNING: exact opening-candle framework artifacts currently cover "
            f"{len(framework_sessions)} distinct sessions, not 180."
        )
        lines.append(
            "The script intentionally does NOT synthesize the missing midpoint events "
            "from futures VWAP, because that would change the original framework semantics."
        )
        lines.append(
            "Add/generate the missing V1_1 framework artifacts for the remaining sessions "
            "and rerun this exact script; it will include them automatically."
        )
    else:
        lines.append(
            "PASS: exact opening-candle framework artifacts cover at least 180 distinct sessions."
        )

    if coverage["frozen_36_missing_from_joined"]:
        lines.append("")
        lines.append("Frozen directional dates missing from exact joined coverage:")
        for d in coverage["frozen_36_missing_from_joined"]:
            lines.append(f"  {d}")

    SUMMARY_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    print()
    print("=" * 132)
    print("OUTPUT FILES")
    print("=" * 132)
    print("EVENTS CSV    =", EVENTS_CSV)
    print("COVERAGE JSON =", COVERAGE_JSON)
    print("SUMMARY TXT   =", SUMMARY_TXT)


if __name__ == "__main__":
    main()
