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

def fmt(v, nd=2):
    return "NA" if v is None else f"{v:.{nd}f}"

def safe_delta(cur, prev):
    if cur is None or prev is None:
        return None
    return cur - prev

def locate_bar_index(bs, entry_time: str):
    for i, b in enumerate(bs):
        if b.ts.strftime("%H:%M") == entry_time:
            return i
    return None

def extract_followthrough(bs, entry_i: int, horizon: int = 3):
    e = bs[entry_i]
    out = {}

    # Entry-state fields.
    out["entry_rsi"] = e.rsi
    out["entry_ema"] = e.ema
    out["entry_wma"] = e.wma
    out["entry_close"] = e.close
    out["entry_rsi_wma_gap"] = None if None in (e.rsi, e.wma) else e.rsi - e.wma
    out["entry_ema_wma_gap"] = None if None in (e.ema, e.wma) else e.ema - e.wma

    for n in range(1, horizon + 1):
        j = entry_i + n
        prefix = f"t{n}"
        if j >= len(bs):
            for k in [
                "time", "close", "price_delta", "rsi", "rsi_delta",
                "ema", "ema_delta", "wma", "wma_delta",
                "rsi_wma_gap", "rsi_wma_gap_change",
                "ema_wma_gap", "ema_wma_gap_change",
                "rsi_rising_vs_prev", "ema_rising_vs_prev", "wma_rising_vs_prev",
                "price_up_vs_entry",
            ]:
                out[f"{prefix}_{k}"] = None
            continue

        b = bs[j]
        prev = bs[j - 1]
        rsi_wma_gap = None if None in (b.rsi, b.wma) else b.rsi - b.wma
        ema_wma_gap = None if None in (b.ema, b.wma) else b.ema - b.wma

        out[f"{prefix}_time"] = b.ts.strftime("%H:%M")
        out[f"{prefix}_close"] = b.close
        out[f"{prefix}_price_delta"] = b.close - e.close
        out[f"{prefix}_rsi"] = b.rsi
        out[f"{prefix}_rsi_delta"] = safe_delta(b.rsi, e.rsi)
        out[f"{prefix}_ema"] = b.ema
        out[f"{prefix}_ema_delta"] = safe_delta(b.ema, e.ema)
        out[f"{prefix}_wma"] = b.wma
        out[f"{prefix}_wma_delta"] = safe_delta(b.wma, e.wma)
        out[f"{prefix}_rsi_wma_gap"] = rsi_wma_gap
        out[f"{prefix}_rsi_wma_gap_change"] = safe_delta(rsi_wma_gap, out["entry_rsi_wma_gap"])
        out[f"{prefix}_ema_wma_gap"] = ema_wma_gap
        out[f"{prefix}_ema_wma_gap_change"] = safe_delta(ema_wma_gap, out["entry_ema_wma_gap"])
        out[f"{prefix}_rsi_rising_vs_prev"] = (
            None if None in (b.rsi, prev.rsi) else b.rsi > prev.rsi
        )
        out[f"{prefix}_ema_rising_vs_prev"] = (
            None if None in (b.ema, prev.ema) else b.ema > prev.ema
        )
        out[f"{prefix}_wma_rising_vs_prev"] = (
            None if None in (b.wma, prev.wma) else b.wma > prev.wma
        )
        out[f"{prefix}_price_up_vs_entry"] = b.close > e.close

    return out

def avg(rows, key):
    vals = [x[key] for x in rows if x.get(key) is not None]
    return None if not vals else sum(vals) / len(vals)

def pct(rows, key, truth=True):
    vals = [x[key] for x in rows if x.get(key) is not None]
    if not vals:
        return None
    return 100.0 * sum(1 for v in vals if bool(v) is truth) / len(vals)

