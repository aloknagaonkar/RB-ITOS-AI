#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from collections import defaultdict
from datetime import date, timedelta

from analyze_hilega_milega_bullish_expansion_multisession_v1 import (
    fetch_1m,
    to5,
    rsi_wilder,
    ema,
    wma,
    replay_trades,
)

def passed(x, ema_min=2.0, rsi_min=10.0, wma3_min=2.0):
    return (
        bool(x.get("full_stack"))
        and x.get("ema_wma_gap") is not None
        and x.get("rsi_wma_gap") is not None
        and x.get("wma_delta_3") is not None
        and x["ema_wma_gap"] >= ema_min
        and x["rsi_wma_gap"] >= rsi_min
        and x["wma_delta_3"] > wma3_min
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dates",
        nargs="+",
        default=["2026-09-17", "2026-09-18", "2026-09-21"],
    )
    ap.add_argument("--warmup-calendar-days", type=int, default=45)
    ap.add_argument("--token-env", default="UPSTOX_ACCESS_TOKEN")
    ap.add_argument("--ema-wma-min", type=float, default=2.0)
    ap.add_argument("--rsi-wma-min", type=float, default=10.0)
    ap.add_argument("--wma3-min", type=float, default=2.0)
    args = ap.parse_args()

    token = os.getenv(args.token_env)
    if not token:
        raise SystemExit(f"Missing {args.token_env}; load .env first")

    target_dates = sorted(date.fromisoformat(x) for x in args.dates)
    first, last = min(target_dates), max(target_dates)
    start = first - timedelta(days=args.warmup_calendar_days)

    raw = {}
    d = start
    while d <= last:
        try:
            bars = fetch_1m(token, d)
            print(f"fetch {d}: candles={len(bars)}")
            if bars:
                raw[d] = bars
        except Exception as e:
            print(f"fetch {d}: ERROR {e}")
        d += timedelta(days=1)

    missing = [d.isoformat() for d in target_dates if d not in raw]
    if missing:
        raise SystemExit(f"Missing target-session data: {', '.join(missing)}")

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

    print("\nFILTER:")
    print("  RSI > EMA3 > WMA21")
    print(f"  EMA3-WMA21 >= {args.ema_wma_min:g}")
    print(f"  RSI-WMA21  >= {args.rsi_wma_min:g}")
    print(f"  WMA3       >  {args.wma3_min:g}")
    print()

    all_trades = []
    for sd in target_dates:
        xs = [
            x for x in replay_trades(by_day[sd], sd)
            if x["outcome"] in {"POSITIVE", "NEGATIVE", "FLAT"}
        ]
        all_trades.extend(xs)

        print(f"=== {sd} ===")
        print(
            f"{'ENTRY':5} {'SRC':7} {'PTS':>8} {'OUTCOME':>9} "
            f"{'EMA-WMA':>8} {'RSI-WMA':>8} {'WMA3':>8} {'PASS?':>6}"
        )
        print("-" * 78)

        original_net = 0.0
        kept_net = 0.0
        kept = 0
        removed_neg = 0
        removed_pos = 0

        for x in xs:
            ok = passed(x, args.ema_wma_min, args.rsi_wma_min, args.wma3_min)
            original_net += x["points"]
            if ok:
                kept += 1
                kept_net += x["points"]
            else:
                if x["outcome"] == "NEGATIVE":
                    removed_neg += 1
                elif x["outcome"] == "POSITIVE":
                    removed_pos += 1

            print(
                f"{x['entry_time']:5} {x['source']:7} {x['points']:8.2f} {x['outcome']:>9} "
                f"{x['ema_wma_gap']:8.2f} {x['rsi_wma_gap']:8.2f} "
                f"{x['wma_delta_3']:8.2f} {'YES' if ok else 'NO':>6}"
            )

        print(
            f"Summary: original={len(xs)} trades, net={original_net:+.2f}; "
            f"kept={kept}, kept_net={kept_net:+.2f}; "
            f"removed_negative={removed_neg}, removed_positive={removed_pos}"
        )
        print()

    print("=== COMBINED ===")
    original_net = sum(x["points"] for x in all_trades)
    kept = [x for x in all_trades if passed(x, args.ema_wma_min, args.rsi_wma_min, args.wma3_min)]
    removed = [x for x in all_trades if x not in kept]

    print(f"Original trades: {len(all_trades)}")
    print(f"Original net: {original_net:+.2f}")
    print(f"Kept trades: {len(kept)}")
    print(f"Kept positives: {sum(1 for x in kept if x['outcome']=='POSITIVE')}")
    print(f"Kept negatives: {sum(1 for x in kept if x['outcome']=='NEGATIVE')}")
    print(f"Kept net: {sum(x['points'] for x in kept):+.2f}")
    print(f"Removed negatives: {sum(1 for x in removed if x['outcome']=='NEGATIVE')}")
    print(f"Removed positives: {sum(1 for x in removed if x['outcome']=='POSITIVE')}")
    print("\nResearch only: this does not modify strategy code.")
    print("Points remain signal-close to structural-exit-close chart-validation points.")

if __name__ == "__main__":
    main()
