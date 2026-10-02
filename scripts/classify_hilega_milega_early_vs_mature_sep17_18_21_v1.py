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

def classify(x):
    rsi = x.get("rsi9")
    ema3 = x.get("ema3")
    wma21 = x.get("wma21")
    rsi_wma = x.get("rsi_wma_gap")
    ema_wma = x.get("ema_wma_gap")
    wma3 = x.get("wma_delta_3")

    if None in (rsi, ema3, wma21):
        return "UNCLASSIFIED"

    full_stack = rsi > ema3 > wma21

    # Mature trend candidate: established bullish stack, meaningful separation,
    # and rising WMA over 3 candles.
    if (
        full_stack
        and ema_wma is not None and ema_wma >= 2
        and rsi_wma is not None and rsi_wma >= 10
        and wma3 is not None and wma3 > 2
    ):
        return "MATURE_BULLISH"

    # Emerging/early bullish candidate: RSI leads above both averages,
    # but the slower WMA structure is not yet mature.
    if (
        rsi > ema3
        and rsi > wma21
        and (
            not full_stack
            or ema_wma is None or ema_wma < 2
            or rsi_wma is None or rsi_wma < 10
            or wma3 is None or wma3 <= 2
        )
    ):
        return "EARLY_BULLISH"

    return "OTHER"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="+",
                    default=["2026-09-17", "2026-09-18", "2026-09-21"])
    ap.add_argument("--warmup-calendar-days", type=int, default=45)
    ap.add_argument("--token-env", default="UPSTOX_ACCESS_TOKEN")
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

    all_trades = []
    for sd in target_dates:
        xs = [
            x for x in replay_trades(by_day[sd], sd)
            if x["outcome"] in {"POSITIVE", "NEGATIVE", "FLAT"}
        ]
        all_trades.extend(xs)

        print(f"\n=== {sd} ===")
        print(
            f"{'ENTRY':5} {'SRC':7} {'PTS':>8} {'OUTCOME':>9} "
            f"{'EMA-WMA':>8} {'RSI-WMA':>8} {'WMA3':>8} {'CLASS':>16}"
        )
        print("-" * 90)

        for x in xs:
            ema_wma = x.get("ema_wma_gap")
            rsi_wma = x.get("rsi_wma_gap")
            wma3 = x.get("wma_delta_3")
            print(
                f"{x['entry_time']:5} {x['source']:7} {x['points']:8.2f} {x['outcome']:>9} "
                f"{('NA' if ema_wma is None else f'{ema_wma:.2f}'):>8} "
                f"{('NA' if rsi_wma is None else f'{rsi_wma:.2f}'):>8} "
                f"{('NA' if wma3 is None else f'{wma3:.2f}'):>8} "
                f"{classify(x):>16}"
            )

    print("\n=== CLASS SUMMARY ===")
    classes = ["MATURE_BULLISH", "EARLY_BULLISH", "OTHER", "UNCLASSIFIED"]
    for c in classes:
        xs = [x for x in all_trades if classify(x) == c]
        if not xs:
            continue
        pos = sum(1 for x in xs if x["outcome"] == "POSITIVE")
        neg = sum(1 for x in xs if x["outcome"] == "NEGATIVE")
        net = sum(x["points"] for x in xs)
        print(
            f"{c:16} n={len(xs):2d} pos={pos:2d} neg={neg:2d} "
            f"win={100*pos/len(xs):6.2f}% net={net:+8.2f}"
        )

    print("\nResearch only: this classifies existing signals; it does not change strategy rules.")
    print("EARLY_BULLISH is exploratory, not an approved entry rule.")

if __name__ == "__main__":
    main()
