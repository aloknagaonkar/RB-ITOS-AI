#!/usr/bin/env python3
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import csv
import math
import statistics

# ============================================================
# OPENING RED MIDPOINT / LOW BREAK + VWAP VALIDATION V1
# ============================================================
#
# Research only.
# No trading rule is changed or enabled.
#
# Input created by the previous VWAP overlay run:
#   opening-red-vwap-overlay-v1.csv
#
# The script validates whether bearish VWAP context helps separate:
#   CONTINUATION
#     BREAK_AND_GO
#     BREAK_AND_BASE_THEN_GO
#   from
#   FALSE_BREAK_RECLAIM
#
# It also derives causal VWAP context immediately before the red event:
# - below / near / above VWAP
# - VWAP 5m / 10m / 15m slope
# - distance below VWAP
# - moving farther below VWAP
# - recent downward VWAP cross/rejection
# - persistent below VWAP
#
# No future bars are used as features.
# ============================================================

RED_OVERLAY = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "vwap-overlay-research-v1/"
    "opening-red-vwap-overlay-v1.csv"
)

VWAP_CSV = Path(
    "data/historical-evidence/"
    "midpoint-v2-nifty-futures-vwap-v1-all180.csv"
)

OUT_DIR = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "opening-red-vwap-validation-v1"
)
OUT_DIR.mkdir(parents=True, exist_ok=True)

DETAIL_CSV = OUT_DIR / "opening-red-vwap-validation-events-v1.csv"
CANDIDATE_CSV = OUT_DIR / "opening-red-vwap-validation-candidates-v1.csv"
SUMMARY_TXT = OUT_DIR / "opening-red-vwap-validation-summary-v1.txt"

CONTINUATION = {
    "BREAK_AND_GO",
    "BREAK_AND_BASE_THEN_GO",
    "RED_BEARISH_BREAK_AND_GO",
    "RED_BEARISH_BASE_THEN_GO",
}

