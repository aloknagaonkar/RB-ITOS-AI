#!/usr/bin/env python3
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import csv
import json
import math

# ============================================================
# OPENING RED + VWAP FROZEN CANDIDATE OOS-H VALIDATION V1
# ============================================================
#
# PURPOSE
# Validate the three already-selected VWAP candidates on OOS_H
# WITHOUT changing thresholds or discovering new rules.
#
# Frozen candidates:
# A) RECENT_DOWN_CROSS_OR_REJECTION_5M
# B) MOVING_FARTHER_BELOW_VWAP_5M
# C) A AND B
#
# Research only. No strategy/execution changes.
# ============================================================

FRAMEWORK = Path(
    "data/historical-evidence/"
    "opening-candle-midpoint-framework-v1-1-oos-h.json"
)

VWAP_CSV = Path(
    "data/historical-evidence/"
    "midpoint-v2-nifty-futures-vwap-v1-all180.csv"
)

OUT_DIR = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "opening-red-vwap-oos-h-validation-v1"
)
OUT_DIR.mkdir(parents=True, exist_ok=True)

DETAIL_CSV = OUT_DIR / "opening-red-vwap-oos-h-events-v1.csv"
SUMMARY_TXT = OUT_DIR / "opening-red-vwap-oos-h-summary-v1.txt"

CONTINUATION = {
    "RED_BEARISH_BREAK_AND_GO",
    "RED_BEARISH_BASE_THEN_GO",
    "BREAK_AND_GO",
    "BREAK_AND_BASE_THEN_GO",
}

RECLAIM = {
    "RED_BREAK_BULLISH_RECLAIM",
    "FALSE_BREAK_RECLAIM",
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


def walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)


def extract_red_events():
    obj = json.loads(
        FRAMEWORK.read_text(encoding="utf-8", errors="ignore")
    )

    events = []
    seen = set()

    for d in walk(obj):
        if d.get("setup_type") != "RED_BREAK":
            continue

        sd = d.get("session_date")
        if not sd:
            continue

        midpoint_ts = d.get("midpoint_break_timestamp")
        boundary_ts = d.get("boundary_break_timestamp")
        outcome = d.get("primary_outcome")

        # Need an actual structural event record.
        if not (midpoint_ts or boundary_ts or outcome):
            continue

        key = (
            str(sd),
            str(midpoint_ts),
            str(boundary_ts),
            str(outcome),
        )
        if key in seen:
            continue
        seen.add(key)

        events.append({
            "session_date": str(sd),
            "setup_type": "RED_BREAK",
            "reference_colour": d.get("reference_colour"),
            "reference_high": d.get("reference_high"),
            "reference_low": d.get("reference_low"),
            "reference_midpoint": d.get("reference_midpoint"),
            "midpoint_break_timestamp": midpoint_ts,
            "boundary_break_timestamp": boundary_ts,
            "primary_outcome": outcome,
            "status": d.get("status"),
        })

    return events


def outcome_class(v):
    s = str(v or "")
    if s in CONTINUATION:
        return "CONTINUATION"
    if s in RECLAIM or "RECLAIM" in s:
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
    p5 = at_or_before(series, t0 - timedelta(minutes=5))

    if cur is None or p5 is None:
        return None

    recent = [
        x for x in series
        if t0 - timedelta(minutes=5) <= x["timestamp"] <= t0
    ]

    dist = cur["distance"]

    # EXACT frozen definitions from previous validation.
    had_touch_or_above = any(
        x["distance"] >= -5 for x in recent
    )
    candidate_a = bool(
        dist < -5 and had_touch_or_above
    )

    candidate_b = bool(
        dist < 0 and dist < p5["distance"]
    )

    candidate_c = bool(
        candidate_a and candidate_b
    )

    x = dict(event)
    x.update({
        "event_timestamp": cur["timestamp"].isoformat(),
        "futures_close": cur["close"],
        "session_vwap": cur["vwap"],
        "price_minus_vwap_points": dist,
        "distance_5m_ago": p5["distance"],
        "outcome_class": outcome_class(
            event.get("primary_outcome")
        ),
        "candidate_a_recent_down_cross_or_rejection_5m": candidate_a,
        "candidate_b_moving_farther_below_vwap_5m": candidate_b,
        "candidate_c_a_and_b": candidate_c,
    })

    return x


