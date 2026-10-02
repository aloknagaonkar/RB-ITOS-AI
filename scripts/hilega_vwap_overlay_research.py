#!/usr/bin/env python3
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
import argparse
import csv
import json
import math
import statistics
import sys

# ============================================================
# HILEGA / OI / RED-MIDPOINT + VWAP OVERLAY RESEARCH V1
# ============================================================
#
# Research only.
# - No Hilega logic changes.
# - No signal blocking.
# - No execution / paper order changes.
# - VWAP is descriptive only in this run.
#
# Uses existing Nifty futures session VWAP:
#   midpoint-v2-nifty-futures-vwap-v1-all180.csv
#
# Main analyses:
# 1) Hilega 180-session trade baseline with VWAP alignment
# 2) Hilega + 5m/10m/15m OI relations + VWAP
# 3) Hilega + true 15->10->5 interval OI sequence + VWAP
# 4) Existing 3-5% intensity candidate + VWAP
# 5) Opening-red midpoint/boundary break outcomes + VWAP where joinable
#
# VWAP features at event time:
# - close vs session VWAP
# - distance in points / %
# - VWAP slope over 5m / 10m / 15m
# - aligned/opposed/near relative to Hilega direction
#
# IMPORTANT:
# Nifty futures VWAP is used because it is volume-weighted traded data.
# ============================================================

VWAP_CSV = Path(
    "data/historical-evidence/"
    "midpoint-v2-nifty-futures-vwap-v1-all180.csv"
)

HILEGA_TRUE_SEQ_CSV = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "true-interval-sequence-v2/"
    "hilega-180-true-interval-sequence-features-v2.csv"
)

HILEGA_WALKFORWARD_CSV = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "180-session-walkforward-v1/"
    "hilega-180-session-features-v1.csv"
)

RED_JSON = Path(
    "data/historical-evidence/"
    "opening-red-midpoint-evidence-v1-1-development.json"
)

RED_CSV = Path(
    "data/historical-evidence/"
    "opening-red-midpoint-evidence-v1-1-development.csv"
)

OUT_DIR = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "vwap-overlay-research-v1"
)
OUT_DIR.mkdir(parents=True, exist_ok=True)

HILEGA_OUT = OUT_DIR / "hilega-vwap-overlay-trades-v1.csv"
RED_OUT = OUT_DIR / "opening-red-vwap-overlay-v1.csv"
SUMMARY = OUT_DIR / "vwap-overlay-summary-v1.txt"


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


def summarize(rows, points_field="points"):
    pts = [f(r.get(points_field)) for r in rows]
    pts = [x for x in pts if x is not None]

    if not pts:
        return {
            "n": 0, "wins": 0, "losses": 0,
            "wr": None, "avg": None, "median": None,
            "total": None, "cap20": None,
        }

    wins = sum(x > 0 for x in pts)
    losses = sum(x < 0 for x in pts)
    capped = [max(-20.0, min(20.0, x)) for x in pts]

    return {
        "n": len(pts),
        "wins": wins,
        "losses": losses,
        "wr": wins / len(pts) * 100,
        "avg": sum(pts) / len(pts),
        "median": statistics.median(pts),
        "total": sum(pts),
        "cap20": sum(capped),
    }


def fmt(label, s):
    if not s["n"]:
        return f"{label:58s} n=0"

    return (
        f"{label:58s} "
        f"n={s['n']:4d} "
        f"win={s['wins']:4d} "
        f"loss={s['losses']:4d} "
        f"wr={s['wr']:6.2f}% "
        f"avg={s['avg']:+8.2f} "
        f"median={s['median']:+7.2f} "
        f"total={s['total']:+10.2f} "
        f"cap20={s['cap20']:+10.2f}"
    )


def write_csv(path, rows):
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

    by_ts = {}
    by_session = defaultdict(list)

    with VWAP_CSV.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ts = parse_ts(r.get("timestamp"))
            if ts is None:
                continue

            rec = {
                "timestamp": ts,
                "session_date": r.get("session_date"),
                "close": f(r.get("close")),
                "session_vwap": f(r.get("session_vwap")),
                "volume": f(r.get("volume")),
                "cum_volume": f(r.get("session_cumulative_volume")),
            }

            by_ts[ts] = rec
            by_session[str(r.get("session_date"))].append(rec)

    for d in by_session:
        by_session[d].sort(key=lambda x: x["timestamp"])

    return by_ts, by_session


