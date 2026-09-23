#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from validate_hilega_milega_final_strategy_routeA_rsi_above_wma import (
    IST,
    Bar,
    fetch_1m,
    to5,
    rsi_wilder,
    ema,
    wma,
    cross_up,
    cross_down,
    full_alignment,
)

def f(v):
    return None if v is None else float(v)

def r(v, n=4):
    return "" if v is None else f"{v:.{n}f}"

def entry_metrics(bs: list[Bar], i: int) -> dict:
    b = bs[i]

    def val(j, attr):
        k = i - j
        if k < 0:
            return None
        return getattr(bs[k], attr)

    rsi = f(b.rsi)
    ema3 = f(b.ema)
    wma21 = f(b.wma)

    rsi_ema_gap = None if None in (rsi, ema3) else rsi - ema3
    rsi_wma_gap = None if None in (rsi, wma21) else rsi - wma21
    ema_wma_gap = None if None in (ema3, wma21) else ema3 - wma21

    prev_rsi = val(1, "rsi")
    prev_ema = val(1, "ema")
    prev_wma = val(1, "wma")

    prev_rsi_ema_gap = None if None in (prev_rsi, prev_ema) else prev_rsi - prev_ema
    prev_rsi_wma_gap = None if None in (prev_rsi, prev_wma) else prev_rsi - prev_wma
    prev_ema_wma_gap = None if None in (prev_ema, prev_wma) else prev_ema - prev_wma

    rsi_delta1 = None if None in (rsi, prev_rsi) else rsi - prev_rsi
    ema_delta1 = None if None in (ema3, prev_ema) else ema3 - prev_ema
    wma_delta1 = None if None in (wma21, prev_wma) else wma21 - prev_wma

    rsi_ema_gap_delta1 = None if None in (rsi_ema_gap, prev_rsi_ema_gap) else rsi_ema_gap - prev_rsi_ema_gap
    rsi_wma_gap_delta1 = None if None in (rsi_wma_gap, prev_rsi_wma_gap) else rsi_wma_gap - prev_rsi_wma_gap
    ema_wma_gap_delta1 = None if None in (ema_wma_gap, prev_ema_wma_gap) else ema_wma_gap - prev_ema_wma_gap

    def span_delta(attr, bars_back):
        old = val(bars_back, attr)
        cur = getattr(b, attr)
        return None if None in (old, cur) else cur - old

    def gap_at(back, a, c):
        x = val(back, a)
        y = val(back, c)
        return None if None in (x, y) else x - y

    rsi_ema_gap_delta2 = None
    rsi_wma_gap_delta2 = None
    ema_wma_gap_delta2 = None
    if i >= 2:
        g = gap_at(2, "rsi", "ema")
        if g is not None and rsi_ema_gap is not None:
            rsi_ema_gap_delta2 = rsi_ema_gap - g
        g = gap_at(2, "rsi", "wma")
        if g is not None and rsi_wma_gap is not None:
            rsi_wma_gap_delta2 = rsi_wma_gap - g
        g = gap_at(2, "ema", "wma")
        if g is not None and ema_wma_gap is not None:
            ema_wma_gap_delta2 = ema_wma_gap - g

    rsi_ema_gap_delta3 = None
    rsi_wma_gap_delta3 = None
    ema_wma_gap_delta3 = None
    if i >= 3:
        g = gap_at(3, "rsi", "ema")
        if g is not None and rsi_ema_gap is not None:
            rsi_ema_gap_delta3 = rsi_ema_gap - g
        g = gap_at(3, "rsi", "wma")
        if g is not None and rsi_wma_gap is not None:
            rsi_wma_gap_delta3 = rsi_wma_gap - g
        g = gap_at(3, "ema", "wma")
        if g is not None and ema_wma_gap is not None:
            ema_wma_gap_delta3 = ema_wma_gap - g

    bullish_core = (
        None not in (rsi, ema3, wma21, rsi_delta1, ema_delta1)
        and rsi > ema3
        and rsi > wma21
        and rsi_delta1 > 0
        and ema_delta1 > 0
    )
    full_stack = None not in (rsi, ema3, wma21) and rsi > ema3 > wma21

    gap_expand_re_1 = rsi_ema_gap_delta1 is not None and rsi_ema_gap_delta1 > 0
    gap_expand_rw_1 = rsi_wma_gap_delta1 is not None and rsi_wma_gap_delta1 > 0
    gap_expand_ew_1 = ema_wma_gap_delta1 is not None and ema_wma_gap_delta1 > 0

    if not bullish_core:
        expansion_class = "NO_EXPANSION"
    elif not full_stack:
        expansion_class = "EARLY_EXPANSION"
    elif gap_expand_re_1 and gap_expand_rw_1 and gap_expand_ew_1:
        expansion_class = "STRONG_EXPANSION"
    else:
        expansion_class = "CONFIRMED_EXPANSION"

    return {
        "rsi9": rsi,
        "ema3": ema3,
        "wma21": wma21,
        "rsi_delta_1": rsi_delta1,
        "ema_delta_1": ema_delta1,
        "wma_delta_1": wma_delta1,
        "rsi_delta_2": span_delta("rsi", 2),
        "ema_delta_2": span_delta("ema", 2),
        "wma_delta_2": span_delta("wma", 2),
        "rsi_delta_3": span_delta("rsi", 3),
        "ema_delta_3": span_delta("ema", 3),
        "wma_delta_3": span_delta("wma", 3),
        "rsi_ema_gap": rsi_ema_gap,
        "rsi_wma_gap": rsi_wma_gap,
        "ema_wma_gap": ema_wma_gap,
        "rsi_ema_gap_delta_1": rsi_ema_gap_delta1,
        "rsi_wma_gap_delta_1": rsi_wma_gap_delta1,
        "ema_wma_gap_delta_1": ema_wma_gap_delta1,
        "rsi_ema_gap_delta_2": rsi_ema_gap_delta2,
        "rsi_wma_gap_delta_2": rsi_wma_gap_delta2,
        "ema_wma_gap_delta_2": ema_wma_gap_delta2,
        "rsi_ema_gap_delta_3": rsi_ema_gap_delta3,
        "rsi_wma_gap_delta_3": rsi_wma_gap_delta3,
        "ema_wma_gap_delta_3": ema_wma_gap_delta3,
        "bullish_core": bullish_core,
        "full_stack": full_stack,
        "gap_expand_rsi_ema_1": gap_expand_re_1,
        "gap_expand_rsi_wma_1": gap_expand_rw_1,
        "gap_expand_ema_wma_1": gap_expand_ew_1,
        "expansion_class": expansion_class,
    }

