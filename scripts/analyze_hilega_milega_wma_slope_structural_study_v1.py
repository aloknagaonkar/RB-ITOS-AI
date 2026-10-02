#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median

from analyze_hilega_milega_bullish_expansion_multisession_v1 import (
    fetch_1m,
    to5,
    rsi_wilder,
    ema,
    wma,
    replay_trades,
)

def slope_bucket(v: float) -> str:
    if v < 0:
        return "<0"
    if v == 0:
        return "=0"
    if v < 0.25:
        return "0-0.25"
    if v < 0.5:
        return "0.25-0.5"
    if v < 1.0:
        return "0.5-1"
    if v < 2.0:
        return "1-2"
    return ">=2"

def stats(rows):
    if not rows:
        return {
            "trades": 0, "positive": 0, "negative": 0, "flat": 0,
            "positive_rate_pct": None, "net_points": 0.0,
            "avg_points": None, "median_points": None,
            "best_points": None, "worst_points": None,
        }
    pts = [float(x["points"]) for x in rows]
    pos = sum(1 for x in rows if x["outcome"] == "POSITIVE")
    neg = sum(1 for x in rows if x["outcome"] == "NEGATIVE")
    flat = sum(1 for x in rows if x["outcome"] == "FLAT")
    return {
        "trades": len(rows),
        "positive": pos,
        "negative": neg,
        "flat": flat,
        "positive_rate_pct": 100.0 * pos / len(rows),
        "net_points": sum(pts),
        "avg_points": sum(pts) / len(pts),
        "median_points": median(pts),
        "best_points": max(pts),
        "worst_points": min(pts),
    }

