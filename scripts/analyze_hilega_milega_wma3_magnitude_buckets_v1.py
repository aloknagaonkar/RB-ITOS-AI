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

def wma3_bucket(v: float) -> str:
    if v <= 0:
        return "<=0"
    if v < 0.5:
        return "0-0.5"
    if v < 1.0:
        return "0.5-1"
    if v < 2.0:
        return "1-2"
    if v < 3.0:
        return "2-3"
    if v < 5.0:
        return "3-5"
    return ">=5"

def stats(rows):
    if not rows:
        return None
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
    if not s:
        print(f"{label:18} trades=0")
        return
    print(
        f"{label:18} "
        f"n={s['trades']:4d} "
        f"pos={s['positive']:4d} neg={s['negative']:4d} "
        f"win={s['positive_rate_pct']:6.2f}% "
        f"net={s['net_points']:9.2f} "
        f"avg={s['avg_points']:8.2f} "
        f"med={s['median_points']:8.2f} "
        f"best={s['best_points']:8.2f} "
        f"worst={s['worst_points']:8.2f}"
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--last-n-sessions", type=int, default=120)
    ap.add_argument("--warmup-calendar-days", type=int, default=45)
    ap.add_argument("--token-env", default="UPSTOX_ACCESS_TOKEN")
    ap.add_argument("--ema-wma-min", type=float, default=2.0)
    ap.add_argument("--rsi-wma-min", type=float, default=10.0)
    ap.add_argument(
        "--output-dir",
        default="data/historical-evidence/hilega-milega-wma3-magnitude-buckets-v1",
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

    candidate = [
        x for x in completed
        if x.get("full_stack")
        and x.get("ema_wma_gap") is not None
        and x.get("rsi_wma_gap") is not None
        and x["ema_wma_gap"] >= args.ema_wma_min
        and x["rsi_wma_gap"] >= args.rsi_wma_min
    ]

    print(f"\nTarget sessions: {len(target_dates)}")
    print(f"Completed trades: {len(completed)}")
    print(f"\nCandidate structural filter:")
    print(f"  RSI > EMA3 > WMA21")
    print(f"  EMA3-WMA21 >= {args.ema_wma_min:g}")
    print(f"  RSI-WMA21  >= {args.rsi_wma_min:g}")
    print_stats("CANDIDATE BASE", candidate)

    groups = defaultdict(list)
    for x in candidate:
        v = x.get("wma_delta_3")
        if v is not None:
            groups[wma3_bucket(float(v))].append(x)

    order = ["<=0", "0-0.5", "0.5-1", "1-2", "2-3", "3-5", ">=5"]

    print("\n=== WMA3 MAGNITUDE BUCKETS ===")
    for b in order:
        print_stats(f"WMA3 {b}", groups.get(b, []))

    print("\n=== CUMULATIVE MINIMUM WMA3 THRESHOLDS ===")
    thresholds = [0, 0.5, 1, 2, 3, 5]
    cumulative_rows = []
    for t in thresholds:
        xs = [x for x in candidate if x.get("wma_delta_3") is not None and x["wma_delta_3"] > t]
        print_stats(f"WMA3 > {t:g}", xs)
        s = stats(xs)
        if s:
            cumulative_rows.append({"wma3_min_exclusive": t, **s})

    bucket_rows = []
    for b in order:
        xs = groups.get(b, [])
        s = stats(xs)
        if s:
            bucket_rows.append({"wma3_bucket": b, **s})

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    with (outdir / "wma3-magnitude-buckets.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(bucket_rows[0].keys()))
        w.writeheader()
        w.writerows(bucket_rows)

    with (outdir / "wma3-cumulative-thresholds.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cumulative_rows[0].keys()))
        w.writeheader()
        w.writerows(cumulative_rows)

    detail_fields = [
        "session_date", "entry_time", "source", "points", "outcome",
        "rsi9", "ema3", "wma21",
        "rsi_wma_gap", "ema_wma_gap",
        "wma_delta_1", "wma_delta_2", "wma_delta_3",
        "full_stack",
    ]
    with (outdir / "candidate-trade-details.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=detail_fields)
        w.writeheader()
        for x in candidate:
            w.writerow({k: x.get(k) for k in detail_fields})

    print(f"\nCSV buckets: {outdir / 'wma3-magnitude-buckets.csv'}")
    print(f"CSV cumulative: {outdir / 'wma3-cumulative-thresholds.csv'}")
    print(f"CSV details: {outdir / 'candidate-trade-details.csv'}")
    print("\nResearch only: NO strategy changes.")
    print("WMA3 = WMA21[t] - WMA21[t-3] at the signal candle.")
    print("Points remain signal-close to structural-exit-close chart-validation points.")

if __name__ == "__main__":
    main()
