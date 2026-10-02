#!/usr/bin/env python3
from pathlib import Path
from collections import defaultdict
import csv
import json
import math

EVIDENCE = Path("data/historical-evidence")

DETAIL_CSV = (
    EVIDENCE
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-candidate-a-failure-diagnostics-v1"
    / "candidate-a-event-diagnostics-v1.csv"
)

FRAMEWORK_FILES = sorted(
    EVIDENCE.glob("opening-candle-midpoint-framework-v1-1*.json")
)

OUT_DIR = (
    EVIDENCE
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-candidate-a-block-stability-v1"
)
OUT_DIR.mkdir(parents=True, exist_ok=True)

EVENTS_OUT = OUT_DIR / "candidate-a-block-stability-events-v1.csv"
SUMMARY_OUT = OUT_DIR / "candidate-a-block-stability-summary-v1.txt"

EXPECTED_BLOCKS = [
    "TRAIN", "OOS_A", "OOS_B", "OOS_C", "OOS_D",
    "OOS_E", "OOS_F", "OOS_G", "OOS_H",
]

DISTANCE_BUCKETS = [
    ("5-10", 5.0, 10.0),
    ("10-20", 10.0, 20.0),
    ("20+", 20.0, float("inf")),
]

TOUCH_BUCKETS = [
    ("0-3m", 0.0, 3.0),
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


def walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)


def normalize_block(v):
    if not v:
        return None
    s = str(v).strip().upper().replace("-", "_")
    return s


def load_block_map():
    """
    Build mapping using exact framework event identity.
    Falls back to (session_date, setup_type) because framework has one RED
    and one GREEN primary event per session.
    """
    exact = {}
    simple = {}
    block_sessions = defaultdict(set)

    for path in FRAMEWORK_FILES:
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        for d in walk(obj):
            setup = d.get("setup_type")
            sd = d.get("session_date")
            block = normalize_block(d.get("block"))

            if setup not in {"RED_BREAK", "GREEN_BREAK"} or not sd:
                continue

            # Some framework rows may inherit block only at segment level.
            # If missing, infer by known file structure only where unambiguous.
            if block is None:
                if "oos-h" in path.name:
                    block = "OOS_H"

            if block is None:
                continue

            sd = str(sd)
            block_sessions[block].add(sd)

            key = (
                sd,
                setup,
                str(d.get("midpoint_break_timestamp")),
                str(d.get("boundary_break_timestamp")),
            )
            exact[key] = block
            simple[(sd, setup)] = block

    return exact, simple, block_sessions


def distance_bucket(x):
    if x is None:
        return "NA"
    for label, lo, hi in DISTANCE_BUCKETS:
        if lo <= x < hi:
            return label
    return "<5"


def touch_bucket(x):
    if x is None:
        return "NA"
    for label, lo, hi in TOUCH_BUCKETS:
        if lo <= x <= hi:
            return label
    return "NA"


def counts(rows):
    n = len(rows)
    c = sum(r["outcome_class"] == "CONTINUATION" for r in rows)
    q = sum(r["outcome_class"] == "RECLAIM" for r in rows)
    o = n - c - q
    return n, c, q, o


def pct(x, n):
    return None if n == 0 else 100.0 * x / n


def fmtp(x):
    return "NA" if x is None else f"{x:.2f}%"


def line(label, rows):
    n, c, q, o = counts(rows)
    return (
        f"{label:38s} n={n:3d} "
        f"cont={c:3d} ({fmtp(pct(c,n)):>7s}) "
        f"reclaim={q:3d} ({fmtp(pct(q,n)):>7s}) "
        f"other={o:2d}"
    )


