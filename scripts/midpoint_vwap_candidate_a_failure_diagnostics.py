#!/usr/bin/env python3
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import csv
import math
import statistics

EVIDENCE = Path("data/historical-evidence")
EVENTS_CSV = (
    EVIDENCE
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-symmetric-180-validation-v1"
    / "midpoint-vwap-symmetric-events-v1.csv"
)
VWAP_CSV = EVIDENCE / "midpoint-v2-nifty-futures-vwap-v1-all180.csv"

OUT_DIR = (
    EVIDENCE
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-candidate-a-failure-diagnostics-v1"
)
OUT_DIR.mkdir(parents=True, exist_ok=True)

DETAIL_CSV = OUT_DIR / "candidate-a-event-diagnostics-v1.csv"
FAILURES_CSV = OUT_DIR / "candidate-a-failures-v1.csv"
SUMMARY_TXT = OUT_DIR / "candidate-a-failure-diagnostics-summary-v1.txt"

# No threshold search in this diagnostic.
# These are descriptive, predeclared buckets only.
TIME_BUCKETS = [
    ("09:20-09:29", 9*60+20, 9*60+29),
    ("09:30-09:44", 9*60+30, 9*60+44),
    ("09:45-10:14", 9*60+45, 10*60+14),
    ("10:15+", 10*60+15, 15*60+30),
]
DIST_BUCKETS = [
    ("5-10", 5.0, 10.0),
    ("10-20", 10.0, 20.0),
    ("20-40", 20.0, 40.0),
    ("40+", 40.0, float("inf")),
]
CROSS_AGE_BUCKETS = [
    ("0-1m", 0.0, 1.0),
    ("2-3m", 2.0, 3.0),
    ("4-5m", 4.0, 5.0),
]


def f(v):
    try:
        if v in (None, ""):
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def b(v):
    return str(v).strip().lower() in {"true", "1", "yes", "y"}


def ts(v):
    try:
        return datetime.fromisoformat(str(v))
    except Exception:
        return None


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
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
    for r in read_csv(VWAP_CSV):
        t = ts(r.get("timestamp"))
        close = f(r.get("close"))
        vw = f(r.get("session_vwap"))
        if t is None or close is None or vw is None:
            continue
        by_session[str(r.get("session_date"))].append({
            "timestamp": t,
            "close": close,
            "vwap": vw,
            "distance": close - vw,
        })
    for k in by_session:
        by_session[k].sort(key=lambda x: x["timestamp"])
    return by_session


def at_or_before(series, target):
    chosen = None
    for r in series:
        if r["timestamp"] <= target:
            chosen = r
        else:
            break
    return chosen


def minute_of_day(t):
    return t.hour * 60 + t.minute


def time_bucket(t):
    m = minute_of_day(t)
    for label, lo, hi in TIME_BUCKETS:
        if lo <= m <= hi:
            return label
    return "OTHER"


def abs_dist_bucket(x):
    if x is None:
        return "NA"
    x = abs(x)
    for label, lo, hi in DIST_BUCKETS:
        if lo <= x < hi:
            return label
    return "<5" if x < 5 else "NA"


def cross_age_bucket(x):
    if x is None:
        return "NA"
    for label, lo, hi in CROSS_AGE_BUCKETS:
        if lo <= x <= hi:
            return label
    return "NA"


def median(values):
    vals = [x for x in values if x is not None]
    return statistics.median(vals) if vals else None


def mean(values):
    vals = [x for x in values if x is not None]
    return statistics.mean(vals) if vals else None


def pct(a, n):
    return 100.0 * a / n if n else None


def fmt_pct(x):
    return "NA" if x is None else f"{x:.2f}%"


def outcome_counts(rows):
    c = sum(r["outcome_class"] == "CONTINUATION" for r in rows)
    q = sum(r["outcome_class"] == "RECLAIM" for r in rows)
    o = len(rows) - c - q
    return len(rows), c, q, o


