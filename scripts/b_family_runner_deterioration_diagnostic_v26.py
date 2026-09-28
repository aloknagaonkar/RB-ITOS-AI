#!/usr/bin/env python3
"""
B FAMILY — V26 RUNNER DETERIORATION DIAGNOSTIC

Purpose
-------
Descriptive candle-by-candle study of the 11 frozen RUNNER_STRENGTHENING events.

Question:
Before a runner gives back a large part of its move, do price deterioration
and directional futures-VWAP deterioration appear early enough to be useful?

This script does NOT define an exit rule.
It does NOT optimize thresholds.
It does NOT change Family-B or V20 classification.

For every minute from classification until canonical structural invalidation,
report:
- directional close move from entry
- directional favorable move from entry
- running MFE
- drawdown from running MFE using close
- directional futures-VWAP diff
- VWAP change vs classification
- VWAP change vs prior minute
- milestone state (+50/+75/+100)

It also records descriptive "deterioration coincidence" timestamps:
- first minute drawdown_from_peak_close > 0 AND vwap_change_vs_prior < 0
- first minute drawdown_from_peak_close >= 10 AND vwap_change_vs_prior < 0
- first minute drawdown_from_peak_close >= 20 AND vwap_change_vs_prior < 0

These are diagnostics ONLY, not candidate exit thresholds.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

RUNNERS = (
    RESEARCH / "b-family-runner-exit-diagnostic-v25"
    / "runner-strengthening-events-v25.csv"
)

UNDERLYING_FILES = [
    ROOT / "b-v23-pre-v22-100-underlying.csv",
    ROOT / "b-v22-untouched-100-underlying.csv",
]
FUTURES_FILES = [
    ROOT / "b-v23-pre-v22-100-futures-vwap.csv",
    ROOT / "b-v22-untouched-100-futures-vwap.csv",
]

OUTDIR = RESEARCH / "b-family-runner-deterioration-diagnostic-v26"
TIMELINE_CSV = OUTDIR / "runner-minute-timeline-v26.csv"
EVENT_CSV = OUTDIR / "runner-event-deterioration-v26.csv"
REPORT_JSON = OUTDIR / "report-v26.json"
SUMMARY_TXT = OUTDIR / "summary-v26.txt"

MILESTONES = (50, 75, 100)


def parse_dt(s):
    return datetime.fromisoformat(s)


def mins(a, b):
    return (parse_dt(b) - parse_dt(a)).total_seconds() / 60.0


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def directional_vwap(direction, close, vwap):
    raw = close - vwap
    return raw if direction == "BULLISH" else -raw


def load_underlying():
    by = defaultdict(dict)
    for path in UNDERLYING_FILES:
        if not path.exists():
            raise SystemExit(f"STOP: missing underlying file: {path}")
        with path.open(newline="") as fh:
            for r in csv.DictReader(fh):
                by[r["session_date"]][r["timestamp"]] = {
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                }
    return dict(by)


def load_futures():
    by = defaultdict(dict)
    for path in FUTURES_FILES:
        if not path.exists():
            raise SystemExit(f"STOP: missing futures file: {path}")
        with path.open(newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("session_vwap") in ("", None):
                    continue
                by[r["session_date"]][r["timestamp"]] = {
                    "close": float(r["close"]),
                    "vwap": float(r["session_vwap"]),
                }
    return dict(by)


def load_runners():
    if not RUNNERS.exists():
        raise SystemExit(f"STOP: missing V25 runner input: {RUNNERS}")
    with RUNNERS.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    if len(rows) != 11:
        raise SystemExit(f"STOP: expected 11 V25 runner rows, got {len(rows)}")
    return rows


def favorable_price(direction, bar):
    return bar["high"] if direction == "BULLISH" else bar["low"]


def milestone_state(running_mfe):
    reached = [m for m in MILESTONES if running_mfe >= m]
    return max(reached) if reached else 20


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fields = []
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def stats(vals):
    xs = [float(x) for x in vals if x not in (None, "")]
    if not xs:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "n": len(xs),
        "mean": mean(xs),
        "median": median(xs),
        "min": min(xs),
        "max": max(xs),
    }


def fmt(x):
    return "-" if x is None else f"{float(x):+.2f}"


def first_match(rows, pred):
    for row in rows:
        if pred(row):
            return row
    return None


def event_timeline(ev, u, fut):
    d = ev["session_date"]
    direction = ev["direction"]
    entry = float(ev["entry_close"])
    class_ts = ev["classification_timestamp"]
    invalid_ts = ev.get("structural_invalidation_timestamp") or None

    class_f = fut.get(class_ts)
    class_dvwap = None
    if class_f:
        class_dvwap = directional_vwap(
            direction,
            class_f["close"],
            class_f["vwap"],
        )

    rows = []
    running_mfe = None
    prev_dvwap = None

    for ts in sorted(u):
        if ts < class_ts:
            continue
        if invalid_ts and ts >= invalid_ts:
            break

        bar = u[ts]
        close_move = directional(direction, entry, bar["close"])
        favorable_move = directional(
            direction,
            entry,
            favorable_price(direction, bar),
        )

        running_mfe = (
            favorable_move
            if running_mfe is None
            else max(running_mfe, favorable_move)
        )
        drawdown = running_mfe - close_move

        f = fut.get(ts)
        dvwap = None
        if f:
            dvwap = directional_vwap(direction, f["close"], f["vwap"])

        change_class = (
            dvwap - class_dvwap
            if dvwap is not None and class_dvwap is not None
            else None
        )
        change_prev = (
            dvwap - prev_dvwap
            if dvwap is not None and prev_dvwap is not None
            else None
        )

        rows.append({
            "validation_block": ev.get("validation_block"),
            "session_date": d,
            "direction": direction,
            "entry_timestamp": ev["entry_timestamp"],
            "classification_timestamp": class_ts,
            "structural_invalidation_timestamp": invalid_ts,
            "timestamp": ts,
            "minutes_since_classification": mins(class_ts, ts),
            "directional_close_move": close_move,
            "directional_favorable_move": favorable_move,
            "running_mfe": running_mfe,
            "drawdown_from_running_mfe_close": drawdown,
            "directional_futures_vwap_diff": dvwap,
            "vwap_change_vs_classification": change_class,
            "vwap_change_vs_prior_minute": change_prev,
            "milestone_state": milestone_state(running_mfe),
        })

        if dvwap is not None:
            prev_dvwap = dvwap

    return rows


def main():
    print("B FAMILY — V26 RUNNER DETERIORATION DIAGNOSTIC")
    print("=" * 118)

    runners = load_runners()
    underlying = load_underlying()
    futures = load_futures()

    all_timeline = []
    event_rows = []

    for i, ev in enumerate(runners, 1):
        d = ev["session_date"]
        if d not in underlying or d not in futures:
            raise SystemExit(f"STOP: missing raw data for {d}")

        rows = event_timeline(ev, underlying[d], futures[d])
        all_timeline.extend(rows)

        any_det = first_match(
            rows,
            lambda r: (
                r["drawdown_from_running_mfe_close"] > 0
                and r["vwap_change_vs_prior_minute"] is not None
                and r["vwap_change_vs_prior_minute"] < 0
            ),
        )
        dd10 = first_match(
            rows,
            lambda r: (
                r["drawdown_from_running_mfe_close"] >= 10
                and r["vwap_change_vs_prior_minute"] is not None
                and r["vwap_change_vs_prior_minute"] < 0
            ),
        )
        dd20 = first_match(
            rows,
            lambda r: (
                r["drawdown_from_running_mfe_close"] >= 20
                and r["vwap_change_vs_prior_minute"] is not None
                and r["vwap_change_vs_prior_minute"] < 0
            ),
        )

        peak = max((r["running_mfe"] for r in rows), default=None)
        last = rows[-1] if rows else None

        def ts_of(x):
            return x["timestamp"] if x else None

        def mins_of(x):
            return x["minutes_since_classification"] if x else None

        row = {
            "validation_block": ev.get("validation_block"),
            "session_date": d,
            "direction": ev["direction"],
            "classification_timestamp": ev["classification_timestamp"],
            "structural_invalidation_timestamp": ev.get(
                "structural_invalidation_timestamp"
            ),
            "timeline_minutes": len(rows),
            "peak_running_mfe": peak,
            "last_directional_close_move": (
                last["directional_close_move"] if last else None
            ),
            "first_joint_deterioration_timestamp": ts_of(any_det),
            "first_joint_deterioration_minutes": mins_of(any_det),
            "first_joint_dd10_timestamp": ts_of(dd10),
            "first_joint_dd10_minutes": mins_of(dd10),
            "first_joint_dd20_timestamp": ts_of(dd20),
            "first_joint_dd20_minutes": mins_of(dd20),
        }
        event_rows.append(row)

        print(
            f"{i:2d}/11 {d} {ev['direction']} "
            f"peak={fmt(peak)} "
            f"joint_any={str(ts_of(any_det))[11:16] if any_det else '-'} "
            f"joint_dd10={str(ts_of(dd10))[11:16] if dd10 else '-'} "
            f"joint_dd20={str(ts_of(dd20))[11:16] if dd20 else '-'}"
        )

    lines = [
        "B FAMILY — V26 RUNNER DETERIORATION DIAGNOSTIC",
        "=" * 118,
        f"runner_events={len(event_rows)}",
        f"timeline_rows={len(all_timeline)}",
        "",
        "DESCRIPTIVE JOINT DETERIORATION TIMING",
        "-" * 118,
    ]

    for field, label in [
        ("first_joint_deterioration_minutes", "drawdown>0 + VWAP prior-minute deterioration"),
        ("first_joint_dd10_minutes", "drawdown>=10 + VWAP prior-minute deterioration"),
        ("first_joint_dd20_minutes", "drawdown>=20 + VWAP prior-minute deterioration"),
    ]:
        s = stats(r[field] for r in event_rows)
        lines.append(
            f"{label}: n={s['n']} "
            f"median={fmt(s['median'])}m "
            f"mean={fmt(s['mean'])}m "
            f"min={fmt(s['min'])}m "
            f"max={fmt(s['max'])}m"
        )

    lines += [
        "",
        "EVENT DETAILS",
        "-" * 118,
    ]

    for r in event_rows:
        lines.append(
            f"{r['session_date']} {r['direction']} "
            f"peak={fmt(r['peak_running_mfe'])} "
            f"joint_any={fmt(r['first_joint_deterioration_minutes'])}m "
            f"joint_dd10={fmt(r['first_joint_dd10_minutes'])}m "
            f"joint_dd20={fmt(r['first_joint_dd20_minutes'])}m"
        )

    lines += [
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- Descriptive candle-by-candle diagnostic only.",
        "- The 10pt/20pt drawdown labels are NOT exit thresholds.",
        "- No exit rule is selected here.",
        "- No threshold optimization is performed.",
        "- Family-B entry remains frozen.",
        "- V20 runner classifier remains frozen.",
        "- Structural invalidation remains the canonical lifecycle boundary.",
        "- Results use underlying NIFTY points, not option-premium P&L.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_RUNNER_DETERIORATION_DIAGNOSTIC_V26",
        "runner_event_count": len(event_rows),
        "timeline_row_count": len(all_timeline),
        "events": event_rows,
        "guards": {
            "exit_rule_defined": False,
            "threshold_search": False,
            "family_b_changed": False,
            "v20_classifier_changed": False,
            "production_code_changed": False,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(TIMELINE_CSV, all_timeline)
    write_csv(EVENT_CSV, event_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("TIMELINE CSV :", TIMELINE_CSV)
    print("EVENT CSV    :", EVENT_CSV)
    print("REPORT JSON  :", REPORT_JSON)
    print("SUMMARY      :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