def main():
    if not DETAIL_CSV.exists():
        raise SystemExit(f"Missing diagnostic CSV: {DETAIL_CSV}")

    rows = read_csv(DETAIL_CSV)
    exact, simple, block_sessions = load_block_map()

    enriched = []
    unmapped = []

    for r in rows:
        key = (
            str(r.get("session_date")),
            r.get("setup_type"),
            str(r.get("midpoint_break_timestamp")),
            str(r.get("boundary_break_timestamp")),
        )
        block = exact.get(key)
        if block is None:
            block = simple.get((str(r.get("session_date")), r.get("setup_type")))

        x = dict(r)
        x["block"] = block or "UNMAPPED"
        x["distance_stability_bucket"] = distance_bucket(
            f(r.get("directional_vwap_distance_points"))
        )
        x["touch_age_stability_bucket"] = touch_bucket(
            f(r.get("recent_touch_age_minutes"))
        )

        if block is None:
            unmapped.append(x)

        enriched.append(x)

    write_csv(EVENTS_OUT, enriched)

    lines = []
    lines.append("=" * 132)
    lines.append("CANDIDATE A BLOCK STABILITY V1 — FULL 180-SESSION UNIVERSE")
    lines.append("=" * 132)
    lines.append("")
    lines.append("Candidate A is unchanged. No threshold optimization.")
    lines.append("20-session blocks are stability slices of the SAME 180-session dataset.")
    lines.append("Main evidence remains the full 180-session result.")
    lines.append("")
    lines.append(f"Candidate A events analyzed = {len(enriched)}")
    lines.append(f"Unmapped events = {len(unmapped)}")

    lines.append("")
    lines.append("=" * 132)
    lines.append("FULL 180 — PRIMARY RESULT")
    lines.append("=" * 132)

    for direction in ("BEARISH", "BULLISH"):
        sub = [r for r in enriched if r["direction"] == direction]
        lines.append(line(direction, sub))

    lines.append(line("COMBINED", enriched))

    for direction in ("BEARISH", "BULLISH"):
        lines.append("")
        lines.append("=" * 132)
        lines.append(f"{direction} — BLOCK STABILITY")
        lines.append("=" * 132)

        for block in EXPECTED_BLOCKS:
            rr = [
                r for r in enriched
                if r["direction"] == direction and r["block"] == block
            ]
            lines.append(line(block, rr))

        lines.append("")
        lines.append(f"{direction} — DISTANCE STABILITY BY BLOCK")
        for block in EXPECTED_BLOCKS:
            lines.append(f"  [{block}]")
            for bucket in ("5-10", "10-20", "20+"):
                rr = [
                    r for r in enriched
                    if r["direction"] == direction
                    and r["block"] == block
                    and r["distance_stability_bucket"] == bucket
                ]
                lines.append("    " + line(bucket, rr))

        lines.append("")
        lines.append(f"{direction} — RECENT TOUCH AGE STABILITY BY BLOCK")
        for block in EXPECTED_BLOCKS:
            lines.append(f"  [{block}]")
            for bucket in ("0-3m", "4-5m"):
                rr = [
                    r for r in enriched
                    if r["direction"] == direction
                    and r["block"] == block
                    and r["touch_age_stability_bucket"] == bucket
                ]
                lines.append("    " + line(bucket, rr))

    lines.append("")
    lines.append("=" * 132)
    lines.append("CROSS-BLOCK CONSISTENCY COUNTS")
    lines.append("=" * 132)

    # Descriptive consistency only, not a promotion rule.
    for direction in ("BEARISH", "BULLISH"):
        positive_blocks = 0
        negative_blocks = 0
        tied_blocks = 0
        nonempty_blocks = 0

        for block in EXPECTED_BLOCKS:
            rr = [
                r for r in enriched
                if r["direction"] == direction and r["block"] == block
                and r["outcome_class"] in {"CONTINUATION", "RECLAIM"}
            ]
            if not rr:
                continue
            nonempty_blocks += 1
            n, c, q, _ = counts(rr)
            if c > q:
                positive_blocks += 1
            elif c < q:
                negative_blocks += 1
            else:
                tied_blocks += 1

        lines.append(
            f"{direction}: blocks_with_data={nonempty_blocks} "
            f"continuation>reclaim={positive_blocks} "
            f"continuation<reclaim={negative_blocks} "
            f"ties={tied_blocks}"
        )

    lines.append("")
    lines.append("INTERPRETATION GUARD")
    lines.append(
        "Do not promote 20-point distance, time-of-day, or touch-age cutoffs "
        "from this report alone. These were discovered descriptively in the "
        "same 180-session universe and need future/live confirmation."
    )

    SUMMARY_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print()
    print("=" * 132)
    print("OUTPUT FILES")
    print("=" * 132)
    print("EVENTS CSV  =", EVENTS_OUT)
    print("SUMMARY TXT =", SUMMARY_OUT)


if __name__ == "__main__":
    main()