def print_stats(label, rows):
    s = stats(rows)
    if s["trades"] == 0:
        print(f"{label:48} trades=0")
        return
    print(
        f"{label:48} "
        f"n={s['trades']:4d} "
        f"pos={s['positive']:4d} neg={s['negative']:4d} "
        f"win={s['positive_rate_pct']:6.2f}% "
        f"net={s['net_points']:9.2f} "
        f"avg={s['avg_points']:7.2f} "
        f"med={s['median_points']:7.2f}"
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--last-n-sessions", type=int, default=120)
    ap.add_argument("--warmup-calendar-days", type=int, default=45)
    ap.add_argument("--token-env", default="UPSTOX_ACCESS_TOKEN")
    ap.add_argument(
        "--output-dir",
        default="data/historical-evidence/hilega-milega-wma-slope-structural-study-v1",
    )
    args = ap.parse_args()

    token = os.getenv(args.token_env)
    if not token:
        raise SystemExit(f"Missing {args.token_env}; load .env first")

    first_req = date.fromisoformat(args.from_date)
    last_req = date.fromisoformat(args.to_date)
    if last_req < first_req:
        raise SystemExit("--to-date must be >= --from-date")

    start = first_req - timedelta(days=args.warmup_calendar_days)
    raw = {}
    d = start
    while d <= last_req:
        try:
            bars = fetch_1m(token, d)
            print(f"fetch {d}: candles={len(bars)}")
            if bars:
                raw[d] = bars
        except Exception as e:
            print(f"fetch {d}: ERROR {e}")
        d += timedelta(days=1)

    target_dates = sorted(d for d in raw if first_req <= d <= last_req)
    if not target_dates:
        raise SystemExit("No trading sessions with data in requested range.")
    if args.last_n_sessions:
        target_dates = target_dates[-args.last_n_sessions:]

    first = min(target_dates)
    prior_sessions = sorted(d for d in raw if d < first)[-10:]
    calc_dates = prior_sessions + target_dates

    all5 = []
    for sd in calc_dates:
        all5.extend(to5(raw[sd]))
    all5.sort(key=lambda b: b.ts)

    rs = rsi_wilder([b.close for b in all5], 9)
    es = ema(rs, 3)
    ws = wma(rs, 21)
    for b, rv, ev, wv in zip(all5, rs, es, ws):
        b.rsi, b.ema, b.wma = rv, ev, wv

    by_day = defaultdict(list)
    for b in all5:
        by_day[b.ts.date()].append(b)

    trades = []
    for sd in target_dates:
        trades.extend(replay_trades(by_day[sd], sd))

    completed = [x for x in trades if x["outcome"] in {"POSITIVE", "NEGATIVE", "FLAT"}]

    # replay_trades already stores wma_delta_1/2/3 from entry_metrics.
    # Here we explicitly interpret those as WMA slope over 1,2,3 bars.
    print(f"\nTarget sessions: {len(target_dates)}")
    print(f"Completed trades: {len(completed)}")
    print_stats("BASELINE", completed)

    print("\n=== WMA21 SLOPE ONLY ===")
    for key, label in [
        ("wma_delta_1", "WMA slope 1-bar > 0"),
        ("wma_delta_2", "WMA slope 2-bar > 0"),
        ("wma_delta_3", "WMA slope 3-bar > 0"),
    ]:
        print_stats(label, [x for x in completed if x.get(key) is not None and x[key] > 0])

    print("\n=== WMA21 SLOPE BUCKETS (1-BAR) ===")
    groups = defaultdict(list)
    for x in completed:
        v = x.get("wma_delta_1")
        if v is not None:
            groups[slope_bucket(float(v))].append(x)
    for b in ["<0", "=0", "0-0.25", "0.25-0.5", "0.5-1", "1-2", ">=2"]:
        print_stats(f"WMA1 {b}", groups.get(b, []))

    print("\n=== FULL STACK + WMA SLOPE ===")
    full = [x for x in completed if x.get("full_stack")]
    print_stats("FULL STACK baseline", full)
    print_stats("FULL STACK + WMA1 > 0", [x for x in full if x.get("wma_delta_1") is not None and x["wma_delta_1"] > 0])
    print_stats("FULL STACK + WMA2 > 0", [x for x in full if x.get("wma_delta_2") is not None and x["wma_delta_2"] > 0])
    print_stats("FULL STACK + WMA3 > 0", [x for x in full if x.get("wma_delta_3") is not None and x["wma_delta_3"] > 0])

    print("\n=== STRUCTURAL GAP + WMA SLOPE COMBINATIONS ===")
    ema_thresholds = [2, 3, 4, 5]
    rsi_thresholds = [5, 8, 10, 12, 15]
    slope_keys = [
        ("NONE", None),
        ("WMA1>0", "wma_delta_1"),
        ("WMA2>0", "wma_delta_2"),
        ("WMA3>0", "wma_delta_3"),
    ]

    rows = []
    for ema_min in ema_thresholds:
        for rsi_min in rsi_thresholds:
            base = [
                x for x in completed
                if x.get("full_stack")
                and x.get("ema_wma_gap") is not None
                and x.get("rsi_wma_gap") is not None
                and x["ema_wma_gap"] >= ema_min
                and x["rsi_wma_gap"] >= rsi_min
            ]
            for slope_name, slope_key in slope_keys:
                xs = base if slope_key is None else [
                    x for x in base
                    if x.get(slope_key) is not None and x[slope_key] > 0
                ]
                s = stats(xs)
                row = {
                    "ema_wma_min": ema_min,
                    "rsi_wma_min": rsi_min,
                    "wma_slope_filter": slope_name,
                    **s,
                }
                rows.append(row)

    # Rank only by net points for display; raw CSV keeps every combination.
    ranked = [x for x in rows if x["trades"] >= 20]
    ranked.sort(key=lambda x: (x["net_points"], x["positive_rate_pct"] or 0), reverse=True)

    print("\nTop combinations with >=20 trades, ranked by net points:")
    print(f"{'EMA>=':>6} {'RSI>=':>6} {'SLOPE':>8} {'N':>5} {'WIN%':>7} {'NET':>10} {'AVG':>8} {'MED':>8}")
    print("-" * 70)
    for x in ranked[:30]:
        print(
            f"{x['ema_wma_min']:6.1f} {x['rsi_wma_min']:6.1f} {x['wma_slope_filter']:>8} "
            f"{x['trades']:5d} {x['positive_rate_pct']:7.2f} {x['net_points']:10.2f} "
            f"{x['avg_points']:8.2f} {x['median_points']:8.2f}"
        )

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    with (outdir / "wma-slope-combination-matrix.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    detail_fields = [
        "session_date", "entry_time", "source", "points", "outcome",
        "rsi9", "ema3", "wma21",
        "rsi_wma_gap", "ema_wma_gap",
        "wma_delta_1", "wma_delta_2", "wma_delta_3",
        "full_stack",
    ]
    with (outdir / "trade-wma-slope-details.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=detail_fields)
        w.writeheader()
        for x in completed:
            w.writerow({k: x.get(k) for k in detail_fields})

    print(f"\nCSV matrix: {outdir / 'wma-slope-combination-matrix.csv'}")
    print(f"CSV details: {outdir / 'trade-wma-slope-details.csv'}")
    print("\nResearch only: NO strategy changes.")
    print("WMA slope means WMA21[t] - WMA21[t-N] at the signal candle.")
    print("Points remain signal-close to structural-exit-close chart-validation points.")

if __name__ == "__main__":
    main()