def replay_trades(bs: list[Bar], sd: date) -> list[dict]:
    trades = []

    active = False
    armed = False
    opening_candidate = False
    opening_holding = False

    source = ""
    entry_i = None
    entry_time = ""
    entry_close = None

    for i, b in enumerate(bs):
        if None in (b.rsi, b.ema, b.wma):
            continue

        prev = bs[i - 1] if i else None
        t = b.ts.strftime("%H:%M")

        rsi_up = bool(prev and prev.rsi is not None and b.rsi > prev.rsi)
        ema_up = bool(prev and prev.ema is not None and b.ema > prev.ema)
        rsi_cross_ema = bool(prev and cross_up(prev.rsi, prev.ema, b.rsi, b.ema))
        rsi_cross_down_wma = bool(prev and cross_down(prev.rsi, prev.wma, b.rsi, b.wma))

        # Exit first, matching the chart-check strategy.
        if active and rsi_cross_down_wma:
            pts = b.close - entry_close
            row = {
                "session_date": sd.isoformat(),
                "entry_time": entry_time,
                "entry_close": entry_close,
                "exit_time": t,
                "exit_close": b.close,
                "points": pts,
                "outcome": "POSITIVE" if pts > 0 else ("NEGATIVE" if pts < 0 else "FLAT"),
                "source": source,
                "bars_held": i - entry_i,
            }
            row.update(entry_metrics(bs, entry_i))
            trades.append(row)
            active = False
            source = ""
            entry_i = None
            entry_time = ""
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
                entry_i = i
                entry_time = t
                entry_close = b.close
                armed = False
            opening_candidate = False
            opening_holding = False

        # Path 1 arm and Route A.
        if not active and rsi_cross_ema:
            armed = True

            if b.rsi > 50 and b.rsi > b.wma:
                active = True
                source = "ROUTE_A"
                entry_i = i
                entry_time = t
                entry_close = b.close
                armed = False

        # Route B may confirm on same candle or later while armed.
        if (
            not active
            and armed
            and (b.rsi > b.wma or b.ema > b.wma)
            and rsi_up
            and ema_up
        ):
            active = True
            source = "ROUTE_B"
            entry_i = i
            entry_time = t
            entry_close = b.close
            armed = False

    if active:
        # Keep censored trades visible but do not mix them into positive/negative comparison.
        b = bs[-1]
        pts = b.close - entry_close
        row = {
            "session_date": sd.isoformat(),
            "entry_time": entry_time,
            "entry_close": entry_close,
            "exit_time": b.ts.strftime("%H:%M"),
            "exit_close": b.close,
            "points": pts,
            "outcome": "CENSORED",
            "source": source,
            "bars_held": len(bs) - 1 - entry_i,
        }
        row.update(entry_metrics(bs, entry_i))
        trades.append(row)

    return trades

