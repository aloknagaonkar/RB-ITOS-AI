#!/usr/bin/env python3
"""
B FAMILY — RISK GEOMETRY V7

Research question
-----------------
How much adverse excursion do genuine B winners actually require, and how
quickly do weak B events deteriorate?

This script DOES NOT optimize or choose a stop.

Canonical source
----------------
Imports the repository's frozen V1.1 setup-family implementation directly:
  scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py

Universe
--------
All canonical B events across the 180-session framework:
- latest 60 development sample
- older 120-session validation sample
- combined

Diagnostics
-----------
1. MFE / MAE distribution.
2. MFE bands:
     <20
     20 to <50
     >=50 NIFTY points
3. For events that eventually reach +10/+20/+30/+50/+75/+100:
   - maximum adverse excursion strictly BEFORE the first target-touch candle
   - time to first target-touch candle
   - whether stop thresholds 5/10/15/20/25/30 were already breached
     before that target
   - same-candle stop/target ambiguity separately
4. For weak events (MFE <20):
   - time to first -5/-10/-15/-20/-25/-30 adverse threshold
   - frequency of those adverse thresholds
5. Bull / Bear and development / older splits.

Intrabar caution
----------------
With 1-minute OHLC, the order of high and low inside the SAME candle is unknown.
Therefore:
- "stop breached before target" only uses candles strictly before the first
  target-touch candle.
- if stop and target are both reachable inside the target-touch candle,
  it is marked SAME_BAR_AMBIGUOUS and is NOT treated as definitely stopped.

Underlying NIFTY points only. Not CE/PE option-premium P&L.
"""

from __future__ import annotations

import csv
import importlib.util
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
KNOWN = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "midpoint-vwap-setup-family-60-session-validation-v1-1"
    / "setup-family-events-v1-1.csv"
)

OUT = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "b-family-risk-geometry-v7"
)
EVENT_CSV = OUT / "b-family-risk-geometry-events-v7.csv"
MILESTONE_CSV = OUT / "b-family-risk-geometry-milestones-v7.csv"
WEAK_CSV = OUT / "b-family-risk-geometry-weak-events-v7.csv"
SUMMARY_TXT = OUT / "b-family-risk-geometry-summary-v7.txt"

TARGETS = (10, 20, 30, 50, 75, 100)
STOPS = (5, 10, 15, 20, 25, 30)
WEAK_MFE_CUTOFF = 20.0


def load_canonical():
    spec = importlib.util.spec_from_file_location("bcanon_v1_1", CANON)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except Exception:
        return None