RECLAIM_KEYS = {
    "FALSE_BREAK_RECLAIM",
    "RED_FALSE_BREAK_RECLAIM",
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


def label_outcome(raw):
    s = str(raw or "")
    if s in CONTINUATION:
        return "CONTINUATION"
    if s in RECLAIM_KEYS or "RECLAIM" in s:
        return "RECLAIM"
    return "OTHER"


def derive_context(row, by_session):
    d = row.get("session_date")
    series = by_session.get(d, [])

    raw_ts = (
        row.get("boundary_break_timestamp")
        or row.get("midpoint_break_timestamp")
        or row.get("vwap_timestamp")
    )
    t0 = parse_ts(raw_ts)

    if not series or t0 is None:
        return None

    def p(minutes):
        return at_or_before(series, t0 - timedelta(minutes=minutes))

    cur = at_or_before(series, t0)
    p1 = p(1)
    p3 = p(3)
    p5 = p(5)
    p10 = p(10)
    p15 = p(15)

    if cur is None:
        return None

    dist = cur["distance"]

    def slope(prev):
        if prev is None:
            return None
        return cur["vwap"] - prev["vwap"]

    def pos(rec):
        if rec is None:
            return None
        if abs(rec["distance"]) <= 5:
            return "NEAR"
        return "ABOVE" if rec["distance"] > 0 else "BELOW"

    # bearish rejection/cross context:
    # event is below VWAP now, and within previous 5m price was at/above or near VWAP.
    recent_records = [
        x for x in series
        if t0 - timedelta(minutes=5) <= x["timestamp"] <= t0
    ]

    had_touch_or_above = any(x["distance"] >= -5 for x in recent_records)
    recent_down_cross = bool(dist < -5 and had_touch_or_above)

    # persistent below: all available records in last 3 / 5 min are below VWAP by > 0.
    last3 = [
        x for x in series
        if t0 - timedelta(minutes=3) <= x["timestamp"] <= t0
    ]
    last5 = recent_records

    persistent_below_3 = bool(last3 and all(x["distance"] < 0 for x in last3))
    persistent_below_5 = bool(last5 and all(x["distance"] < 0 for x in last5))

    moving_farther_below_5 = (
        p5 is not None
        and dist < 0
        and dist < p5["distance"]
    )

    x = dict(row)
    x.update({
        "event_timestamp": cur["timestamp"].isoformat(),
        "outcome_class": label_outcome(row.get("outcome")),
        "vwap_distance_points_recalc": dist,
        "vwap_position_recalc": pos(cur),
        "vwap_slope_5m_recalc": slope(p5),
        "vwap_slope_10m_recalc": slope(p10),
        "vwap_slope_15m_recalc": slope(p15),
        "distance_1m_ago": None if p1 is None else p1["distance"],
        "distance_3m_ago": None if p3 is None else p3["distance"],
        "distance_5m_ago": None if p5 is None else p5["distance"],
        "recent_down_cross_or_rejection_5m": recent_down_cross,
        "persistent_below_vwap_3m": persistent_below_3,
        "persistent_below_vwap_5m": persistent_below_5,
        "moving_farther_below_vwap_5m": moving_farther_below_5,
    })

    if dist < -20:
        x["below_vwap_distance_bucket"] = "<-20"
    elif dist < -10:
        x["below_vwap_distance_bucket"] = "-20_to_-10"
    elif dist < -5:
        x["below_vwap_distance_bucket"] = "-10_to_-5"
    elif dist < 0:
        x["below_vwap_distance_bucket"] = "-5_to_0"
    elif dist <= 5:
        x["below_vwap_distance_bucket"] = "0_to_5"
    else:
        x["below_vwap_distance_bucket"] = ">5"

    return x


def stats(rows):
    n = len(rows)
    if not n:
        return {
            "n": 0,
            "continuation": 0,
            "reclaim": 0,
            "other": 0,
            "continuation_rate": None,
            "reclaim_rate": None,
        }

    c = sum(r.get("outcome_class") == "CONTINUATION" for r in rows)
    q = sum(r.get("outcome_class") == "RECLAIM" for r in rows)
    o = n - c - q

    return {
        "n": n,
        "continuation": c,
        "reclaim": q,
        "other": o,
        "continuation_rate": c / n * 100,
        "reclaim_rate": q / n * 100,
    }


def fmt(label, s):
    if not s["n"]:
        return f"{label:52s} n=0"

    return (
        f"{label:52s} "
        f"n={s['n']:3d} "
        f"continuation={s['continuation']:3d} "
        f"({s['continuation_rate']:6.2f}%) "
        f"reclaim={s['reclaim']:3d} "
        f"({s['reclaim_rate']:6.2f}%) "
        f"other={s['other']:2d}"
    )


def split_dates(rows):
    dates = sorted({r["session_date"] for r in rows})

    # chronological 40/30/remainder session split
    train_dates = set(dates[:40])
    validation_dates = set(dates[40:70])
    evaluation_dates = set(dates[70:])

    return train_dates, validation_dates, evaluation_dates


def eval_candidate(name, pred, rows, splits):
    train_dates, val_dates, eval_dates = splits

    subsets = {
        "ALL": [r for r in rows if pred(r)],
        "TRAIN": [r for r in rows if r["session_date"] in train_dates and pred(r)],
        "VALIDATION": [r for r in rows if r["session_date"] in val_dates and pred(r)],
        "EVALUATION": [r for r in rows if r["session_date"] in eval_dates and pred(r)],
    }

    rec = {"candidate": name}

    for split, rr in subsets.items():
        s = stats(rr)
        p = split.lower()
        rec[f"{p}_n"] = s["n"]
        rec[f"{p}_continuation"] = s["continuation"]
        rec[f"{p}_reclaim"] = s["reclaim"]
        rec[f"{p}_continuation_rate"] = s["continuation_rate"]
        rec[f"{p}_reclaim_rate"] = s["reclaim_rate"]

    return rec, subsets


def main():
    if not RED_OVERLAY.exists():
        raise SystemExit(f"MISSING: {RED_OVERLAY}")
    if not VWAP_CSV.exists():
        raise SystemExit(f"MISSING: {VWAP_CSV}")

    with RED_OVERLAY.open(newline="", encoding="utf-8") as fh:
        raw = list(csv.DictReader(fh))

    by_session = load_vwap()

    rows = []
    for r in raw:
        x = derive_context(r, by_session)
        if x is not None:
            rows.append(x)

    write_csv(DETAIL_CSV, rows)

    splits = split_dates(rows)

    candidates = [
        ("BASELINE", lambda r: True),

        ("BELOW_VWAP", lambda r:
            f(r.get("vwap_distance_points_recalc")) is not None
            and f(r.get("vwap_distance_points_recalc")) < 0),

        ("BELOW_VWAP_AND_5M_FALLING", lambda r:
            f(r.get("vwap_distance_points_recalc")) is not None
            and f(r.get("vwap_distance_points_recalc")) < 0
            and f(r.get("vwap_slope_5m_recalc")) is not None
            and f(r.get("vwap_slope_5m_recalc")) < 0),

        ("BELOW_VWAP_AND_10M_FALLING", lambda r:
            f(r.get("vwap_distance_points_recalc")) is not None
            and f(r.get("vwap_distance_points_recalc")) < 0
            and f(r.get("vwap_slope_10m_recalc")) is not None
            and f(r.get("vwap_slope_10m_recalc")) < 0),

        ("BELOW_VWAP_AND_15M_FALLING", lambda r:
            f(r.get("vwap_distance_points_recalc")) is not None
            and f(r.get("vwap_distance_points_recalc")) < 0
            and f(r.get("vwap_slope_15m_recalc")) is not None
            and f(r.get("vwap_slope_15m_recalc")) < 0),

        ("PERSISTENT_BELOW_3M", lambda r:
            r.get("persistent_below_vwap_3m") is True),

        ("PERSISTENT_BELOW_5M", lambda r:
            r.get("persistent_below_vwap_5m") is True),

        ("MOVING_FARTHER_BELOW_5M", lambda r:
            r.get("moving_farther_below_vwap_5m") is True),

        ("RECENT_DOWN_CROSS_OR_REJECTION_5M", lambda r:
            r.get("recent_down_cross_or_rejection_5m") is True),

        ("BELOW_AND_FALLING_AND_FARTHER", lambda r:
            f(r.get("vwap_distance_points_recalc")) is not None
            and f(r.get("vwap_distance_points_recalc")) < 0
            and f(r.get("vwap_slope_5m_recalc")) is not None
            and f(r.get("vwap_slope_5m_recalc")) < 0
            and r.get("moving_farther_below_vwap_5m") is True),

        ("DISTANCE_-10_TO_-5", lambda r:
            r.get("below_vwap_distance_bucket") == "-10_to_-5"),

        ("DISTANCE_-20_TO_-10", lambda r:
            r.get("below_vwap_distance_bucket") == "-20_to_-10"),

        ("DISTANCE_LT_-20", lambda r:
            r.get("below_vwap_distance_bucket") == "<-20"),
    ]

    lines = []
    lines.append("=" * 128)
    lines.append("OPENING RED MIDPOINT / LOW BREAK + VWAP VALIDATION V1")
    lines.append("=" * 128)
    lines.append("")
    lines.append(f"events joined = {len(rows)}")
    lines.append(
        "Chronological session split: first 40 TRAIN, next 30 VALIDATION, remainder EVALUATION."
    )
    lines.append(
        "All VWAP features are exact-or-backward only; no future VWAP values are used."
    )

    candidate_rows = []

    for name, pred in candidates:
        rec, subsets = eval_candidate(name, pred, rows, splits)
        candidate_rows.append(rec)

        lines.append("")
        lines.append(name)
        lines.append(fmt("  ALL", stats(subsets["ALL"])))
        lines.append(fmt("  TRAIN", stats(subsets["TRAIN"])))
        lines.append(fmt("  VALIDATION", stats(subsets["VALIDATION"])))
        lines.append(fmt("  EVALUATION", stats(subsets["EVALUATION"])))

    lines.append("")
    lines.append("=" * 128)
    lines.append("DISTANCE BUCKETS")
    lines.append("=" * 128)

    bucket_order = [
        "<-20",
        "-20_to_-10",
        "-10_to_-5",
        "-5_to_0",
        "0_to_5",
        ">5",
    ]

    for b in bucket_order:
        rr = [r for r in rows if r.get("below_vwap_distance_bucket") == b]
        lines.append(fmt(b, stats(rr)))

    SUMMARY_TXT.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    write_csv(CANDIDATE_CSV, candidate_rows)

    print("\n".join(lines))
    print()
    print("=" * 128)
    print("OUTPUT FILES")
    print("=" * 128)
    print("DETAIL CSV    =", DETAIL_CSV)
    print("CANDIDATE CSV =", CANDIDATE_CSV)
    print("SUMMARY TXT   =", SUMMARY_TXT)


if __name__ == "__main__":
    main()