def add_feature_summaries(lines, rows, direction, field, label):
    sub = [r for r in rows if r["direction"] == direction and r["candidate_a"]]
    cont = [r for r in sub if r["outcome_class"] == "CONTINUATION"]
    rec = [r for r in sub if r["outcome_class"] == "RECLAIM"]

    cv = [f(r.get(field)) for r in cont]
    rv = [f(r.get(field)) for r in rec]

    lines.append(
        f"{label:36s} "
        f"CONT n={sum(x is not None for x in cv):3d} "
        f"mean={mean(cv)!s:>10} median={median(cv)!s:>10} | "
        f"RECLAIM n={sum(x is not None for x in rv):3d} "
        f"mean={mean(rv)!s:>10} median={median(rv)!s:>10}"
    )


def grouped_table(lines, rows, direction, field, title, order=None):
    sub = [r for r in rows if r["direction"] == direction and r["candidate_a"]]
    groups = defaultdict(list)
    for r in sub:
        groups[str(r.get(field, "NA"))].append(r)

    lines.append("")
    lines.append(title)
    labels = order if order else sorted(groups)
    for k in labels:
        rr = groups.get(k, [])
        if not rr:
            continue
        n, c, q, o = outcome_counts(rr)
        lines.append(
            f"  {k:20s} n={n:3d} "
            f"cont={c:3d} ({fmt_pct(pct(c,n)):>7s}) "
            f"reclaim={q:3d} ({fmt_pct(pct(q,n)):>7s}) "
            f"other={o:2d}"
        )


