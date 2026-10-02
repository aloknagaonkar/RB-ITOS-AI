#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

CLASSIFIED = RESEARCH / "b-family-combined-200-v24" / "combined-classified-v24.csv"
UNDERLYING_FILES = [
    ROOT / "b-v23-pre-v22-100-underlying.csv",
    ROOT / "b-v22-untouched-100-underlying.csv",
]
FUTURES_FILES = [
    ROOT / "b-v23-pre-v22-100-futures-vwap.csv",
    ROOT / "b-v22-untouched-100-futures-vwap.csv",
]

OUTDIR = RESEARCH / "b-family-runner-exit-diagnostic-v25"
EVENTS_OUT = OUTDIR / "runner-strengthening-events-v25.csv"
SUMMARY_JSON = OUTDIR / "report-v25.json"
SUMMARY_TXT = OUTDIR / "summary-v25.txt"

TARGET_LABEL = "RUNNER_STRENGTHENING"
MILESTONES = (50, 75, 100)


def parse_dt(s):
    return datetime.fromisoformat(s)


def mins(a, b):
    return (parse_dt(b) - parse_dt(a)).total_seconds() / 60.0


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def directional_vwap(direction, close, vwap):
    d = close - vwap
    return d if direction == "BULLISH" else -d


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


def load_runner_events():
    if not CLASSIFIED.exists():
        raise SystemExit(f"STOP: missing classified input: {CLASSIFIED}")
    with CLASSIFIED.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if r.get("classification") == TARGET_LABEL]


def favorable_highlow(direction, bar):
    return bar["high"] if direction == "BULLISH" else bar["low"]


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
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def analyze_event(ev, u, fut):
    direction = ev["direction"]
    entry_ts = ev["entry_timestamp"]
    class_ts = ev["observation_end_timestamp"]
    invalid_ts = ev.get("structural_invalidation_timestamp") or None
    entry = float(ev["entry_close"])

    timeline = []
    for ts in sorted(u):
        if ts < class_ts:
            continue
        if invalid_ts and ts >= invalid_ts:
            break

        bar = u[ts]
        fav_px = favorable_highlow(direction, bar)
        fav = directional(direction, entry, fav_px)
        close_move = directional(direction, entry, bar["close"])

        f = fut.get(ts)
        dv = None
        if f:
            dv = directional_vwap(direction, f["close"], f["vwap"])

        timeline.append((ts, fav, close_move, dv))

    running_peak = None
    max_pullback = 0.0
    milestones = {m: None for m in MILESTONES}
    milestone_pullback = {m: None for m in MILESTONES}
    milestone_vwap = {m: None for m in MILESTONES}

    for ts, fav, close_move, dv in timeline:
        running_peak = fav if running_peak is None else max(running_peak, fav)
        pullback = max(0.0, running_peak - close_move)
        max_pullback = max(max_pullback, pullback)

        for m in MILESTONES:
            if milestones[m] is None and fav >= m:
                milestones[m] = ts
                milestone_pullback[m] = max_pullback
                milestone_vwap[m] = dv

    peak_fav = max((x[1] for x in timeline), default=None)

    class_close_move = None
    if class_ts in u:
        class_close_move = directional(direction, entry, u[class_ts]["close"])

    class_vwap = None
    if class_ts in fut:
        f = fut[class_ts]
        class_vwap = directional_vwap(direction, f["close"], f["vwap"])

    invalid_close_move = None
    invalid_vwap = None
    if invalid_ts and invalid_ts in u:
        invalid_close_move = directional(direction, entry, u[invalid_ts]["close"])
    if invalid_ts and invalid_ts in fut:
        f = fut[invalid_ts]
        invalid_vwap = directional_vwap(direction, f["close"], f["vwap"])

    giveback = None
    if peak_fav is not None and invalid_close_move is not None:
        giveback = peak_fav - invalid_close_move

    out = {
        "validation_block": ev.get("validation_block"),
        "session_date": ev["session_date"],
        "direction": direction,
        "entry_timestamp": entry_ts,
        "entry_close": entry,
        "classification_timestamp": class_ts,
        "classification_close_move": class_close_move,
        "classification_directional_vwap": class_vwap,
        "structural_invalidation_timestamp": invalid_ts,
        "classification_to_invalidation_minutes": (
            mins(class_ts, invalid_ts) if invalid_ts else None
        ),
        "peak_favorable_after_classification": peak_fav,
        "structural_invalidation_close_move": invalid_close_move,
        "peak_to_structural_giveback": giveback,
        "max_pullback_before_invalidation": max_pullback,
        "directional_vwap_at_invalidation": invalid_vwap,
    }

    for m in MILESTONES:
        ts = milestones[m]
        out[f"plus{m}_after_classification"] = ts is not None
        out[f"plus{m}_timestamp"] = ts
        out[f"minutes_classification_to_plus{m}"] = (
            mins(class_ts, ts) if ts else None
        )
        out[f"max_pullback_before_plus{m}"] = milestone_pullback[m]
        out[f"directional_vwap_at_plus{m}"] = milestone_vwap[m]

    return out