def print_group_summary(name, rows):
    print(f"\n=== {name} ({len(rows)} trades) ===")
    if not rows:
        return
    for n in (1, 2, 3):
        print(
            f"T+{n}: "
            f"avg_price={fmt(avg(rows, f't{n}_price_delta'))}  "
            f"avg_RSIΔ={fmt(avg(rows, f't{n}_rsi_delta'))}  "
            f"avg_EMAΔ={fmt(avg(rows, f't{n}_ema_delta'))}  "
            f"avg_WMAΔ={fmt(avg(rows, f't{n}_wma_delta'))}  "
            f"avg_RSI-WMA_gapΔ={fmt(avg(rows, f't{n}_rsi_wma_gap_change'))}  "
            f"avg_EMA-WMA_gapΔ={fmt(avg(rows, f't{n}_ema_wma_gap_change'))}"
        )
        print(
            f"     price_up={fmt(pct(rows, f't{n}_price_up_vs_entry'))}%  "
            f"RSI_rising={fmt(pct(rows, f't{n}_rsi_rising_vs_prev'))}%  "
            f"EMA_rising={fmt(pct(rows, f't{n}_ema_rising_vs_prev'))}%  "
            f"WMA_rising={fmt(pct(rows, f't{n}_wma_rising_vs_prev'))}%"
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
    ap.add_argument(
        "--output-dir",
        default="data/historical-evidence/hilega-milega-followthrough-sep17-18-21-v1",
    )
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

    rows = []

    for sd in target_dates:
        bs = by_day[sd]
        trades = [
            x for x in replay_trades(bs, sd)
            if x["outcome"] in {"POSITIVE", "NEGATIVE", "FLAT"}
        ]

        print(f"\n=== {sd} ===")
        print(
            f"{'ENTRY':5} {'SRC':7} {'PTS':>8} {'OUTCOME':>9} "
            f"{'T+1 PTS':>8} {'T+1 RSIΔ':>9} {'T+1 EMAΔ':>9} {'T+1 GAPΔ':>9} "
            f"{'T+2 PTS':>8} {'T+3 PTS':>8}"
        )
        print("-" * 104)

        for t in trades:
            i = locate_bar_index(bs, t["entry_time"])
            if i is None:
                continue

            ft = extract_followthrough(bs, i, 3)
            row = {
                "session_date": sd.isoformat(),
                "entry_time": t["entry_time"],
                "source": t["source"],
                "points": t["points"],
                "outcome": t["outcome"],
            }
            row.update(ft)
            rows.append(row)

            print(
                f"{t['entry_time']:5} {t['source']:7} {t['points']:8.2f} {t['outcome']:>9} "
                f"{fmt(ft['t1_price_delta']):>8} {fmt(ft['t1_rsi_delta']):>9} "
                f"{fmt(ft['t1_ema_delta']):>9} {fmt(ft['t1_rsi_wma_gap_change']):>9} "
                f"{fmt(ft['t2_price_delta']):>8} {fmt(ft['t3_price_delta']):>8}"
            )

    positive = [x for x in rows if x["outcome"] == "POSITIVE"]
    negative = [x for x in rows if x["outcome"] == "NEGATIVE"]

    print_group_summary("POSITIVE", positive)
    print_group_summary("NEGATIVE", negative)

    print("\n=== SIMPLE FOLLOW-THROUGH FLAGS ===")
    tests = [
        ("T+1 price > entry", lambda x: x.get("t1_price_delta") is not None and x["t1_price_delta"] > 0),
        ("T+1 RSI > entry RSI", lambda x: x.get("t1_rsi_delta") is not None and x["t1_rsi_delta"] > 0),
        ("T+1 EMA > entry EMA", lambda x: x.get("t1_ema_delta") is not None and x["t1_ema_delta"] > 0),
        ("T+1 RSI-WMA gap expands", lambda x: x.get("t1_rsi_wma_gap_change") is not None and x["t1_rsi_wma_gap_change"] > 0),
        ("T+1 price+RSI positive", lambda x: (
            x.get("t1_price_delta") is not None and x["t1_price_delta"] > 0
            and x.get("t1_rsi_delta") is not None and x["t1_rsi_delta"] > 0
        )),
        ("T+2 price > entry", lambda x: x.get("t2_price_delta") is not None and x["t2_price_delta"] > 0),
        ("T+3 price > entry", lambda x: x.get("t3_price_delta") is not None and x["t3_price_delta"] > 0),
    ]

    for label, fn in tests:
        p_pass = sum(1 for x in positive if fn(x))
        n_pass = sum(1 for x in negative if fn(x))
        print(
            f"{label:30} "
            f"positive={p_pass}/{len(positive)} "
            f"negative={n_pass}/{len(negative)}"
        )

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    if rows:
        with (outdir / "followthrough-trade-details.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    print(f"\nCSV: {outdir / 'followthrough-trade-details.csv'}")
    print("\nResearch only: this does NOT alter strategy entries.")
    print("T+1/T+2/T+3 are closed 5-minute candles after the signal candle.")
    print("This is a confirmation study, not executable P&L.")

if __name__ == "__main__":
    main()