def exact_or_backward(series, target):
    # Causal only: latest row <= target.
    chosen = None
    for r in series:
        if r["timestamp"] <= target:
            chosen = r
        else:
            break
    return chosen


def vwap_at(by_session, session_date, event_ts):
    series = by_session.get(session_date, [])
    if not series or event_ts is None:
        return None

    cur = exact_or_backward(series, event_ts)
    if cur is None:
        return None

    def prior(minutes):
        return exact_or_backward(
            series,
            event_ts - timedelta(minutes=minutes)
        )

    p5 = prior(5)
    p10 = prior(10)
    p15 = prior(15)

    close = cur["close"]
    vw = cur["session_vwap"]

    if close is None or vw is None:
        return None

    dist = close - vw
    dist_pct = dist / vw * 100.0 if vw else None

    def slope(prev):
        if prev is None:
            return None
        pv = prev.get("session_vwap")
        return None if pv is None else vw - pv

    return {
        "vwap_timestamp": cur["timestamp"].isoformat(),
        "fut_close": close,
        "session_vwap": vw,
        "price_minus_vwap_points": dist,
        "price_minus_vwap_pct": dist_pct,
        "vwap_slope_5m_points": slope(p5),
        "vwap_slope_10m_points": slope(p10),
        "vwap_slope_15m_points": slope(p15),
    }


def vwap_position(dist_points, near_points=5.0):
    if dist_points is None:
        return "UNKNOWN"
    if abs(dist_points) <= near_points:
        return "NEAR"
    return "ABOVE" if dist_points > 0 else "BELOW"


def slope_label(v):
    if v is None:
        return "UNKNOWN"
    if v > 0:
        return "RISING"
    if v < 0:
        return "FALLING"
    return "FLAT"


def alignment(direction, position, slope5):
    if position == "NEAR":
        return "NEAR_VWAP"

    if direction == "BULLISH":
        if position == "ABOVE" and slope5 == "RISING":
            return "ALIGNED_STRONG"
        if position == "ABOVE":
            return "ALIGNED_PRICE"
        if position == "BELOW" and slope5 == "FALLING":
            return "OPPOSED_STRONG"
        return "OPPOSED_PRICE"

    if direction == "BEARISH":
        if position == "BELOW" and slope5 == "FALLING":
            return "ALIGNED_STRONG"
        if position == "BELOW":
            return "ALIGNED_PRICE"
        if position == "ABOVE" and slope5 == "RISING":
            return "OPPOSED_STRONG"
        return "OPPOSED_PRICE"

    return "UNKNOWN"


def load_hilega_base():
    source = HILEGA_TRUE_SEQ_CSV if HILEGA_TRUE_SEQ_CSV.exists() else HILEGA_WALKFORWARD_CSV
    if not source.exists():
        raise SystemExit(
            "Missing Hilega feature source. Expected one of:\n"
            f"{HILEGA_TRUE_SEQ_CSV}\n{HILEGA_WALKFORWARD_CSV}"
        )

    with source.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh)), source


def enrich_hilega(rows, by_session):
    out = []

    for r in rows:
        if r.get("data_status") != "AVAILABLE":
            continue

        d = r.get("session_date")
        et = r.get("entry_time")

        try:
            hh, mm = map(int, et.split(":"))
            event_ts = datetime.fromisoformat(d).replace(
                hour=hh, minute=mm
            )
        except Exception:
            continue

        # Match timezone from VWAP session data if needed.
        series = by_session.get(d, [])
        if series and series[0]["timestamp"].tzinfo is not None:
            event_ts = event_ts.replace(
                tzinfo=series[0]["timestamp"].tzinfo
            )

        vf = vwap_at(by_session, d, event_ts)
        if vf is None:
            continue

        x = dict(r)
        x.update(vf)

        pos = vwap_position(vf["price_minus_vwap_points"])
        s5 = slope_label(vf["vwap_slope_5m_points"])

        x["vwap_position"] = pos
        x["vwap_slope_5m_state"] = s5
        x["vwap_slope_10m_state"] = slope_label(vf["vwap_slope_10m_points"])
        x["vwap_slope_15m_state"] = slope_label(vf["vwap_slope_15m_points"])
        x["vwap_alignment"] = alignment(
            r.get("direction"),
            pos,
            s5,
        )

        out.append(x)

    return out


def get_5m_relation(r):
    return r.get("i5_0_relation") or r.get("h5_relation")


