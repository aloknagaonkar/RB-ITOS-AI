from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.validate_hilega_milega_bullish_today_v1_1 import (
    ema,
    make_5m,
    parse_1m,
    pine_rsi,
    wma,
)

DEFAULT_UNDERLYING = "NSE_INDEX|Nifty 50"


def _fetch(client, token, encoded, day, intraday=False):
    if intraday:
        path = f"/v3/historical-candle/intraday/{encoded}/minutes/1"
    else:
        path = f"/v3/historical-candle/{encoded}/minutes/1/{day}/{day}"

    r = client.get(
        path,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    if r.status_code != 200:
        raise RuntimeError(f"Upstox {day} HTTP {r.status_code}: {r.text[:300]}")

    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Upstox {day} status={body.get('status')!r}")

    return body.get("data", {}).get("candles", [])


def load_target_signals(csv_path: Path, target_date: str):
    out = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["session_date"] != target_date:
                continue
            if row["signal_type"] not in (
                "OPENING_BULLISH_CONFIRMED",
                "INTRADAY_BULLISH",
            ):
                continue
            out.append(row)
    return out


def build_rows(bars, rsi9, ema3, wma21, target_date, start_time, end_time):
    rows = []
    started = False

    for i, b in enumerate(bars):
        ds = b["start"].date().isoformat()
        tm = b["start"].strftime("%H:%M")

        if ds != target_date:
            continue

        if tm == start_time:
            started = True

        if not started:
            continue

        r = rsi9[i]
        e = ema3[i]
        w = wma21[i]

        rows.append({
            "date": ds,
            "time": tm,
            "open": float(b["open"]),
            "high": float(b["high"]),
            "low": float(b["low"]),
            "close": float(b["close"]),
            "rsi9": None if r is None else float(r),
            "ema3": None if e is None else float(e),
            "wma21": None if w is None else float(w),
            "rsi_minus_ema3": None if r is None or e is None else float(r - e),
            "rsi_minus_wma21": None if r is None or w is None else float(r - w),
            "ema3_minus_wma21": None if e is None or w is None else float(e - w),
            "rsi_gt_50": None if r is None else bool(r > 50.0),
            "ema3_gt_wma21": None if e is None or w is None else bool(e > w),
            "rsi_gt_ema3": None if r is None or e is None else bool(r > e),
            "rsi_gt_wma21": None if r is None or w is None else bool(r > w),
        })

        if tm == end_time:
            break

    return rows


def print_rows(title, rows):
    print("\n" + "=" * 132)
    print(title)
    print("=" * 132)
    print(
        f"{'TIME':<6}"
        f"{'CLOSE':>11}"
        f"{'RSI9':>11}"
        f"{'EMA3':>11}"
        f"{'WMA21':>11}"
        f"{'R-E':>11}"
        f"{'R-W':>11}"
        f"{'E-W':>11}"
        f"{'RSI>50':>9}"
        f"{'EMA>WMA':>10}"
        f"{'RSI>EMA':>10}"
        f"{'RSI>WMA':>10}"
    )

    for r in rows:
        def f(v):
            return "NA" if v is None else f"{v:.4f}"

        print(
            f"{r['time']:<6}"
            f"{r['close']:>11.2f}"
            f"{f(r['rsi9']):>11}"
            f"{f(r['ema3']):>11}"
            f"{f(r['wma21']):>11}"
            f"{f(r['rsi_minus_ema3']):>11}"
            f"{f(r['rsi_minus_wma21']):>11}"
            f"{f(r['ema3_minus_wma21']):>11}"
            f"{str(r['rsi_gt_50']):>9}"
            f"{str(r['ema3_gt_wma21']):>10}"
            f"{str(r['rsi_gt_ema3']):>10}"
            f"{str(r['rsi_gt_wma21']):>10}"
        )


def main():
    ap = argparse.ArgumentParser(
        description="Branch C V2.3 RSI/EMA3/WMA21 candle-by-candle signal audit"
    )
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--start", help="HH:MM; optional if --all-signals used")
    ap.add_argument("--end", help="HH:MM; optional if --all-signals used")
    ap.add_argument("--all-signals", action="store_true")
    ap.add_argument(
        "--signals-csv",
        default="data/historical-evidence/branch-c-forward-outcome-v2-2.csv",
    )
    ap.add_argument("--underlying", default=DEFAULT_UNDERLYING)
    ap.add_argument("--warmup-days", type=int, default=10)
    ap.add_argument("--intraday-date", default="2026-09-21")
    ap.add_argument(
        "--output-csv",
        default="data/historical-evidence/branch-c-indicator-audit-v2-3.csv",
    )
    args = ap.parse_args()

    if not args.all_signals and (not args.start or not args.end):
        raise SystemExit("Use --start HH:MM --end HH:MM, or --all-signals")

    target = date.fromisoformat(args.date)
    intraday_date = date.fromisoformat(args.intraday_date)

    load_dotenv(REPO_ROOT / ".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("UPSTOX_ACCESS_TOKEN missing")

    encoded = quote(args.underlying, safe="")
    raw = []

    fetch_start = target - timedelta(days=args.warmup_days)

    with httpx.Client(base_url="https://api.upstox.com", timeout=30) as client:
        d = fetch_start
        while d <= target:
            ds = d.isoformat()
            candles = _fetch(
                client,
                token,
                encoded,
                ds,
                intraday=(d == intraday_date),
            )
            print(f"fetch {ds}: candles={len(candles)}")
            raw.extend(candles)
            d += timedelta(days=1)

    bars = make_5m(parse_1m(raw))
    closes = [b["close"] for b in bars]
    rsi9 = pine_rsi(closes, 9)
    ema3 = ema(rsi9, 3)
    wma21 = wma(rsi9, 21)

    ranges = []

    if args.all_signals:
        signals = load_target_signals(REPO_ROOT / args.signals_csv, args.date)
        for s in signals:
            end = s.get("bullish_end_time") or ""
            if not end:
                continue
            ranges.append((
                s["signal_type"],
                s["entry_time"],
                end,
                s.get("move_to_end_points", ""),
            ))
    else:
        ranges.append(("MANUAL", args.start, args.end, ""))

    all_rows = []

    for signal_type, start, end, points in ranges:
        rows = build_rows(
            bars, rsi9, ema3, wma21,
            args.date, start, end
        )

        title = (
            f"DATE={args.date}  TYPE={signal_type}  "
            f"BULLISH_START={start}  BULLISH_END={end}"
        )
        if points not in ("", None):
            title += f"  START_TO_END_POINTS={float(points):+.2f}"

        print_rows(title, rows)

        for r in rows:
            all_rows.append({
                "signal_type": signal_type,
                "bullish_start": start,
                "bullish_end": end,
                "start_to_end_points": points,
                **r,
            })

    out_path = REPO_ROOT / args.output_csv
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if all_rows:
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_rows)

    print(f"\nCSV={out_path}")


if __name__ == "__main__":
    main()