def main():
    print("B FAMILY — V25 RUNNER EXIT DIAGNOSTIC")
    print("=" * 118)

    runners = load_runner_events()
    underlying = load_underlying()
    futures = load_futures()

    if len(runners) != 11:
        raise SystemExit(
            f"STOP: expected 11 RUNNER_STRENGTHENING events from V24, got {len(runners)}"
        )

    rows = []
    for i, ev in enumerate(runners, 1):
        d = ev["session_date"]
        if d not in underlying or d not in futures:
            raise SystemExit(f"STOP: missing raw data for {d}")

        row = analyze_event(ev, underlying[d], futures[d])
        rows.append(row)

        print(
            f"{i:2d}/11 {d} {row['direction']} "
            f"class={str(row['classification_timestamp'])[11:16]} "
            f"peak={fmt(row['peak_favorable_after_classification'])} "
            f"+50={row['plus50_after_classification']} "
            f"+75={row['plus75_after_classification']} "
            f"+100={row['plus100_after_classification']} "
            f"giveback={fmt(row['peak_to_structural_giveback'])}"
        )

    lines = [
        "B FAMILY — V25 RUNNER EXIT DIAGNOSTIC",
        "=" * 118,
        f"runner_strengthening_events={len(rows)}",
        "",
        "POST-CLASSIFICATION MILESTONE TIMING",
        "-" * 118,
    ]

    for m in MILESTONES:
        hit_rows = [r for r in rows if r[f"plus{m}_after_classification"]]
        timing = stats(r[f"minutes_classification_to_plus{m}"] for r in hit_rows)
        pull = stats(r[f"max_pullback_before_plus{m}"] for r in hit_rows)

        lines.append(
            f"+{m}: hits={len(hit_rows)}/{len(rows)} "
            f"time_med={fmt(timing['median'])}m "
            f"time_mean={fmt(timing['mean'])}m "
            f"pullback_med={fmt(pull['median'])} "
            f"pullback_mean={fmt(pull['mean'])}"
        )

    peak = stats(r["peak_favorable_after_classification"] for r in rows)
    giveback = stats(r["peak_to_structural_giveback"] for r in rows)
    maxpb = stats(r["max_pullback_before_invalidation"] for r in rows)
    life = stats(r["classification_to_invalidation_minutes"] for r in rows)

    lines += [
        "",
        "STRUCTURAL-LIFECYCLE GIVEBACK",
        "-" * 118,
        f"peak favorable after classification: median={fmt(peak['median'])} mean={fmt(peak['mean'])}",
        f"peak -> structural invalidation giveback: median={fmt(giveback['median'])} mean={fmt(giveback['mean'])}",
        f"max pullback before invalidation: median={fmt(maxpb['median'])} mean={fmt(maxpb['mean'])}",
        f"classification -> invalidation: median={fmt(life['median'])}m mean={fmt(life['mean'])}m",
        "",
        "EVENT DETAILS",
        "-" * 118,
    ]

    for r in rows:
        lines.append(
            f"{r['session_date']} {r['direction']} "
            f"class={str(r['classification_timestamp'])[11:16]} "
            f"peak={fmt(r['peak_favorable_after_classification'])} "
            f"+50t={fmt(r['minutes_classification_to_plus50'])}m "
            f"+75t={fmt(r['minutes_classification_to_plus75'])}m "
            f"+100t={fmt(r['minutes_classification_to_plus100'])}m "
            f"pb50={fmt(r['max_pullback_before_plus50'])} "
            f"pb75={fmt(r['max_pullback_before_plus75'])} "
            f"pb100={fmt(r['max_pullback_before_plus100'])} "
            f"giveback={fmt(r['peak_to_structural_giveback'])}"
        )

    lines += [
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- Descriptive diagnostic only.",
        "- No exit architecture is selected by this script.",
        "- No stop, trail, or VWAP threshold is optimized.",
        "- Family-B entry remains frozen.",
        "- V20 runner classifier remains frozen.",
        "- Structural invalidation remains the canonical lifecycle boundary.",
        "- Results use underlying NIFTY points, not CE/PE premium P&L.",
        "- No production/runtime/order code changed.",
    ]

    report = {
        "version": "B_FAMILY_RUNNER_EXIT_DIAGNOSTIC_V25",
        "runner_strengthening_event_count": len(rows),
        "milestones": {},
        "structural_lifecycle": {
            "peak_favorable_after_classification": peak,
            "peak_to_structural_giveback": giveback,
            "max_pullback_before_invalidation": maxpb,
            "classification_to_invalidation_minutes": life,
        },
        "events": rows,
        "guards": {
            "exit_rule_defined": False,
            "threshold_search": False,
            "family_b_changed": False,
            "v20_classifier_changed": False,
            "production_code_changed": False,
        },
    }

    for m in MILESTONES:
        hit_rows = [r for r in rows if r[f"plus{m}_after_classification"]]
        report["milestones"][str(m)] = {
            "hits": len(hit_rows),
            "total": len(rows),
            "classification_to_milestone_minutes": stats(
                r[f"minutes_classification_to_plus{m}"] for r in hit_rows
            ),
            "max_pullback_before_milestone": stats(
                r[f"max_pullback_before_plus{m}"] for r in hit_rows
            ),
        }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENTS_OUT, rows)
    SUMMARY_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("EVENT CSV   :", EVENTS_OUT)
    print("REPORT JSON :", SUMMARY_JSON)
    print("SUMMARY     :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