def main():
    if not EVENTS_CSV.exists():
        raise SystemExit(f"Missing events CSV: {EVENTS_CSV}")
    if not VWAP_CSV.exists():
        raise SystemExit(f"Missing VWAP CSV: {VWAP_CSV}")

    events = read_csv(EVENTS_CSV)
    by_session = load_vwap()

    out = []

    for r in events:
        if not b(r.get("candidate_a")):
            continue

        direction = r.get("direction")
        t0 = ts(r.get("event_timestamp"))
        sd = r.get("session_date")
        series = by_session.get(sd, [])
        if t0 is None or not series:
            continue

        cur = at_or_before(series, t0)
        p5 = at_or_before(series, t0 - timedelta(minutes=5))
        p10 = at_or_before(series, t0 - timedelta(minutes=10))
        p15 = at_or_before(series, t0 - timedelta(minutes=15))

        signed = f(r.get("price_minus_vwap_points"))
        directional_distance = None
        if signed is not None:
            directional_distance = -signed if direction == "BEARISH" else signed

        # Candidate A requires a recent touch/near-VWAP observation.
        recent = [
            x for x in series
            if t0 - timedelta(minutes=5) <= x["timestamp"] <= t0
        ]

        touch_records = []
        if direction == "BEARISH":
            touch_records = [x for x in recent if x["distance"] >= -5]
        elif direction == "BULLISH":
            touch_records = [x for x in recent if x["distance"] <= 5]

        last_touch = max((x["timestamp"] for x in touch_records), default=None)
        cross_age = (
            (t0 - last_touch).total_seconds() / 60.0
            if last_touch is not None else None
        )

        def directional_delta(prev):
            if prev is None or cur is None:
                return None
            raw = cur["distance"] - prev["distance"]
            return -raw if direction == "BEARISH" else raw

        mid_t = ts(r.get("midpoint_break_timestamp"))
        boundary_t = ts(r.get("boundary_break_timestamp"))
        midpoint_to_boundary = (
            (boundary_t - mid_t).total_seconds() / 60.0
            if mid_t and boundary_t else None
        )

        ref_hi = f(r.get("reference_high"))
        ref_lo = f(r.get("reference_low"))
        ref_range = (
            ref_hi - ref_lo
            if ref_hi is not None and ref_lo is not None else None
        )

        x = dict(r)
        x.update({
            "directional_vwap_distance_points": directional_distance,
            "abs_vwap_distance_bucket": abs_dist_bucket(directional_distance),
            "event_time_bucket": time_bucket(t0),
            "recent_touch_age_minutes": cross_age,
            "recent_touch_age_bucket": cross_age_bucket(cross_age),
            "directional_vwap_move_5m": directional_delta(p5),
            "directional_vwap_move_10m": directional_delta(p10),
            "directional_vwap_move_15m": directional_delta(p15),
            "midpoint_to_boundary_minutes": midpoint_to_boundary,
            "reference_range_points": ref_range,
        })
        out.append(x)

    write_csv(DETAIL_CSV, out)
    failures = [r for r in out if r["outcome_class"] == "RECLAIM"]
    write_csv(FAILURES_CSV, failures)

    lines = []
    lines.append("=" * 132)
    lines.append("MIDPOINT + VWAP CANDIDATE A FAILURE DIAGNOSTICS V1")
    lines.append("=" * 132)
    lines.append("")
    lines.append("NO RULE TUNING / NO THRESHOLD SEARCH.")
    lines.append("This is descriptive failure analysis of the already-frozen Candidate A only.")
    lines.append("OTHER outcomes are retained but continuation-vs-reclaim diagnostics focus on labelled outcomes.")

    for direction in ("BEARISH", "BULLISH"):
        lines.append("")
        lines.append("=" * 132)
        lines.append(direction)
        lines.append("=" * 132)

        sub = [r for r in out if r["direction"] == direction]
        n, c, q, o = outcome_counts(sub)
        lines.append(
            f"CANDIDATE A n={n} continuation={c} ({fmt_pct(pct(c,n))}) "
            f"reclaim={q} ({fmt_pct(pct(q,n))}) other={o}"
        )

        lines.append("")
        lines.append("CONTINUATION vs RECLAIM — CONTINUOUS FEATURE SUMMARY")
        add_feature_summaries(lines, out, direction,
                              "directional_vwap_distance_points",
                              "Directional VWAP distance")
        add_feature_summaries(lines, out, direction,
                              "recent_touch_age_minutes",
                              "Recent touch age minutes")
        add_feature_summaries(lines, out, direction,
                              "directional_vwap_move_5m",
                              "Directional VWAP move 5m")
        add_feature_summaries(lines, out, direction,
                              "directional_vwap_move_10m",
                              "Directional VWAP move 10m")
        add_feature_summaries(lines, out, direction,
                              "directional_vwap_move_15m",
                              "Directional VWAP move 15m")
        add_feature_summaries(lines, out, direction,
                              "midpoint_to_boundary_minutes",
                              "Midpoint->boundary minutes")
        add_feature_summaries(lines, out, direction,
                              "reference_range_points",
                              "Reference range points")

        grouped_table(
            lines, out, direction, "event_time_bucket",
            "EVENT TIME BUCKETS",
            [x[0] for x in TIME_BUCKETS] + ["OTHER"]
        )
        grouped_table(
            lines, out, direction, "abs_vwap_distance_bucket",
            "ABS DIRECTIONAL VWAP DISTANCE BUCKETS",
            [x[0] for x in DIST_BUCKETS] + ["<5", "NA"]
        )
        grouped_table(
            lines, out, direction, "recent_touch_age_bucket",
            "RECENT VWAP TOUCH/CROSS AGE BUCKETS",
            [x[0] for x in CROSS_AGE_BUCKETS] + ["NA"]
        )

        lines.append("")
        lines.append("RECLAIM / FAILURE CASES")
        for r in [x for x in sub if x["outcome_class"] == "RECLAIM"]:
            lines.append(
                f"  {r['session_date']} {r['event_timestamp']} "
                f"setup={r['setup_type']} "
                f"dist={r.get('directional_vwap_distance_points')} "
                f"touch_age={r.get('recent_touch_age_minutes')} "
                f"d5={r.get('directional_vwap_move_5m')} "
                f"d10={r.get('directional_vwap_move_10m')} "
                f"mid_to_boundary={r.get('midpoint_to_boundary_minutes')} "
                f"ref_range={r.get('reference_range_points')} "
                f"outcome={r.get('primary_outcome')}"
            )

    SUMMARY_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print()
    print("=" * 132)
    print("OUTPUT FILES")
    print("=" * 132)
    print("DETAIL CSV   =", DETAIL_CSV)
    print("FAILURES CSV =", FAILURES_CSV)
    print("SUMMARY TXT  =", SUMMARY_TXT)


if __name__ == "__main__":
    main()
