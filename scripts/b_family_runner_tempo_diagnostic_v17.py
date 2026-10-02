#!/usr/bin/env python3
"""
B FAMILY — RUNNER TEMPO DIAGNOSTIC V17

Purpose
-------
Describe the timing shape of canonical Family-B big runners and test whether
"fast" versus "slow" expansion is visibly present WITHOUT creating a new
trading rule.

Scope
-----
- Canonical 180-session Family-B universe.
- Frozen Family-B detector unchanged.
- Canonical big-runner set = MFE >= +75 points.
- Expected big runners = 12.
- NO exit optimization.
- NO threshold search.
- NO production rule creation.

Method
------
For each >=75-point runner measure:
- entry -> +20
- +20 -> +30
- +20 -> +50
- +20 -> +75
- +20 -> +100
- +50 -> +75
- +75 -> +100

Also attach the already-defined V15/V16 T1/T2 outcomes.

To visualize tempo without inventing a strategy threshold, V17 uses:
1) raw ranked timings
2) distribution quartiles
3) a descriptive median split:
   FASTER_HALF / SLOWER_HALF based only on +20 -> +75 elapsed minutes.

IMPORTANT:
The median split is descriptive research only.
It is NOT a trading classifier and must not be promoted to production.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from statistics import mean, median

CANON = Path("scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py")
V8_2 = Path("scripts/b_family_risk_model_comparison_v8_2.py")
V16_TIMELINE = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "b-family-big-runner-exit-diagnostic-v16/runner-events-v16.csv"
)

OUTDIR = Path(
    "data/historical-evidence/hilega-pcr-oi-support-research-v1/"
    "b-family-runner-tempo-diagnostic-v17"
)
EVENTS_CSV = OUTDIR / "runner-tempo-events-v17.csv"
SUMMARY_CSV = OUTDIR / "runner-tempo-summary-v17.csv"
REPORT_JSON = OUTDIR / "report-v17.json"
SUMMARY_TXT = OUTDIR / "summary-v17.txt"

EXPECTED_B_TOTAL = 45
EXPECTED_RUNNERS_75 = 12
MILESTONES = (20, 30, 50, 75, 100)


def import_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_dt(ts):
    if not ts:
        return None
    from datetime import datetime
    return datetime.fromisoformat(ts)


def mins(a, b):
    if not a or not b:
        return None
    return (parse_dt(b) - parse_dt(a)).total_seconds() / 60.0


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def favorable_move(direction, entry, bar):
    px = bar["high"] if direction == "BULLISH" else bar["low"]
    return directional(direction, entry, px)


def first_milestones(ev, u):
    entry_ts = ev["entry_timestamp"]
    direction = ev["direction"]
    entry = float(ev.get("entry_close") or u[entry_ts]["close"])
    out = {x: None for x in MILESTONES}

    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if ts[:10] != ev["session_date"]:
            continue
        if ts[11:16] > "15:14":
            continue
        m = favorable_move(direction, entry, u[ts])
        for level in MILESTONES:
            if out[level] is None and m >= level:
                out[level] = ts
    return out


def quartiles(xs):
    vals = sorted(float(x) for x in xs if x is not None)
    if not vals:
        return {"n": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None, "mean": None}

    def q(p):
        return vals[round((len(vals) - 1) * p)]

    return {
        "n": len(vals),
        "min": vals[0],
        "p25": q(0.25),
        "median": median(vals),
        "p75": q(0.75),
        "max": vals[-1],
        "mean": mean(vals),
    }


def load_v16_rows():
    if not V16_TIMELINE.exists():
        return {}
    out = {}
    with V16_TIMELINE.open(newline="") as fh:
        for r in csv.DictReader(fh):
            key = (r["session_date"], r["entry_timestamp"])
            out[key] = r
    return out


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


def fmt(x):
    return "-" if x is None else f"{x:.1f}"


def agg_group(name, rows):
    def vals(key):
        return [float(r[key]) for r in rows if r.get(key) not in (None, "")]

    def avg(key):
        x = vals(key)
        return mean(x) if x else None

    return {
        "group": name,
        "n": len(rows),
        "mean_entry_to_20": avg("entry_to_20_min"),
        "mean_20_to_50": avg("plus20_to_plus50_min"),
        "mean_20_to_75": avg("plus20_to_plus75_min"),
        "mean_20_to_100": avg("plus20_to_plus100_min"),
        "mean_t1_points": avg("t1_points"),
        "mean_t2_points": avg("t2_points"),
        "mean_mfe": avg("canonical_mfe"),
        "median_t1_points": median(vals("t1_points")) if vals("t1_points") else None,
        "median_t2_points": median(vals("t2_points")) if vals("t2_points") else None,
    }


def main():
    print("B FAMILY — RUNNER TEMPO DIAGNOSTIC V17")
    print("=" * 118)

    c = import_module(CANON, "canonical_b_v17")
    r8 = import_module(V8_2, "risk_v8_2_v17")

    framework_files, framework = c.load_framework()
    underlying_files, underlying, dup_conflicts = c.load_underlying()
    futures = c.load_futures()

    events = []
    for e in framework:
        d = e["session_date"]
        b = c.family_b_for_event(e, underlying.get(d, {}), futures.get(d, {}))
        if b:
            events.append(c.measure_event(dict(b), underlying[d]))

    if len(events) != EXPECTED_B_TOTAL or dup_conflicts != 0:
        raise SystemExit(
            f"STOP: canonical parity failed events={len(events)} dup={dup_conflicts}"
        )

    runners = [e for e in events if e.get("mfe") is not None and float(e["mfe"]) >= 75.0]
    if len(runners) != EXPECTED_RUNNERS_75:
        raise SystemExit(
            f"STOP: runner parity failed runners={len(runners)} expected={EXPECTED_RUNNERS_75}"
        )

    v16 = load_v16_rows()

    rows = []
    for ev in runners:
        d = ev["session_date"]
        u = underlying[d]
        ms = first_milestones(ev, u)

        row = {
            "session_date": d,
            "direction": ev["direction"],
            "entry_timestamp": ev["entry_timestamp"],
            "origin_timestamp": ev["origin_timestamp"],
            "delay_minutes": ev["delay_minutes"],
            "canonical_mfe": ev.get("mfe"),
            "canonical_mae": ev.get("mae"),
            "plus20_timestamp": ms[20],
            "plus30_timestamp": ms[30],
            "plus50_timestamp": ms[50],
            "plus75_timestamp": ms[75],
            "plus100_timestamp": ms[100],
            "entry_to_20_min": mins(ev["entry_timestamp"], ms[20]),
            "plus20_to_plus30_min": mins(ms[20], ms[30]),
            "plus20_to_plus50_min": mins(ms[20], ms[50]),
            "plus20_to_plus75_min": mins(ms[20], ms[75]),
            "plus20_to_plus100_min": mins(ms[20], ms[100]),
            "plus50_to_plus75_min": mins(ms[50], ms[75]),
            "plus75_to_plus100_min": mins(ms[75], ms[100]),
        }

        old = v16.get((d, ev["entry_timestamp"]), {})
        row["t1_points"] = old.get("t1_points")
        row["t1_exit_timestamp"] = old.get("t1_exit_timestamp")
        row["t2_points"] = old.get("t2_points")
        row["t2_exit_timestamp"] = old.get("t2_exit_timestamp")

        rows.append(row)

    tempo_vals = sorted(
        float(r["plus20_to_plus75_min"])
        for r in rows
        if r["plus20_to_plus75_min"] is not None
    )
    tempo_median = median(tempo_vals)

    # Purely descriptive median split.
    for r in rows:
        v = r["plus20_to_plus75_min"]
        if v is None:
            r["tempo_group_descriptive"] = "UNAVAILABLE"
        elif float(v) <= tempo_median:
            r["tempo_group_descriptive"] = "FASTER_HALF"
        else:
            r["tempo_group_descriptive"] = "SLOWER_HALF"

    rows.sort(key=lambda r: (
        float("inf") if r["plus20_to_plus75_min"] is None else float(r["plus20_to_plus75_min"]),
        r["session_date"],
    ))

    metrics = {
        "entry_to_20_min": quartiles(r["entry_to_20_min"] for r in rows),
        "plus20_to_plus30_min": quartiles(r["plus20_to_plus30_min"] for r in rows),
        "plus20_to_plus50_min": quartiles(r["plus20_to_plus50_min"] for r in rows),
        "plus20_to_plus75_min": quartiles(r["plus20_to_plus75_min"] for r in rows),
        "plus20_to_plus100_min": quartiles(r["plus20_to_plus100_min"] for r in rows),
        "plus50_to_plus75_min": quartiles(r["plus50_to_plus75_min"] for r in rows),
        "plus75_to_plus100_min": quartiles(r["plus75_to_plus100_min"] for r in rows),
    }

    faster = [r for r in rows if r["tempo_group_descriptive"] == "FASTER_HALF"]
    slower = [r for r in rows if r["tempo_group_descriptive"] == "SLOWER_HALF"]

    group_rows = [
        agg_group("FASTER_HALF", faster),
        agg_group("SLOWER_HALF", slower),
    ]

    report = {
        "version": "B_FAMILY_RUNNER_TEMPO_DIAGNOSTIC_V17",
        "canonical_b_events": len(events),
        "big_runner_threshold_mfe": 75,
        "big_runner_count": len(runners),
        "no_optimization": True,
        "median_split_is_descriptive_only": True,
        "tempo_split_basis": "plus20_to_plus75_min",
        "tempo_split_median_minutes": tempo_median,
        "metric_distributions": metrics,
        "groups": group_rows,
        "events": rows,
    }

    summary = [
        "B FAMILY — RUNNER TEMPO DIAGNOSTIC V17",
        "=" * 118,
        f"Canonical B events : {len(events)}",
        f">=75 runners       : {len(runners)}",
        f"Duplicate conflicts: {dup_conflicts}",
        "",
        "NO OPTIMIZATION. NO NEW TRADING THRESHOLD.",
        "",
        "TEMPO DISTRIBUTIONS",
        "-" * 118,
    ]

    for name, q in metrics.items():
        summary.append(
            f"{name:<26} n={q['n']} "
            f"min={fmt(q['min'])} p25={fmt(q['p25'])} "
            f"median={fmt(q['median'])} p75={fmt(q['p75'])} "
            f"max={fmt(q['max'])} mean={fmt(q['mean'])}"
        )

    summary += [
        "",
        f"DESCRIPTIVE MEDIAN SPLIT: +20 -> +75 median = {tempo_median:.1f} minutes",
        "This split is for diagnosis only, NOT a trading classifier.",
        "",
        "RANKED RUNNERS BY +20 -> +75 TEMPO",
        "-" * 118,
    ]

    for r in rows:
        summary.append(
            f"{r['session_date']} {r['direction']:<7} "
            f"group={r['tempo_group_descriptive']:<11} "
            f"entry->20={fmt(r['entry_to_20_min'])}m "
            f"20->50={fmt(r['plus20_to_plus50_min'])}m "
            f"20->75={fmt(r['plus20_to_plus75_min'])}m "
            f"20->100={fmt(r['plus20_to_plus100_min'])}m "
            f"MFE={fmt(r['canonical_mfe'])} "
            f"T1={r['t1_points'] if r['t1_points'] not in (None,'') else '-'} "
            f"T2={r['t2_points'] if r['t2_points'] not in (None,'') else '-'}"
        )

    summary += [
        "",
        "DESCRIPTIVE GROUP COMPARISON",
        "-" * 118,
    ]

    for g in group_rows:
        summary.append(
            f"{g['group']:<11} n={g['n']} "
            f"mean20->50={fmt(g['mean_20_to_50'])}m "
            f"mean20->75={fmt(g['mean_20_to_75'])}m "
            f"mean20->100={fmt(g['mean_20_to_100'])}m "
            f"meanMFE={fmt(g['mean_mfe'])} "
            f"meanT1={fmt(g['mean_t1_points'])} "
            f"meanT2={fmt(g['mean_t2_points'])}"
        )

    summary += [
        "",
        "INTERPRETATION GUARDS",
        "-" * 118,
        "- A visible tempo separation is descriptive evidence only.",
        "- Do not turn the median split into a live classifier.",
        "- Do not search multiple tempo cutoffs on these same 12 runners.",
        "- Any future tempo-aware exit architecture must be defined once and then tested forward.",
        "- Same historical 180-session universe; not independent validation.",
        "- Underlying NIFTY points only, not CE/PE premium P&L.",
        "- No production/runtime/order code changed.",
    ]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENTS_CSV, rows)
    write_csv(SUMMARY_CSV, group_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(summary))

    print("\n".join(summary))
    print()
    print("EVENTS CSV :", EVENTS_CSV)
    print("GROUP CSV  :", SUMMARY_CSV)
    print("REPORT JSON:", REPORT_JSON)
    print("SUMMARY    :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