def get_10m_relation(r):
    # true interval source does not have cumulative 10m relation.
    return r.get("h10_relation")


def get_15m_relation(r):
    return r.get("h15_relation")


def get_5m_intensity(r):
    return f(r.get("i5_0_intensity")) if r.get("i5_0_intensity") not in (None, "") else f(r.get("h5_intensity"))


def report_hilega(lines, rows):
    lines.append("")
    lines.append("=" * 128)
    lines.append("HILEGA + VWAP OVERLAY")
    lines.append("=" * 128)
    lines.append(fmt("ALL VWAP-JOINED HILEGA TRADES", summarize(rows)))

    for k in [
        "ALIGNED_STRONG",
        "ALIGNED_PRICE",
        "NEAR_VWAP",
        "OPPOSED_PRICE",
        "OPPOSED_STRONG",
    ]:
        lines.append(
            fmt(
                k,
                summarize([r for r in rows if r.get("vwap_alignment") == k]),
            )
        )

    lines.append("")
    lines.append("BY DIRECTION + VWAP ALIGNMENT")
    for d in ["BULLISH", "BEARISH"]:
        for k in [
            "ALIGNED_STRONG",
            "ALIGNED_PRICE",
            "NEAR_VWAP",
            "OPPOSED_PRICE",
            "OPPOSED_STRONG",
        ]:
            subset = [
                r for r in rows
                if r.get("direction") == d
                and r.get("vwap_alignment") == k
            ]
            lines.append(fmt(f"{d} | {k}", summarize(subset)))

    lines.append("")
    lines.append("=" * 128)
    lines.append("5M OI RELATION + VWAP")
    lines.append("=" * 128)

    for rel in ["MATCH", "OPPOSITE", "AMBIGUOUS"]:
        for k in [
            "ALIGNED_STRONG",
            "ALIGNED_PRICE",
            "NEAR_VWAP",
            "OPPOSED_PRICE",
            "OPPOSED_STRONG",
        ]:
            subset = [
                r for r in rows
                if get_5m_relation(r) == rel
                and r.get("vwap_alignment") == k
            ]
            lines.append(fmt(f"5M {rel} | {k}", summarize(subset)))

    lines.append("")
    lines.append("=" * 128)
    lines.append("PRIOR 3-5% INTENSITY CANDIDATE + VWAP")
    lines.append("=" * 128)

    base = []
    for r in rows:
        intensity = get_5m_intensity(r)
        if (
            get_5m_relation(r) == "MATCH"
            and intensity is not None
            and 3.0 <= intensity < 5.0
            and r.get("time_bucket") != "13:00-13:59"
        ):
            base.append(r)

    lines.append(fmt("BASE 3-5% + NO13H", summarize(base)))

    for k in [
        "ALIGNED_STRONG",
        "ALIGNED_PRICE",
        "NEAR_VWAP",
        "OPPOSED_PRICE",
        "OPPOSED_STRONG",
    ]:
        lines.append(
            fmt(
                f"3-5% | {k}",
                summarize([r for r in base if r.get("vwap_alignment") == k]),
            )
        )

    # True interval sequence overlays if available.
    if any(r.get("state_sequence_true") for r in rows):
        lines.append("")
        lines.append("=" * 128)
        lines.append("TRUE OI SEQUENCES + VWAP — minimum n=8")
        lines.append("=" * 128)

        groups = defaultdict(list)
        for r in rows:
            seq = r.get("state_sequence_true")
            if seq:
                groups[(seq, r.get("vwap_alignment"))].append(r)

        ranked = []
        for key, subset in groups.items():
            s = summarize(subset)
            if s["n"] >= 8:
                ranked.append((key, s))

        ranked.sort(
            key=lambda x: (
                x[1]["cap20"],
                x[1]["median"],
                x[1]["n"],
            ),
            reverse=True,
        )

        for (seq, align), s in ranked[:25]:
            lines.append(fmt(f"{seq} | {align}", s))


