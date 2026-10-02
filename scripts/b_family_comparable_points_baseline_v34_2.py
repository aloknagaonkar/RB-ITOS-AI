#!/usr/bin/env python3
"""
B FAMILY — V34.2 COMPARABLE 18-EVENT POINTS BASELINE

Purpose
-------
Create a fully comparable points baseline across ALL 18 degraded-state events.

This corrects V34.1's population mismatch by defining one common terminal
baseline for every event:

  STRUCTURAL_OR_SESSION_CUTOFF
  - if structural invalidation timestamp exists and is present in raw data:
      use structural invalidation close
  - otherwise:
      use the final trusted 1-minute session close available in raw data

Also reconstruct the frozen V29 candidate exactly as a multi-episode scan:
- after V20 classification
- each joint deterioration FALSE->TRUE starts a candidate episode
- evaluate exactly +3 minutes later
- if V29 condition fails, keep scanning future deterioration episodes
- first valid V29 trigger exits
- if no V29 exit occurs, fall back to STRUCTURAL_OR_SESSION_CUTOFF for
  same-population comparison

Outputs one 18-event comparable scorecard for:
- STRUCTURAL_OR_SESSION_CUTOFF
- V29_REJECTED_FULL_POLICY

Metrics:
- total directional NIFTY points
- mean / median / worst / best
- event-sequence cumulative max drawdown
- paired improvement versus baseline
- +50/+75/+100 preservation
- later-new-MFE after actual V29 exits
- actual-exit count vs fallback count

All figures are NIFTY underlying directional points.
No option premium P&L.
No rupee P&L.
No threshold search.
No candidate tuning.
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

OUTDIR = RESEARCH / "b-family-comparable-points-baseline-v34_2"
EVENT_CSV = OUTDIR / "comparable-event-points-v34_2.csv"
SCORECARD_CSV = OUTDIR / "comparable-scorecard-v34_2.csv"
REPORT_JSON = OUTDIR / "report-v34_2.json"
SUMMARY_TXT = OUTDIR / "summary-v34_2.txt"


def load_csv(path):
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def f(v):
    if v in ("", None):
        return None
    return float(v)


def parse_dt(s):
    return datetime.fromisoformat(s)


def plus_minutes(ts, n):
    return (parse_dt(ts) + timedelta(minutes=n)).isoformat()


def directional(direction, entry, price):
    return price - entry if direction == "BULLISH" else entry - price


def favorable(direction, bar):
    return bar["high"] if direction == "BULLISH" else bar["low"]


def directional_vwap(direction, row):
    if not row:
        return None
    raw = row["close"] - row["vwap"]
    return raw if direction == "BULLISH" else -raw


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
    mdd = 0.0
    for x in xs:
        equity += x
        peak = max(peak, equity)
        mdd = min(mdd, equity - peak)
    return mdd


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


def discover_raw():
    u_files = []
    f_files = []

    for p in ROOT.rglob("*.csv"):
        name = p.name.lower()

        if "underlying" in name:
            try:
                rows = load_csv(p)
            except Exception:
                continue
            if rows and {"session_date","timestamp","open","high","low","close"}.issubset(rows[0].keys()):
                u_files.append(p)

        if "futures" in name and "vwap" in name:
            try:
                rows = load_csv(p)
            except Exception:
                continue
            if rows and {"session_date","timestamp","close","session_vwap"}.issubset(rows[0].keys()):
                f_files.append(p)

    return u_files, f_files


def load_underlying(files):
    by = defaultdict(dict)
    for path in files:
        for r in load_csv(path):
            by[r["session_date"]][r["timestamp"]] = {
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
            by[r["session_date"]][r["timestamp"]] = {
                "close": float(r["close"]),
                "vwap": float(r["session_vwap"]),
            }
    return dict(by)


def discover_event_rows():
    out = {}
    for p in RESEARCH.rglob("*.csv"):
        name = p.name.lower()
        if not ("b-event" in name or name.startswith("b-events")):
            continue
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
                    "observation_end_timestamp",
                    "classification",
                    "structural_invalidation_timestamp",
                )
            )

            if k not in out or score > out[k][0]:
                out[k] = (score, dict(r), str(p))

    return {k: (v[1], v[2]) for k, v in out.items()}


def lifecycle_and_baseline(path, ev, u):
    direction = path["direction"]
    entry_ts = path["entry_timestamp"]
    entry = f(ev.get("entry_close"))
    if entry is None:
        if entry_ts not in u:
            raise RuntimeError(f"Missing entry candle {path['session_date']} {entry_ts}")
        entry = u[entry_ts]["close"]

    invalid_ts = ev.get("structural_invalidation_timestamp") or None
    trusted_ts = sorted(u)

    if not trusted_ts:
        raise RuntimeError(f"No underlying rows {path['session_date']}")

    last_ts = trusted_ts[-1]

    if invalid_ts and invalid_ts in u:
        terminal_ts = invalid_ts
        terminal_type = "STRUCTURAL_INVALIDATION"
    else:
        terminal_ts = last_ts
        terminal_type = "SESSION_CUTOFF"

    lifecycle_mfe = None
    milestones = {50: None, 75: None, 100: None}

    for ts in trusted_ts:
        if ts <= entry_ts:
            continue
        if ts >= terminal_ts:
            break

        fav = directional(direction, entry, favorable(direction, u[ts]))
        lifecycle_mfe = fav if lifecycle_mfe is None else max(lifecycle_mfe, fav)

        for m in milestones:
            if milestones[m] is None and fav >= m:
                milestones[m] = ts

    terminal_points = directional(
        direction,
        entry,
        u[terminal_ts]["close"],
    )

    giveback = (
        None if lifecycle_mfe is None
        else lifecycle_mfe - terminal_points
    )

    return {
        "entry_close": entry,
        "terminal_timestamp": terminal_ts,
        "terminal_type": terminal_type,
        "baseline_points": terminal_points,
        "lifecycle_mfe_points": lifecycle_mfe,
        "baseline_giveback_points": giveback,
        "plus50_timestamp": milestones[50],
        "plus75_timestamp": milestones[75],
        "plus100_timestamp": milestones[100],
    }


def exact_v29_scan(path, ev, u, fut, base):
    """
    Exact frozen V29 multi-episode scan.

    Start at V20 classification timestamp.
    Joint deterioration:
      drawdown_from_running_MFE_close > 0
      AND prior-minute directional futures-VWAP change < 0
    On FALSE->TRUE transition, evaluate exactly +3m.
    Exit if:
      directional VWAP change from episode start < 0
      AND directional close move change from episode start <= 0
    Otherwise continue scanning future episodes.
    """
    direction = path["direction"]
    entry_ts = path["entry_timestamp"]
    entry = base["entry_close"]
    terminal_ts = base["terminal_timestamp"]

    class_ts = ev.get("observation_end_timestamp")
    if not class_ts:
        raise RuntimeError(f"Missing V20 classification timestamp {path['session_date']}")

    timestamps = [
        ts for ts in sorted(u)
        if ts >= class_ts and ts < terminal_ts
    ]

    # Seed running MFE from entry through classification.
    running_mfe = None
    prev_dvwap = None
    for ts in sorted(u):
        if ts <= entry_ts:
            continue
        if ts > class_ts:
            break
        if ts >= terminal_ts:
            break

        fav = directional(direction, entry, favorable(direction, u[ts]))
        running_mfe = fav if running_mfe is None else max(running_mfe, fav)

        dv = directional_vwap(direction, fut.get(ts))
        if dv is not None:
            prev_dvwap = dv

    prior_joint = False
    episode_count = 0

    for ts in timestamps:
        bar = u[ts]
        fav = directional(direction, entry, favorable(direction, bar))
        running_mfe = fav if running_mfe is None else max(running_mfe, fav)

        close_move = directional(direction, entry, bar["close"])
        dd = running_mfe - close_move

        dvwap = directional_vwap(direction, fut.get(ts))
        vwap_change_prior = (
            None if dvwap is None or prev_dvwap is None
            else dvwap - prev_dvwap
        )

        joint = (
            dd > 0
            and vwap_change_prior is not None
            and vwap_change_prior < 0
        )

        if joint and not prior_joint:
            episode_count += 1
            cp_ts = plus_minutes(ts, 3)

            if cp_ts < terminal_ts and cp_ts in u and cp_ts in fut:
                cp_dvwap = directional_vwap(direction, fut.get(cp_ts))
                cp_move = directional(direction, entry, u[cp_ts]["close"])

                if (
                    dvwap is not None and cp_dvwap is not None
                    and cp_dvwap < dvwap
                    and cp_move <= close_move
                ):
                    # later new MFE after actual V29 exit
                    pre_peak = running_mfe
                    later_new = False

                    for later in sorted(u):
                        if later <= cp_ts:
                            continue
                        if later >= terminal_ts:
                            break

                        lf = directional(
                            direction,
                            entry,
                            favorable(direction, u[later]),
                        )
                        if pre_peak is not None and lf > pre_peak + 1e-9:
                            later_new = True
                            break

                    return {
                        "v29_actual_exit": True,
                        "v29_exit_timestamp": cp_ts,
                        "v29_points": cp_move,
                        "v29_episode_count_evaluated": episode_count,
                        "v29_later_new_mfe": later_new,
                    }

        prior_joint = joint
        if dvwap is not None:
            prev_dvwap = dvwap

    # Same-population full-policy fallback.
    return {
        "v29_actual_exit": False,
        "v29_exit_timestamp": None,
        "v29_points": base["baseline_points"],
        "v29_episode_count_evaluated": episode_count,
        "v29_later_new_mfe": None,
    }


def score_row(name, vals, baseline_vals=None):
    s = stats(vals)
    row = {
        "policy": name,
        "n": s["n"],
        "total_points": s["total"],
        "mean_points": s["mean"],
        "median_points": s["median"],
        "worst_points": s["min"],
        "best_points": s["max"],
        "max_drawdown_points": max_drawdown(vals),
    }

    if baseline_vals is not None:
        diffs = [
            float(v) - float(b)
            for v, b in zip(vals, baseline_vals)
            if v is not None and b is not None
        ]
        d = stats(diffs)
        row.update({
            "paired_n": d["n"],
            "total_improvement_vs_baseline": d["total"],
            "mean_improvement_vs_baseline": d["mean"],
            "median_improvement_vs_baseline": d["median"],
            "worst_improvement_vs_baseline": d["min"],
            "best_improvement_vs_baseline": d["max"],
        })

    return row


def main():
    print("B FAMILY — V34.2 COMPARABLE 18-EVENT POINTS BASELINE")
    print("=" * 118)

    paths = load_csv(V32_PATHS)
    if len(paths) != 18:
        raise SystemExit(f"STOP: expected 18 V32 paths, got {len(paths)}")

    u_files, f_files = discover_raw()
    underlying = load_underlying(u_files)
    futures = load_futures(f_files)
    events = discover_event_rows()

    event_rows = []

    for idx, path in enumerate(paths, 1):
        k = (path["session_date"], path["direction"], path["entry_timestamp"])
        pair = events.get(k)
        if not pair:
            raise SystemExit(f"STOP: missing event source for {k}")

        ev, ev_source = pair
        d = path["session_date"]

        if d not in underlying:
            raise SystemExit(f"STOP: missing underlying {d}")
        if d not in futures:
            raise SystemExit(f"STOP: missing futures {d}")

        base = lifecycle_and_baseline(path, ev, underlying[d])
        v29 = exact_v29_scan(path, ev, underlying[d], futures[d], base)

        row = {
            "session_date": d,
            "direction": path["direction"],
            "entry_timestamp": path["entry_timestamp"],
            "block": path.get("block"),
            "resolution": path["resolution"],
            "event_source": ev_source,
            **base,
            **v29,
        }

        for m in (50, 75, 100):
            mt = row[f"plus{m}_timestamp"]
            et = row["v29_exit_timestamp"]
            row[f"v29_exit_before_plus{m}"] = bool(et and mt and et < mt)

        row["v29_improvement_vs_baseline_points"] = (
            row["v29_points"] - row["baseline_points"]
        )

        event_rows.append(row)

        print(
            f"{idx:2d}/18 {d} {row['direction']} "
            f"baseline={fmt(row['baseline_points'])} "
            f"({row['terminal_type']}) "
            f"V29={fmt(row['v29_points'])} "
            f"actualExit={row['v29_actual_exit']} "
            f"delta={fmt(row['v29_improvement_vs_baseline_points'])}"
        )

    baseline_vals = [r["baseline_points"] for r in event_rows]
    v29_vals = [r["v29_points"] for r in event_rows]

    baseline_score = score_row("STRUCTURAL_OR_SESSION_CUTOFF", baseline_vals)
    v29_score = score_row("V29_REJECTED_FULL_POLICY", v29_vals, baseline_vals)

    actual_v29 = [r for r in event_rows if r["v29_actual_exit"]]
    fallback_v29 = [r for r in event_rows if not r["v29_actual_exit"]]

    preservation = {}
    for m in (50, 75, 100):
        runners = [r for r in actual_v29 if r[f"plus{m}_timestamp"]]
        cut = [r for r in runners if r[f"v29_exit_before_plus{m}"]]
        preservation[m] = {
            "reached": len(runners),
            "cut_before": len(cut),
            "preserved": len(runners) - len(cut),
        }

    later_new = sum(r["v29_later_new_mfe"] is True for r in actual_v29)

    bstats = stats(baseline_vals)
    vstats = stats(v29_vals)
    diffs = [v - b for v, b in zip(v29_vals, baseline_vals)]
    dstats = stats(diffs)

    lines = [
        "B FAMILY — V34.2 COMPARABLE 18-EVENT POINTS BASELINE",
        "=" * 118,
        f"events={len(event_rows)}",
        f"baseline_events={len(baseline_vals)}",
        f"v29_policy_events={len(v29_vals)}",
        f"v29_actual_exits={len(actual_v29)}",
        f"v29_fallback_to_baseline={len(fallback_v29)}",
        "",
        "FULL 18-EVENT SCORECARD — NIFTY UNDERLYING DIRECTIONAL POINTS",
        "-" * 118,
        f"BASELINE total={fmt(bstats['total'])} mean={fmt(bstats['mean'])} "
        f"median={fmt(bstats['median'])} worst={fmt(bstats['min'])} "
        f"best={fmt(bstats['max'])} maxDD={fmt(max_drawdown(baseline_vals))}",
        f"V29      total={fmt(vstats['total'])} mean={fmt(vstats['mean'])} "
        f"median={fmt(vstats['median'])} worst={fmt(vstats['min'])} "
        f"best={fmt(vstats['max'])} maxDD={fmt(max_drawdown(v29_vals))}",
        f"V29 Δ vs baseline: total={fmt(dstats['total'])} "
        f"mean={fmt(dstats['mean'])} median={fmt(dstats['median'])} "
        f"worstΔ={fmt(dstats['min'])} bestΔ={fmt(dstats['max'])}",
        "",
        "V29 ACTUAL-EXIT RUNNER PRESERVATION",
        "-" * 118,
    ]

    for m in (50,75,100):
        p = preservation[m]
        lines.append(
            f"+{m}: reached={p['reached']} cutBefore={p['cut_before']} "
            f"preserved={p['preserved']}/{p['reached']}"
        )

    lines += [
        f"actual V29 exits followed by later new MFE: "
        f"{later_new}/{len(actual_v29)}",
        "",
        "INTERPRETATION",
        "-" * 118,
        "- This is now the common 18-event points baseline.",
        "- V29 full policy is evaluated on the SAME 18-event population.",
        "- No candidate tuning occurred in this script.",
        "- Future exit candidates must beat this baseline on points AND improve runner preservation.",
        "",
        "GUARDS",
        "-" * 118,
        "- Underlying NIFTY directional points only.",
        "- Not CE/PE premium P&L.",
        "- Not rupee P&L.",
        "- Family-B unchanged.",
        "- V20 unchanged.",
        "- V29 remains rejected.",
    ]

    report = {
        "version": "B_FAMILY_COMPARABLE_POINTS_BASELINE_V34_2",
        "events": len(event_rows),
        "scorecard": [baseline_score, v29_score],
        "v29_actual_exit_count": len(actual_v29),
        "v29_fallback_count": len(fallback_v29),
        "v29_preservation": preservation,
        "v29_later_new_mfe_count": later_new,
        "guards": {
            "same_population": True,
            "unit": "NIFTY_UNDERLYING_DIRECTIONAL_POINTS",
            "threshold_search": False,
            "candidate_tuning": False,
        },
    }

    OUTDIR.mkdir(parents=True, exist_ok=True)
    write_csv(EVENT_CSV, event_rows)
    write_csv(SCORECARD_CSV, [baseline_score, v29_score])
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