def stats(rows):
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "continuation": 0,
            "reclaim": 0,
            "other": 0,
            "continuation_rate": None,
            "reclaim_rate": None,
        }

    c = sum(r["outcome_class"] == "CONTINUATION" for r in rows)
    q = sum(r["outcome_class"] == "RECLAIM" for r in rows)
    o = n - c - q

    return {
        "n": n,
        "continuation": c,
        "reclaim": q,
        "other": o,
        "continuation_rate": 100 * c / n,
        "reclaim_rate": 100 * q / n,
    }


def fmt(label, s):
    if not s["n"]:
        return f"{label:62s} n=0"

    return (
        f"{label:62s} "
        f"n={s['n']:3d} "
        f"continuation={s['continuation']:3d} "
        f"({s['continuation_rate']:6.2f}%) "
        f"reclaim={s['reclaim']:3d} "
        f"({s['reclaim_rate']:6.2f}%) "
        f"other={s['other']:2d}"
    )


def main():
    if not FRAMEWORK.exists():
        raise SystemExit(f"MISSING FRAMEWORK: {FRAMEWORK}")
    if not VWAP_CSV.exists():
        raise SystemExit(f"MISSING VWAP: {VWAP_CSV}")

    raw_events = extract_red_events()
    by_session = load_vwap()

    rows = []
    for e in raw_events:
        x = enrich(e, by_session)
        if x is not None:
            rows.append(x)

    write_csv(DETAIL_CSV, rows)

    lines = []
    lines.append("=" * 128)
    lines.append("OPENING RED + VWAP FROZEN CANDIDATE OOS-H VALIDATION V1")
    lines.append("=" * 128)
    lines.append("")
    lines.append(f"framework = {FRAMEWORK}")
    lines.append(f"raw red events discovered = {len(raw_events)}")
    lines.append(f"VWAP-joinable red events = {len(rows)}")
    lines.append(
        f"distinct joined sessions = {len(set(r['session_date'] for r in rows))}"
    )
    if rows:
        ds = sorted(set(r["session_date"] for r in rows))
        lines.append(f"date range = {ds[0]} -> {ds[-1]}")
    lines.append("")
    lines.append(
        "NO THRESHOLD SEARCH: only the three previously selected frozen candidates are evaluated."
    )
    lines.append(
        "A = recent downward VWAP cross/rejection within 5m using the frozen -5 point touch criterion."
    )
    lines.append(
        "B = event below VWAP and farther below than 5 minutes earlier."
    )
    lines.append("C = A AND B.")
    lines.append("")

    baseline = rows
    cand_a = [
        r for r in rows
        if r["candidate_a_recent_down_cross_or_rejection_5m"]
    ]
    cand_b = [
        r for r in rows
        if r["candidate_b_moving_farther_below_vwap_5m"]
    ]
    cand_c = [
        r for r in rows
        if r["candidate_c_a_and_b"]
    ]

    lines.append(fmt("BASELINE", stats(baseline)))
    lines.append(fmt("CANDIDATE A — RECENT DOWN CROSS/REJECTION 5M", stats(cand_a)))
    lines.append(fmt("CANDIDATE B — MOVING FARTHER BELOW VWAP 5M", stats(cand_b)))
    lines.append(fmt("CANDIDATE C — A AND B", stats(cand_c)))

    lines.append("")
    lines.append("=" * 128)
    lines.append("COMPLEMENT CHECK")
    lines.append("=" * 128)

    lines.append(
        fmt(
            "NOT A",
            stats([
                r for r in rows
                if not r["candidate_a_recent_down_cross_or_rejection_5m"]
            ]),
        )
    )
    lines.append(
        fmt(
            "NOT B",
            stats([
                r for r in rows
                if not r["candidate_b_moving_farther_below_vwap_5m"]
            ]),
        )
    )
    lines.append(
        fmt(
            "NOT C",
            stats([
                r for r in rows
                if not r["candidate_c_a_and_b"]
            ]),
        )
    )

    SUMMARY_TXT.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print("\n".join(lines))
    print()
    print("=" * 128)
    print("OUTPUT FILES")
    print("=" * 128)
    print("DETAIL CSV  =", DETAIL_CSV)
    print("SUMMARY TXT =", SUMMARY_TXT)


if __name__ == "__main__":
    main()