def avg(rows, key):
    vals = [x[key] for x in rows if x.get(key) is not None]
    return None if not vals else sum(vals) / len(vals)

def pct(rows, pred):
    if not rows:
        return None
    return 100.0 * sum(1 for x in rows if pred(x)) / len(rows)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="+", default=None,
                    help="Explicit trading dates (YYYY-MM-DD).")
    ap.add_argument("--from-date", default=None,
                    help="Range start date YYYY-MM-DD.")
    ap.add_argument("--to-date", default=None,
                    help="Range end date YYYY-MM-DD.")
    ap.add_argument("--last-n-sessions", type=int, default=None,
                    help="After fetching the range, keep only the last N sessions with data.")
    ap.add_argument("--warmup-calendar-days", type=int, default=45)
    ap.add_argument("--token-env", default="UPSTOX_ACCESS_TOKEN")
    ap.add_argument(
        "--output-dir",
        default="data/historical-evidence/hilega-milega-bullish-expansion-multisession-v1",
    )
    args = ap.parse_args()

    token = os.getenv(args.token_env)
    if not token:
        raise SystemExit(f"Missing {args.token_env}; load .env first")

    if args.dates:
        requested_dates = [date.fromisoformat(x) for x in args.dates]
        first_req, last_req = min(requested_dates), max(requested_dates)
    elif args.from_date and args.to_date:
        first_req = date.fromisoformat(args.from_date)
        last_req = date.fromisoformat(args.to_date)
        if last_req < first_req:
            raise SystemExit("--to-date must be >= --from-date")
        requested_dates = []
    else:
        raise SystemExit("Use either --dates ... OR --from-date YYYY-MM-DD --to-date YYYY-MM-DD")

    start = first_req - timedelta(days=args.warmup_calendar_days)
    last = last_req

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

    if requested_dates:
        missing = [d.isoformat() for d in requested_dates if d not in raw]
        if missing:
            raise SystemExit(f"Missing target-session data: {', '.join(missing)}")
        target_dates = sorted(requested_dates)
    else:
        target_dates = sorted(d for d in raw if first_req <= d <= last_req)
        if not target_dates:
            raise SystemExit("No trading sessions with data were found in the requested range.")

    if args.last_n_sessions is not None:
        if args.last_n_sessions <= 0:
            raise SystemExit("--last-n-sessions must be > 0")
        target_dates = target_dates[-args.last_n_sessions:]

    first = min(target_dates)
    prior_sessions = sorted(d for d in raw if d < first)[-10:]
    calc_dates = prior_sessions + target_dates

    print(f"\nTarget sessions with data: {len(target_dates)}")
    print(f"First target session: {target_dates[0]}")
    print(f"Last target session:  {target_dates[-1]}")

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
    pos = [x for x in completed if x["outcome"] == "POSITIVE"]
    neg = [x for x in completed if x["outcome"] == "NEGATIVE"]

    print("\n=== BULLISH EXPANSION ENTRY STUDY ===")
    print(f"completed={len(completed)} positive={len(pos)} negative={len(neg)}")
    print()
    print(
        f"{'DATE':10} {'ENTRY':5} {'SRC':7} {'PTS':>8} {'RSI':>7} {'EMA':>7} {'WMA':>7} "
        f"{'dRSI':>7} {'dEMA':>7} {'R-E':>7} {'R-W':>7} {'E-W':>7} "
        f"{'dR-E':>7} {'dR-W':>7} {'dE-W':>7} CLASS"
    )
    print("-" * 145)

    for x in trades:
        print(
            f"{x['session_date']:10} {x['entry_time']:5} {x['source']:7} "
            f"{x['points']:8.2f} {x['rsi9']:7.2f} {x['ema3']:7.2f} {x['wma21']:7.2f} "
            f"{(x['rsi_delta_1'] or 0):7.2f} {(x['ema_delta_1'] or 0):7.2f} "
            f"{x['rsi_ema_gap']:7.2f} {x['rsi_wma_gap']:7.2f} {x['ema_wma_gap']:7.2f} "
            f"{(x['rsi_ema_gap_delta_1'] or 0):7.2f} {(x['rsi_wma_gap_delta_1'] or 0):7.2f} "
            f"{(x['ema_wma_gap_delta_1'] or 0):7.2f} {x['expansion_class']}"
        )

    def summary(name, rows):
        print(f"\n{name}: n={len(rows)}")
        for k in [
            "rsi_delta_1", "ema_delta_1", "wma_delta_1",
            "rsi_ema_gap", "rsi_wma_gap", "ema_wma_gap",
            "rsi_ema_gap_delta_1", "rsi_wma_gap_delta_1", "ema_wma_gap_delta_1",
            "rsi_ema_gap_delta_2", "rsi_wma_gap_delta_2", "ema_wma_gap_delta_2",
            "rsi_ema_gap_delta_3", "rsi_wma_gap_delta_3", "ema_wma_gap_delta_3",
        ]:
            v = avg(rows, k)
            print(f"  avg {k:24} = {'' if v is None else f'{v:.4f}'}")
        print(f"  full_stack %              = {pct(rows, lambda x: x['full_stack']):.2f}")
        print(f"  bullish_core %            = {pct(rows, lambda x: x['bullish_core']):.2f}")
        print(f"  RSI-EMA gap expanding %   = {pct(rows, lambda x: x['gap_expand_rsi_ema_1']):.2f}")
        print(f"  RSI-WMA gap expanding %   = {pct(rows, lambda x: x['gap_expand_rsi_wma_1']):.2f}")
        print(f"  EMA-WMA gap expanding %   = {pct(rows, lambda x: x['gap_expand_ema_wma_1']):.2f}")

        classes = defaultdict(int)
        for x in rows:
            classes[x["expansion_class"]] += 1
        print("  classes:")
        for c in ["STRONG_EXPANSION", "CONFIRMED_EXPANSION", "EARLY_EXPANSION", "NO_EXPANSION"]:
            print(f"    {c:22} {classes[c]}")

    summary("POSITIVE", pos)
    summary("NEGATIVE", neg)

    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    fieldnames = list(trades[0].keys()) if trades else []
    with (outdir / "trade-expansion-details.csv").open("w", newline="", encoding="utf-8") as fh:
        if fieldnames:
            w = csv.DictWriter(fh, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(trades)

    # Simple class/outcome matrix.
    matrix = defaultdict(lambda: defaultdict(int))
    points_by_class = defaultdict(list)
    for x in completed:
        matrix[x["expansion_class"]][x["outcome"]] += 1
        points_by_class[x["expansion_class"]].append(x["points"])

    matrix_rows = []
    for c in ["STRONG_EXPANSION", "CONFIRMED_EXPANSION", "EARLY_EXPANSION", "NO_EXPANSION"]:
        vals = points_by_class[c]
        matrix_rows.append({
            "expansion_class": c,
            "positive": matrix[c]["POSITIVE"],
            "negative": matrix[c]["NEGATIVE"],
            "flat": matrix[c]["FLAT"],
            "trades": len(vals),
            "net_points": sum(vals),
            "avg_points": None if not vals else sum(vals) / len(vals),
            "positive_rate_pct": None if not vals else 100.0 * matrix[c]["POSITIVE"] / len(vals),
        })

    with (outdir / "expansion-class-summary.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(matrix_rows[0].keys()))
        w.writeheader()
        w.writerows(matrix_rows)


    # Per-day summary for robustness inspection.
    day_rows = []
    for sd in target_dates:
        xs = [x for x in completed if x["session_date"] == sd.isoformat()]
        ps = [x for x in xs if x["outcome"] == "POSITIVE"]
        ns = [x for x in xs if x["outcome"] == "NEGATIVE"]
        day_rows.append({
            "session_date": sd.isoformat(),
            "completed_trades": len(xs),
            "positive": len(ps),
            "negative": len(ns),
            "net_points": sum(x["points"] for x in xs),
            "avg_points": None if not xs else sum(x["points"] for x in xs) / len(xs),
        })

    with (outdir / "day-summary.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(day_rows[0].keys()))
        w.writeheader()
        w.writerows(day_rows)

    print(f"\nCSV details: {outdir / 'trade-expansion-details.csv'}")
    print(f"CSV class summary: {outdir / 'expansion-class-summary.csv'}")
    print(f"CSV day summary: {outdir / 'day-summary.csv'}")
    print("\nResearch only: this script does NOT change entry rules.")
    print("Points are still signal-candle-close to structural-exit-close for chart validation.")

if __name__ == "__main__":
    main()
