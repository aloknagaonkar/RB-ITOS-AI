#!/usr/bin/env python3
"""
B FAMILY — V34.1 COMPLETE POINT-ACCOUNTING BASELINE

Purpose
-------
Complete the points baseline for the 18 V32 degraded-state paths using raw
underlying candles, rather than relying on incomplete structural fields in prior
event CSVs.

This script reconstructs, for every path:
- B entry directional reference
- lifecycle MFE before structural invalidation
- structural invalidation close move
- structural giveback
- V29-type degraded-trigger close move
- V29 rejected exit move (+3m checkpoint, when reconstructable)
- later-new-MFE after V29 exit
- +50/+75/+100 milestone preservation vs V29 exit

Then it produces a baseline scorecard:
- structural invalidation exit
- V29 rejected exit

Metrics:
- total directional NIFTY points
- mean / median / worst / best
- simple cumulative max drawdown of sequential event outcomes
- improvement vs structural baseline
- +50/+75/+100 runner preservation
- later-new-MFE after V29 exit

All point figures are underlying NIFTY directional points, NOT option premium
P&L and NOT rupee P&L.

No strategy logic changes.
No threshold search.
Family-B frozen.
V20 frozen.
V29 remains rejected.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
RESEARCH = ROOT / "hilega-pcr-oi-support-research-v1"

V32_PATHS = (
    RESEARCH / "b-family-degraded-state-population-v32"
    / "degraded-state-population-v32.csv"
)

# Use raw historical sidecars already present.
UNDERLYING_FILES = []
FUTURES_FILES = []

OUTDIR = RESEARCH / "b-family-points-baseline-v34_1"
EVENT_CSV = OUTDIR / "event-points-baseline-v34_1.csv"
SCORECARD_CSV = OUTDIR / "points-scorecard-v34_1.csv"
REPORT_JSON = OUTDIR / "report-v34_1.json"
SUMMARY_TXT = OUTDIR / "summary-v34_1.txt"


def load_csv(path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    if v in ("", None):
        return None
    return float(v)


def b(v):
    return str(v).strip().lower() == "true"


def parse_dt(s):
    return datetime.fromisoformat(s)


def minute_plus(ts, n):
    return (parse_dt(ts) + timedelta(minutes=n)).isoformat()


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def favorable(direction, bar):
    return bar["high"] if direction == "BULLISH" else bar["low"]


def stats(vals):
    xs = [float(x) for x in vals if x not in (None, "")]
    if not xs:
        return {
            "n": 0, "total": None, "mean": None, "median": None,
            "min": None, "max": None
        }
    return {
        "n": len(xs),
        "total": sum(xs),
        "mean": mean(xs),
        "median": median(xs),
        "min": min(xs),
        "max": max(xs),
    }


def max_drawdown(vals):
    xs = [float(x) for x in vals if x not in (None, "")]
    if not xs:
        return None
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for x in xs:
        equity += x
        peak = max(peak, equity)
        dd = equity - peak
        max_dd = min(max_dd, dd)
    return max_dd


def fmt(x):
    return "-" if x is None else f"{float(x):+.2f}"


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


def discover_raw_files():
    u = []
    fts = []

    for p in ROOT.rglob("*.csv"):
        name = p.name.lower()

        if "underlying" in name:
            try:
                rows = load_csv(p)
            except Exception:
                continue
            if rows and {"session_date","timestamp","open","high","low","close"}.issubset(rows[0].keys()):
                u.append(p)

        if "futures" in name and "vwap" in name:
            try:
                rows = load_csv(p)
            except Exception:
                continue
            if rows and {"session_date","timestamp","close","session_vwap"}.issubset(rows[0].keys()):
                fts.append(p)

    return u, fts


def load_underlying(files):
    by = defaultdict(dict)
    for path in files:
        for r in load_csv(path):
            d = r["session_date"]
            ts = r["timestamp"]
            by[d][ts] = {
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            }
    return dict(by)


def load_futures(files):
    by = defaultdict(dict)
    for path in files:
        for r in load_csv(path):
            if r.get("session_vwap") in ("", None):
                continue
            d = r["session_date"]
            ts = r["timestamp"]
            by[d][ts] = {
                "close": float(r["close"]),
                "vwap": float(r["session_vwap"]),
            }
    return dict(by)


def discover_event_rows():
    """
    Discover best matching B-event row for each path to recover exact entry and
    structural invalidation timestamp.
    """
    out = {}

    candidates = []
    for p in RESEARCH.rglob("*.csv"):
        name = p.name.lower()
        if "b-event" in name or name.startswith("b-events"):
            candidates.append(p)

    for p in candidates:
        try:
            rows = load_csv(p)
        except Exception:
            continue

        for r in rows:
            if not all(r.get(k) for k in ("session_date","direction","entry_timestamp")):
                continue

            k = (r["session_date"], r["direction"], r["entry_timestamp"])
            score = sum(
                r.get(x) not in ("", None)
                for x in (
                    "entry_close",
                    "structural_invalidation_timestamp",
                    "observation_end_timestamp",
                    "classification",
                    "plus50_timestamp",
                    "plus75_timestamp",
                    "plus100_timestamp",
                )
            )

            if k not in out or score > out[k][0]:
                out[k] = (score, dict(r), str(p))

    return {k: (v[1], v[2]) for k, v in out.items()}


def reconstruct_event(path, ev, u):
    direction = path["direction"]
    entry_ts = path["entry_timestamp"]
    entry = f(ev.get("entry_close"))
    if entry is None:
        if entry_ts not in u:
            raise RuntimeError(f"Missing entry candle {path['session_date']} {entry_ts}")
        entry = u[entry_ts]["close"]

    invalid_ts = ev.get("structural_invalidation_timestamp") or None
    degraded_ts = path["degraded_timestamp"]

    # Lifecycle MFE through just before invalidation.
    lifecycle_mfe = None
    milestone_ts = {50: None, 75: None, 100: None}

    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if invalid_ts and ts >= invalid_ts:
            break

        fav = directional(direction, entry, favorable(direction, u[ts]))
        lifecycle_mfe = fav if lifecycle_mfe is None else max(lifecycle_mfe, fav)

        for m in (50, 75, 100):
            if milestone_ts[m] is None and fav >= m:
                milestone_ts[m] = ts

    structural_close = None
    if invalid_ts and invalid_ts in u:
        structural_close = directional(direction, entry, u[invalid_ts]["close"])

    structural_giveback = (
        None if lifecycle_mfe is None or structural_close is None
        else lifecycle_mfe - structural_close
    )

    degraded_move = None
    if degraded_ts in u:
        degraded_move = directional(direction, entry, u[degraded_ts]["close"])

    return {
        "entry_close": entry,
        "structural_invalidation_timestamp": invalid_ts,
        "lifecycle_mfe_points": lifecycle_mfe,
        "structural_exit_points": structural_close,
        "structural_giveback_points": structural_giveback,
        "degraded_trigger_points": degraded_move,
        "plus50_timestamp": milestone_ts[50],
        "plus75_timestamp": milestone_ts[75],
        "plus100_timestamp": milestone_ts[100],
    }


def reconstruct_v29(path, ev, u, fut, rec):
    """
    Reconstruct the rejected V29 exit for point baseline.
    Uses first degraded trigger from V32 as episode start and +3m checkpoint.
    """
    degraded_ts = path["degraded_timestamp"]
    checkpoint_ts = minute_plus(degraded_ts, 3)

    direction = path["direction"]
    entry = rec["entry_close"]
    invalid_ts = rec["structural_invalidation_timestamp"]

    if invalid_ts and checkpoint_ts >= invalid_ts:
        return {
            "v29_exit_reconstructable": False,
            "v29_exit_timestamp": None,
            "v29_exit_points": None,
            "v29_later_new_mfe": None,
        }

    if checkpoint_ts not in u:
        return {
            "v29_exit_reconstructable": False,
            "v29_exit_timestamp": None,
            "v29_exit_points": None,
            "v29_later_new_mfe": None,
        }

    # Need exact frozen condition.
    start_f = fut.get(degraded_ts)
    end_f = fut.get(checkpoint_ts)
    if not start_f or not end_f:
        return {
            "v29_exit_reconstructable": False,
            "v29_exit_timestamp": None,
            "v29_exit_points": None,
            "v29_later_new_mfe": None,
        }

    start_dvwap = (
        start_f["close"] - start_f["vwap"]
        if direction == "BULLISH"
        else -(start_f["close"] - start_f["vwap"])
    )
    end_dvwap = (
        end_f["close"] - end_f["vwap"]
        if direction == "BULLISH"
        else -(end_f["close"] - end_f["vwap"])
    )

    start_move = directional(direction, entry, u[degraded_ts]["close"])
    end_move = directional(direction, entry, u[checkpoint_ts]["close"])

    trigger = (
        end_dvwap < start_dvwap
        and end_move <= start_move
    )

    if not trigger:
        return {
            "v29_exit_reconstructable": True,
            "v29_exit_timestamp": None,
            "v29_exit_points": None,
            "v29_later_new_mfe": None,
        }

    # Pre-exit MFE.
    pre_peak = None
    for ts in sorted(u):
        if ts <= path["entry_timestamp"]:
            continue
        if ts > checkpoint_ts:
            break
        if invalid_ts and ts >= invalid_ts:
            break
        fav = directional(direction, entry, favorable(direction, u[ts]))
        pre_peak = fav if pre_peak is None else max(pre_peak, fav)

    later_new = False
    if pre_peak is not None:
        for ts in sorted(u):
            if ts <= checkpoint_ts:
                continue
            if invalid_ts and ts >= invalid_ts:
                break
            fav = directional(direction, entry, favorable(direction, u[ts]))
            if fav > pre_peak + 1e-9:
                later_new = True
                break

    return {
        "v29_exit_reconstructable": True,
        "v29_exit_timestamp": checkpoint_ts,
        "v29_exit_points": end_move,
        "v29_later_new_mfe": later_new,
    }


def scorecard_row(name, vals, structural_vals=None):
    s = stats(vals)
    row = {
        "candidate": name,
        "n": s["n"],
        "total_points": s["total"],
        "mean_points": s["mean"],
        "median_points": s["median"],
        "worst_points": s["min"],
        "best_points": s["max"],
        "max_drawdown_points": max_drawdown(vals),
    }

    if structural_vals is not None:
        paired = [
            (float(v), float(sv))
            for v, sv in zip(vals, structural_vals)
            if v is not None and sv is not None
        ]
        improvements = [v - sv for v, sv in paired]
        si = stats(improvements)
        row.update({
            "paired_vs_structural_n": si["n"],
            "total_improvement_vs_structural": si["total"],
            "mean_improvement_vs_structural": si["mean"],
            "median_improvement_vs_structural": si["median"],
        })

    return row


def main():
    print("B FAMILY — V34.1 COMPLETE POINT-ACCOUNTING BASELINE")
    print("=" * 118)

    paths = load_csv(V32_PATHS)
    u_files, f_files = discover_raw_files()
    underlying = load_underlying(u_files)
    futures = load_futures(f_files)
    events = discover_event_rows()

    print(f"paths={len(paths)}")
    print(f"underlying_files={len(u_files)} futures_files={len(f_files)}")
    print(f"event_keys={len(events)}")

    event_rows = []

    for idx, path in enumerate(paths, 1):
        k = (path["session_date"], path["direction"], path["entry_timestamp"])
        pair = events.get(k)
        if not pair:
            raise SystemExit(f"STOP: missing event row for {k}")

        ev, ev_source = pair
        d = path["session_date"]

        if d not in underlying:
            raise SystemExit(f"STOP: missing underlying for {d}")
        if d not in futures:
            raise SystemExit(f"STOP: missing futures for {d}")

        rec = reconstruct_event(path, ev, underlying[d])
        v29 = reconstruct_v29(path, ev, underlying[d], futures[d], rec)

        row = {
            "session_date": d,
            "direction": path["direction"],
            "entry_timestamp": path["entry_timestamp"],
            "block": path.get("block"),
            "resolution": path["resolution"],
            "event_source": ev_source,
            **rec,
            **v29,
        }

        # milestone preservation relative to V29
        for m in (50,75,100):
            mt = row[f"plus{m}_timestamp"]
            et = row["v29_exit_timestamp"]
            row[f"v29_exit_before_plus{m}"] = bool(et and mt and et < mt)

        event_rows.append(row)

        print(
            f"{idx:2d}/{len(paths)} {d} {row['direction']} "
            f"struct={fmt(row['structural_exit_points'])} "
            f"MFE={fmt(row['lifecycle_mfe_points'])} "
            f"giveback={fmt(row['structural_giveback_points'])} "
            f"V29={fmt(row['v29_exit_points'])} "
            f"laterNewMFE={row['v29_later_new_mfe']}"
        )

    structural_vals = [r["structural_exit_points"] for r in event_rows]

    # V29 scorecard only on events where V29 actually triggers.
    v29_rows = [r for r in event_rows if r["v29_exit_points"] is not None]
    v29_vals = [r["v29_exit_points"] for r in v29_rows]
    v29_struct = [r["structural_exit_points"] for r in v29_rows]

    score_rows = [
        scorecard_row("STRUCTURAL_INVALIDATION", structural_vals),
        scorecard_row("V29_REJECTED_EXIT", v29_vals, v29_struct),
    ]

    # Preservation counts.
    preservation = {}
    for m in (50,75,100):
        runners = [r for r in v29_rows if r[f"plus{m}_timestamp"]]
        cut = [r for r in runners if r[f"v29_exit_before_plus{m}"]]
        preservation[m] = {
            "structural_reached": len(runners),
            "v29_exited_before": len(cut),
            "preserved": len(runners) - len(cut),
        }

    later_new = sum(r["v29_later_new_mfe"] is True for r in v29_rows)

    structural_stats = stats(structural_vals)
    v29_stats = stats(v29_vals)
    improvement_stats = stats(
        r["v29_exit_points"] - r["structural_exit_points"]
        for r in v29_rows
        if r["v29_exit_points"] is not None
        and r["structural_exit_points"] is not None
    )

    lines = [
        "B FAMILY — V34.1 COMPLETE POINT-ACCOUNTING BASELINE",
        "=" * 118,
        f"events={len(event_rows)}",
        f"structural_point_events={structural_stats['n']}",
        f"v29_triggered_events={v29_stats['n']}",
        "",
        "BASELINE SCORECARD — NIFTY UNDERLYING DIRECTIONAL POINTS",
        "-" * 118,
        f"STRUCTURAL: total={fmt(structural_stats['total'])} "
        f"mean={fmt(structural_stats['mean'])} "
        f"median={fmt(structural_stats['median'])} "
        f"worst={fmt(structural_stats['min'])} "
        f"best={fmt(structural_stats['max'])} "
        f"maxDD={fmt(max_drawdown(structural_vals))}",
        f"V29: total={fmt(v29_stats['total'])} "
        f"mean={fmt(v29_stats['mean'])} "
        f"median={fmt(v29_stats['median'])} "
        f"worst={fmt(v29_stats['min'])} "
        f"best={fmt(v29_stats['max'])} "
        f"maxDD={fmt(max_drawdown(v29_vals))}",
        f"V29 improvement vs structural on same events: "
        f"total={fmt(improvement_stats['total'])} "
        f"mean={fmt(improvement_stats['mean'])} "
        f"median={fmt(improvement_stats['median'])}",
        "",
        "V29 RUNNER PRESERVATION",
        "-" * 118,
    ]

    for m in (50,75,100):
        p = preservation[m]
        lines.append(
            f"+{m}: reached={p['structural_reached']} "
            f"V29 exited before={p['v29_exited_before']} "
            f"preserved={p['preserved']}/{p['structural_reached']}"
        )

    lines += [
        f"V29 exits followed by later new MFE: {later_new}/{len(v29_rows)}",
        "",
        "POINT ACCOUNTING BASELINE ESTABLISHED",
        "-" * 118,
        "- Future exit candidates must compare against STRUCTURAL_INVALIDATION.",
        "- Future exit candidates must compare against previous candidate.",
        "- Report total/mean/median/worst/best/maxDD.",
        "- Report paired improvement vs structural.",
        "- Report +50/+75/+100 preservation.",
        "- Report later-new-MFE after candidate exit.",
        "",
        "GUARDS",
        "-" * 118,
        "- Underlying NIFTY directional points only.",
        "- Not CE/PE premium P&L.",
        "- Not rupee P&L.",
        "- No threshold search.",
        "- No strategy logic changes.",
        "- V29 remains rejected.",
    ]

    report = {
        "version": "B_FAMILY_POINTS_BASELINE_V34_1",
        "events": len(event_rows),
        "scorecard": score_rows,
        "v29_preservation": preservation,
        "v29_later_new_mfe_count": later_new,
        "guards": {
            "unit": "NIFTY_UNDERLYING_DIRECTIONAL_POINTS",
            "threshold_search": False,
            "strategy_logic_changed": False,
            "v29_status": "REJECTED",
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENT_CSV, event_rows)
    write_csv(SCORECARD_CSV, score_rows)
    REPORT_JSON.write_text(json.dumps(report, indent=2))
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")

    print()
    print("\n".join(lines))
    print()
    print("EVENT CSV     :", EVENT_CSV)
    print("SCORECARD CSV :", SCORECARD_CSV)
    print("REPORT JSON   :", REPORT_JSON)
    print("SUMMARY       :", SUMMARY_TXT)


if __name__ == "__main__":
    main()
