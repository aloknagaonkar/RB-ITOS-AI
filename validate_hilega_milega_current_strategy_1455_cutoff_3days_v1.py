#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from collections import defaultdict
from datetime import date, timedelta

from validate_hilega_milega_final_strategy_routeA_rsi_above_wma import (
    fetch_1m,
    to5,
    rsi_wilder,
    ema,
    wma,
    cross_up,
    cross_down,
    full_alignment,
)

CUTOFF = "14:55"

def replay_day(bs, sd):
    trades = []

    active = False
    armed = False
    opening_candidate = False
    opening_holding = False

    source = ""
    entry_time = None
    entry_close = None

    for i, b in enumerate(bs):
        if None in (b.rsi, b.ema, b.wma):
            continue

        t = b.ts.strftime("%H:%M")
        prev = bs[i - 1] if i else None

        rsi_up = bool(prev and prev.rsi is not None and b.rsi > prev.rsi)
        ema_up = bool(prev and prev.ema is not None and b.ema > prev.ema)
        rsi_cross_ema = bool(prev and cross_up(prev.rsi, prev.ema, b.rsi, b.ema))
        rsi_cross_down_wma = bool(prev and cross_down(prev.rsi, prev.wma, b.rsi, b.wma))

        # HARD SESSION CUTOFF.
        # At the START of the 14:55 candle:
        # - exit any active position at 14:55 OPEN
        # - cancel armed/opening state
        # - do not allow any new entries at 14:55 or later
        if t >= CUTOFF:
            if active:
                exit_price = b.open
                trades.append({
                    "session_date": sd.isoformat(),
                    "entry_time": entry_time,
                    "entry_price": entry_close,
                    "exit_time": t,
                    "exit_price": exit_price,
                    "points": exit_price - entry_close,
                    "source": source,
                    "exit_reason": "SESSION_CUTOFF_14_55_OPEN",
                })
                active = False
                source = ""
                entry_time = None
                entry_close = None

            armed = False
            opening_candidate = False
            opening_holding = False
            continue

        # Structural exit first.
        if active and rsi_cross_down_wma:
            trades.append({
                "session_date": sd.isoformat(),
                "entry_time": entry_time,
                "entry_price": entry_close,
                "exit_time": t,
                "exit_price": b.close,
                "points": b.close - entry_close,
                "source": source,
                "exit_reason": "RSI_CROSS_BELOW_WMA21",
            })
            active = False
            source = ""
            entry_time = None
            entry_close = None
            armed = False

        # Opening path.
        if t == "09:15" and full_alignment(b):
            opening_candidate = True

        elif t == "09:20" and opening_candidate:
            if b.rsi > b.wma:
                opening_holding = True
            else:
                opening_candidate = False
                opening_holding = False

        elif t == "09:25" and opening_candidate and opening_holding:
            if b.rsi > b.wma and not active:
                active = True
                source = "OPENING_PATH"
                entry_time = t
                entry_close = b.close
                armed = False
            opening_candidate = False
            opening_holding = False

        # Path1 arm + Route A.
        if not active and rsi_cross_ema:
            armed = True

            if b.rsi > 50 and b.rsi > b.wma:
                active = True
                source = "PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21"
                entry_time = t
                entry_close = b.close
                armed = False

        # Route B; same-candle or later confirmation.
        if (
            not active
            and armed
            and (b.rsi > b.wma or b.ema > b.wma)
            and rsi_up
            and ema_up
        ):
            active = True
            source = "PATH1_ROUTE_B_STRUCTURAL"
            entry_time = t
            entry_close = b.close
            armed = False

    return trades

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dates",
        nargs="+",
        default=["2026-09-17", "2026-09-18", "2026-09-21"],
    )
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

    print("\nCURRENT STRATEGY + HARD 14:55 CUTOFF")
    print("No new entries at or after 14:55.")
    print("Any active trade is closed at the 14:55 candle OPEN.\n")

    for sd in target_dates:
        xs = replay_day(by_day[sd], sd)
        all_trades.extend(xs)

        print(f"=== {sd} ===")
        print(f"{'ENTRY':5} {'SOURCE':43} {'EXIT':5} {'REASON':29} {'PTS':>8}")
        print("-" * 100)
        for x in xs:
            print(
                f"{x['entry_time']:5} "
                f"{x['source'][:43]:43} "
                f"{x['exit_time']:5} "
                f"{x['exit_reason'][:29]:29} "
                f"{x['points']:8.2f}"
            )

        net = sum(x["points"] for x in xs)
        pos = sum(1 for x in xs if x["points"] > 0)
        neg = sum(1 for x in xs if x["points"] < 0)
        print(f"Summary: trades={len(xs)} positive={pos} negative={neg} net={net:+.2f}\n")

    net = sum(x["points"] for x in all_trades)
    pos = sum(1 for x in all_trades if x["points"] > 0)
    neg = sum(1 for x in all_trades if x["points"] < 0)
    cutoff_exits = sum(1 for x in all_trades if x["exit_reason"] == "SESSION_CUTOFF_14_55_OPEN")

    print("=== COMBINED ===")
    print(f"Trades: {len(all_trades)}")
    print(f"Positive: {pos}")
    print(f"Negative: {neg}")
    print(f"Net points: {net:+.2f}")
    print(f"14:55 cutoff exits: {cutoff_exits}")
    print("\nValidation note:")
    print("- Entry remains signal-candle CLOSE, matching the current chart-validation baseline.")
    print("- Structural exit remains exit-candle CLOSE.")
    print("- Only the hard session cutoff uses 14:55 candle OPEN, because the rule is to be flat from 14:55 onward.")
    print("- This is still chart-validation, not executable option P&L.")

if __name__ == "__main__":
    main()