def walk_dicts(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk_dicts(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk_dicts(v)


def load_red_events():
    events = []

    if RED_JSON.exists():
        obj = json.loads(
            RED_JSON.read_text(encoding="utf-8", errors="ignore")
        )

        # Prefer explicit per-session objects that include session_date
        # and primary/outcome classification.
        for d in walk_dicts(obj):
            sd = d.get("session_date")
            if not sd:
                continue

            outcome = (
                d.get("primary_outcome")
                or d.get("outcome")
                or d.get("outcome_label")
                or d.get("classification")
            )

            # Keep likely top-level event/session records.
            if outcome or d.get("midpoint_break_timestamp") or d.get("boundary_break_timestamp"):
                events.append({
                    "session_date": str(sd),
                    "outcome": outcome,
                    "midpoint_break_timestamp": d.get("midpoint_break_timestamp"),
                    "boundary_break_timestamp": d.get("boundary_break_timestamp"),
                    "reference_low": d.get("reference_low"),
                    "reference_midpoint": d.get("reference_midpoint"),
                    "setup_type": d.get("setup_type"),
                    "direction": d.get("direction") or "BEARISH",
                })

    # Deduplicate by session/outcome/timestamps.
    seen = set()
    uniq = []

    for e in events:
        key = (
            e.get("session_date"),
            e.get("outcome"),
            e.get("midpoint_break_timestamp"),
            e.get("boundary_break_timestamp"),
        )
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)

    return uniq


def enrich_red(events, by_session):
    out = []

    for e in events:
        d = e.get("session_date")
        raw_ts = e.get("boundary_break_timestamp") or e.get("midpoint_break_timestamp")
        event_ts = parse_ts(raw_ts)

        if event_ts is None:
            continue

        vf = vwap_at(by_session, d, event_ts)
        if vf is None:
            continue

        x = dict(e)
        x.update(vf)

        pos = vwap_position(vf["price_minus_vwap_points"])
        s5 = slope_label(vf["vwap_slope_5m_points"])

        x["vwap_position"] = pos
        x["vwap_slope_5m_state"] = s5
        x["vwap_alignment"] = alignment(
            "BEARISH",
            pos,
            s5,
        )

        out.append(x)

    return out


def report_red(lines, rows):
    lines.append("")
    lines.append("=" * 128)
    lines.append("OPENING RED MIDPOINT / LOW BREAK + VWAP")
    lines.append("=" * 128)

    if not rows:
        lines.append("No joinable red-event rows found.")
        return

    # Here outcomes are categorical, so show counts and continuation fraction.
    continuation_labels = {
        "BREAK_AND_GO",
        "BREAK_AND_BASE_THEN_GO",
        "RED_BEARISH_BREAK_AND_GO",
        "RED_BEARISH_BASE_THEN_GO",
    }

    def stats(subset):
        n = len(subset)
        if not n:
            return "n=0"

        good = sum(
            str(r.get("outcome")) in continuation_labels
            for r in subset
        )

        reclaim = sum(
            "RECLAIM" in str(r.get("outcome"))
            for r in subset
        )

        return (
            f"n={n:3d} "
            f"continuation={good:3d} ({good/n*100:6.2f}%) "
            f"reclaim={reclaim:3d} ({reclaim/n*100:6.2f}%)"
        )

    lines.append("ALL".ljust(42) + stats(rows))

    for k in [
        "ALIGNED_STRONG",
        "ALIGNED_PRICE",
        "NEAR_VWAP",
        "OPPOSED_PRICE",
        "OPPOSED_STRONG",
    ]:
        subset = [r for r in rows if r.get("vwap_alignment") == k]
        lines.append(k.ljust(42) + stats(subset))


def main():
    _, by_session = load_vwap()

    hilega_raw, hilega_source = load_hilega_base()
    hilega = enrich_hilega(hilega_raw, by_session)
    write_csv(HILEGA_OUT, hilega)

    red_events = load_red_events()
    red = enrich_red(red_events, by_session)
    if red:
        write_csv(RED_OUT, red)

    lines = []

    lines.append("=" * 128)
    lines.append("HILEGA / OI / RED-MIDPOINT + VWAP OVERLAY RESEARCH V1")
    lines.append("=" * 128)
    lines.append("")
    lines.append(f"VWAP source   = {VWAP_CSV}")
    lines.append(f"Hilega source = {hilega_source}")
    lines.append(
        "VWAP is descriptive only; no Hilega logic or execution settings are changed."
    )
    lines.append(
        "VWAP joins use exact-or-backward timestamps only; no future VWAP values are used."
    )

    report_hilega(lines, hilega)
    report_red(lines, red)

    SUMMARY.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print("\n".join(lines))
    print()
    print("=" * 128)
    print("OUTPUT FILES")
    print("=" * 128)
    print("HILEGA CSV =", HILEGA_OUT)
    if red:
        print("RED CSV    =", RED_OUT)
    print("SUMMARY    =", SUMMARY)


if __name__ == "__main__":
    main()