def minutes(a, b):
    if not a or not b:
        return None
    return int((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() // 60)


def percentile(vals, p):
    xs = sorted(float(x) for x in vals if x is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return xs[lo] * (1-frac) + xs[hi] * frac


def desc(vals):
    xs = [float(x) for x in vals if x is not None]
    if not xs:
        return "n=0"
    return (
        f"n={len(xs)} mean={mean(xs):+.2f} median={median(xs):+.2f} "
        f"p25={percentile(xs,.25):+.2f} p75={percentile(xs,.75):+.2f} "
        f"min={min(xs):+.2f} max={max(xs):+.2f}"
    )


def known_latest60_keys():
    rows = list(csv.DictReader(open(KNOWN, newline="")))
    return {
        (r["session_date"], r["direction"], r["entry_timestamp"])
        for r in rows
        if r.get("family") == "B_DELAYED_FULL_CANDIDATE_A"
    }


def canonical_events(m):
    _, framework = m.load_framework()
    _, underlying, dup_conflicts = m.load_underlying()
    futures = m.load_futures()

    sessions = sorted({e["session_date"] for e in framework})
    latest60 = set(sessions[-60:])

    detected = []
    for e in framework:
        day = e["session_date"]
        b = m.family_b_for_event(e, underlying.get(day, {}), futures.get(day, {}))
        if b:
            ev = m.measure_event(dict(b), underlying.get(day, {}))
            ev["sample"] = "DEVELOPMENT_LATEST60" if day in latest60 else "OLDER_120"
            detected.append(ev)

    detected.sort(key=lambda r:(r["session_date"], r["entry_timestamp"], r["direction"]))

    dev_keys = {
        (r["session_date"], r["direction"], r["entry_timestamp"])
        for r in detected
        if r["sample"] == "DEVELOPMENT_LATEST60"
    }
    parity = dev_keys == known_latest60_keys()

    return detected, underlying, futures, sessions, dup_conflicts, parity


def event_bars(ev, underlying):
    day = ev["session_date"]
    entry_ts = ev["entry_timestamp"]
    invalid = ev.get("structural_invalidation_timestamp") or ""

    bars = []
    for ts, bar in sorted(underlying.get(day, {}).items()):
        if ts <= entry_ts or ts[11:16] > "15:14":
            continue
        if invalid and ts >= invalid:
            break
        bars.append((ts, bar))
    return bars


def favorable_points(direction, entry, bar):
    if direction == "BULLISH":
        return bar["high"] - entry
    return entry - bar["low"]


def adverse_points(direction, entry, bar):
    # negative = adverse
    if direction == "BULLISH":
        return bar["low"] - entry
    return entry - bar["high"]


def first_target_touch(ev, bars, target):
    direction = ev["direction"]
    entry = num(ev.get("entry_close"))
    for ts, bar in bars:
        if favorable_points(direction, entry, bar) >= target:
            return ts, bar
    return None, None


def milestone_geometry(ev, bars, target):
    direction = ev["direction"]
    entry = num(ev.get("entry_close"))
    t_ts, t_bar = first_target_touch(ev, bars, target)

    if not t_ts:
        return {
            "reached": False,
            "target_timestamp": None,
            "minutes_to_target": None,
            "prior_mae": None,
            "target_bar_adverse": None,
            **{f"stop_{s}_status": "TARGET_NOT_REACHED" for s in STOPS},
        }

    prior = [(ts, b) for ts, b in bars if ts < t_ts]
    prior_adv = [adverse_points(direction, entry, b) for _, b in prior]
    prior_mae = min(prior_adv) if prior_adv else 0.0
    target_bar_adv = adverse_points(direction, entry, t_bar)

    out = {
        "reached": True,
        "target_timestamp": t_ts,
        "minutes_to_target": minutes(ev["entry_timestamp"], t_ts),
        "prior_mae": prior_mae,
        "target_bar_adverse": target_bar_adv,
    }

    for s in STOPS:
        if prior_mae <= -s:
            status = "STOP_BREACHED_BEFORE_TARGET"
        elif target_bar_adv <= -s:
            status = "SAME_BAR_AMBIGUOUS"
        else:
            status = "TARGET_REACHED_WITHOUT_PRIOR_STOP"
        out[f"stop_{s}_status"] = status

    return out


def first_adverse_touch(ev, bars, stop):
    direction = ev["direction"]
    entry = num(ev.get("entry_close"))
    for ts, bar in bars:
        if adverse_points(direction, entry, bar) <= -stop:
            return ts
    return None


def mfe_band(mfe):
    if mfe is None:
        return "UNKNOWN"
    if mfe < 20:
        return "MFE_LT20"
    if mfe < 50:
        return "MFE_20_TO_LT50"
    return "MFE_GE50"


def main():
    m = load_canonical()
    events, underlying, futures, sessions, dup_conflicts, parity = canonical_events(m)

    print("B FAMILY — RISK GEOMETRY V7")
    print("=" * 118)
    print("Framework sessions :", len(sessions))
    print("Canonical B events :", len(events))
    print("Development B      :", sum(r["sample"]=="DEVELOPMENT_LATEST60" for r in events))
    print("Older B            :", sum(r["sample"]=="OLDER_120" for r in events))
    print("Latest60 parity    :", parity)
    print("Duplicate conflicts:", dup_conflicts)

    if not parity:
        raise SystemExit("ABORT: canonical latest60 parity failed.")

    OUT.mkdir(parents=True, exist_ok=True)

    event_rows = []
    milestone_rows = []
    weak_rows = []

    for ev in events:
        bars = event_bars(ev, underlying)
        mfe = num(ev.get("mfe"))
        mae = num(ev.get("mae"))
        band = mfe_band(mfe)

        event_row = {
            "sample": ev["sample"],
            "session_date": ev["session_date"],
            "direction": ev["direction"],
            "entry_timestamp": ev["entry_timestamp"],
            "origin_timestamp": ev["origin_timestamp"],
            "delay_minutes": ev["delay_minutes"],
            "entry_close": num(ev.get("entry_close")),
            "mfe": mfe,
            "mae": mae,
            "mfe_band": band,
            "structural_invalidation_timestamp": ev.get("structural_invalidation_timestamp"),
        }
        event_rows.append(event_row)

        for target in TARGETS:
            g = milestone_geometry(ev, bars, target)
            milestone_rows.append({
                **event_row,
                "target_points": target,
                **g,
            })

        if mfe is not None and mfe < WEAK_MFE_CUTOFF:
            wr = dict(event_row)
            for stop in STOPS:
                hit = first_adverse_touch(ev, bars, stop)
                wr[f"first_minus_{stop}_timestamp"] = hit
                wr[f"minutes_to_minus_{stop}"] = minutes(ev["entry_timestamp"], hit) if hit else None
                wr[f"hit_minus_{stop}"] = bool(hit)
            weak_rows.append(wr)

    # Write event CSV
    with open(EVENT_CSV, "w", newline="") as f:
        fields = list(event_rows[0].keys())
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(event_rows)

    # Write milestone CSV
    with open(MILESTONE_CSV, "w", newline="") as f:
        fields = []
        for r in milestone_rows:
            for k in r:
                if k not in fields:
                    fields.append(k)
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(milestone_rows)

    # Write weak CSV
    if weak_rows:
        with open(WEAK_CSV, "w", newline="") as f:
            fields = []
            for r in weak_rows:
                for k in r:
                    if k not in fields:
                        fields.append(k)
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(weak_rows)

    lines = []
    lines.append("B FAMILY — RISK GEOMETRY V7")
    lines.append("=" * 118)
    lines.append("Canonical detector parity: PASS")
    lines.append(f"All B events: {len(event_rows)}")
    lines.append("")

    groups = [
        ("COMBINED_45", event_rows),
        ("DEVELOPMENT_18", [r for r in event_rows if r["sample"]=="DEVELOPMENT_LATEST60"]),
        ("OLDER_27", [r for r in event_rows if r["sample"]=="OLDER_120"]),
        ("BULLISH_ALL", [r for r in event_rows if r["direction"]=="BULLISH"]),
        ("BEARISH_ALL", [r for r in event_rows if r["direction"]=="BEARISH"]),
    ]

    for name, rows in groups:
        lines.append(name)
        lines.append("-" * 118)
        lines.append(f"events={len(rows)}")
        lines.append(f"MFE: {desc(r['mfe'] for r in rows)}")
        lines.append(f"MAE: {desc(r['mae'] for r in rows)}")
        bc = Counter(r["mfe_band"] for r in rows)
        lines.append(
            "MFE bands: "
            + ", ".join(f"{k}={bc.get(k,0)}" for k in ("MFE_LT20","MFE_20_TO_LT50","MFE_GE50"))
        )
        lines.append("")

    lines.append("MILESTONE RISK GEOMETRY")
    lines.append("=" * 118)

    for sample_name, selector in (
        ("COMBINED_45", lambda r: True),
        ("DEVELOPMENT_18", lambda r: r["sample"]=="DEVELOPMENT_LATEST60"),
        ("OLDER_27", lambda r: r["sample"]=="OLDER_120"),
    ):
        lines.append(sample_name)
        lines.append("-" * 118)

        for target in TARGETS:
            rows = [
                r for r in milestone_rows
                if selector(r) and r["target_points"] == target and r["reached"]
            ]
            lines.append(
                f"+{target:>3} reached: n={len(rows):>2} | "
                f"prior MAE [{desc(r['prior_mae'] for r in rows)}] | "
                f"time-to-target [{desc(r['minutes_to_target'] for r in rows)}]"
            )
            if rows:
                stop_parts = []
                for stop in STOPS:
                    c = Counter(r[f"stop_{stop}_status"] for r in rows)
                    stop_parts.append(
                        f"SL{stop}: survive={c.get('TARGET_REACHED_WITHOUT_PRIOR_STOP',0)} "
                        f"priorStop={c.get('STOP_BREACHED_BEFORE_TARGET',0)} "
                        f"amb={c.get('SAME_BAR_AMBIGUOUS',0)}"
                    )
                lines.append("    " + " | ".join(stop_parts))
        lines.append("")

    lines.append("WEAK B EVENTS — MFE < 20")
    lines.append("=" * 118)

    for sample_name, selector in (
        ("COMBINED", lambda r: True),
        ("DEVELOPMENT", lambda r: r["sample"]=="DEVELOPMENT_LATEST60"),
        ("OLDER", lambda r: r["sample"]=="OLDER_120"),
    ):
        rows = [r for r in weak_rows if selector(r)]
        lines.append(f"{sample_name}: weak events={len(rows)}")
        for stop in STOPS:
            hit = [r for r in rows if r[f"hit_minus_{stop}"]]
            times = [r[f"minutes_to_minus_{stop}"] for r in hit]
            lines.append(
                f"  -{stop:>2}: hit={len(hit)}/{len(rows)} "
                f"medianTime={median(times) if times else None}m "
                f"p25={percentile(times,.25) if times else None} "
                f"p75={percentile(times,.75) if times else None}"
            )
        lines.append("")

    lines.append("EVENT DETAIL")
    lines.append("=" * 118)
    for r in event_rows:
        lines.append(
            f"{r['sample']} {r['session_date']} {r['direction']} "
            f"entry={r['entry_timestamp'][11:16]} "
            f"MFE={r['mfe']} MAE={r['mae']} band={r['mfe_band']} "
            f"invalid={(r['structural_invalidation_timestamp'][11:16] if r['structural_invalidation_timestamp'] else '-')}"
        )

    lines.append("")
    lines.append("IMPORTANT")
    lines.append("- V7 does not choose a stop.")
    lines.append("- Same-candle target/stop order is unknown in 1m OHLC and is marked ambiguous.")
    lines.append("- 'Prior MAE' uses only candles strictly before first target-touch candle.")
    lines.append("- MFE bands are descriptive reporting buckets, not strategy rules.")
    lines.append("- Underlying NIFTY points are not CE/PE option-premium P&L.")
    lines.append("- Any candidate risk rule must survive development and older samples separately before option replay.")

    summary = "\n".join(lines)
    SUMMARY_TXT.write_text(summary)

    print()
    print(summary)
    print()
    print("EVENT CSV    :", EVENT_CSV)
    print("MILESTONE CSV:", MILESTONE_CSV)
    print("WEAK CSV     :", WEAK_CSV)
    print("SUMMARY      :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
