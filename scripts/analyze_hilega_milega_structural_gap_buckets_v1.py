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
    Bar,
    fetch_1m,
    to5,
    rsi_wilder,
    ema,
    wma,
    replay_trades,
)

def bucket_label(v: float, edges: list[float]) -> str:
    # edges define [e0,e1), [e1,e2), ... with open tails.
    if v < edges[0]:
        return f"<{edges[0]:g}"
    for a, b in zip(edges, edges[1:]):
        if a <= v < b:
            return f"{a:g}-{b:g}"
    return f">={edges[-1]:g}"

def summarize(rows: list[dict], metric: str, edges: list[float]) -> list[dict]:
    groups = defaultdict(list)
    for x in rows:
        v = x.get(metric)
        if v is None:
            continue
        groups[bucket_label(float(v), edges)].append(x)

    order = []
    if rows:
        order.append(f"<{edges[0]:g}")
        order.extend(f"{a:g}-{b:g}" for a, b in zip(edges, edges[1:]))
        order.append(f">={edges[-1]:g}")

    out = []
    for label in order:
        xs = groups.get(label, [])
        if not xs:
            continue
        pts = [float(x["points"]) for x in xs]
        pos = sum(1 for x in xs if x["outcome"] == "POSITIVE")
        neg = sum(1 for x in xs if x["outcome"] == "NEGATIVE")
        flat = sum(1 for x in xs if x["outcome"] == "FLAT")
        out.append({
            "metric": metric,
            "bucket": label,
            "trades": len(xs),
            "positive": pos,
            "negative": neg,
            "flat": flat,
            "positive_rate_pct": 100.0 * pos / len(xs),
            "net_points": sum(pts),
            "avg_points": sum(pts) / len(pts),
            "median_points": median(pts),
            "best_points": max(pts),
            "worst_points": min(pts),
        })
    return out

def print_table(title: str, rows: list[dict]):
    print(f"\n=== {title} ===")
    print(f"{'BUCKET':>10} {'TRADES':>7} {'POS':>5} {'NEG':>5} {'WIN%':>8} "
          f"{'NET':>11} {'AVG':>9} {'MEDIAN':>9} {'BEST':>9} {'WORST':>9}")
    print("-" * 95)
    for x in rows:
        print(
            f"{x['bucket']:>10} {x['trades']:7d} {x['positive']:5d} {x['negative']:5d} "
            f"{x['positive_rate_pct']:8.2f} {x['net_points']:11.2f} "
            f"{x['avg_points']:9.2f} {x['median_points']:9.2f} "
            f"{x['best_points']:9.2f} {x['worst_points']:9.2f}"
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
        default="data/historical-evidence/hilega-milega-structural-gap-buckets-v1",
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

    print(f"\nTarget sessions with data: {len(target_dates)}")
    print(f"First target session: {target_dates[0]}")
    print(f"Last target session:  {target_dates[-1]}")
    print(f"Completed trades: {len(completed)}")
    print(f"Positive: {sum(1 for x in completed if x['outcome']=='POSITIVE')}")
    print(f"Negative: {sum(1 for x in completed if x['outcome']=='NEGATIVE')}")

    # User-requested structural gap buckets.
    ema_wma_edges = [0, 0.5, 1, 2, 3, 5]
    rsi_wma_edges = [0, 1, 2, 3, 5, 8, 12]
    rsi_ema_edges = [0, 1, 2, 3, 5, 8, 12]

    summaries = []
    for metric, edges, title in [
        ("ema_wma_gap", ema_wma_edges, "EMA3 - WMA21 GAP BUCKETS"),
        ("rsi_wma_gap", rsi_wma_edges, "RSI - WMA21 GAP BUCKETS"),
        ("rsi_ema_gap", rsi_ema_edges, "RSI - EMA3 GAP BUCKETS"),
    ]:
        rows = summarize(completed, metric, edges)
        print_table(title, rows)
        summaries.extend(rows)

    # Full-stack-only secondary view.
    full_stack = [x for x in completed if x.get("full_stack")]
    print(f"\nFull-stack trades (RSI > EMA3 > WMA21): {len(full_stack)}")
    fs_ema = summarize(full_stack, "ema_wma_gap", ema_wma_edges)
    fs_rsiw = summarize(full_stack, "rsi_wma_gap", rsi_wma_edges)
    print_table("FULL-STACK ONLY: EMA3 - WMA21 GAP", fs_ema)
    print_table("FULL-STACK ONLY: RSI - WMA21 GAP", fs_rsiw)

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    with (outdir / "structural-gap-buckets.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summaries[0].keys()))
        w.writeheader()
        w.writerows(summaries)

    full_rows = []
    full_rows.extend(fs_ema)
    full_rows.extend(fs_rsiw)
    with (outdir / "full-stack-gap-buckets.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(full_rows[0].keys()))
        w.writeheader()
        w.writerows(full_rows)

    # Also preserve completed trade details for audit.
    if completed:
        with (outdir / "completed-trade-details.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(completed[0].keys()))
            w.writeheader()
            w.writerows(completed)

    print(f"\nCSV all buckets: {outdir / 'structural-gap-buckets.csv'}")
    print(f"CSV full-stack buckets: {outdir / 'full-stack-gap-buckets.csv'}")
    print(f"CSV trade details: {outdir / 'completed-trade-details.csv'}")
    print("\nResearch only: no strategy rule changes.")
    print("Points remain signal-candle-close to structural-exit-close chart-validation points.")

if __name__ == "__main__":
    main()
