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

MODEL = "HILEGA_MILEGA_OPENING_GAP_DIAGNOSTIC_V2_0"
DEFAULT_UNDERLYING = "NSE_INDEX|Nifty 50"
DEFAULT_DATES = [
    "2026-08-10",
    "2026-08-20",
    "2026-08-24",
    "2026-09-03",
    "2026-09-18",
]


def gap_metrics(prev_close: float, open_0915: float, close_0920: float, close_0925: float) -> dict:
    gap_points = open_0915 - prev_close
    gap_pct = (gap_points / prev_close * 100.0) if prev_close else 0.0

    def retained(close_now: float):
        retained_points = close_now - prev_close
        retained_pct_of_gap = (
            retained_points / gap_points * 100.0
            if gap_points != 0
            else 0.0
        )
        fill_pct = 100.0 - retained_pct_of_gap
        return retained_points, retained_pct_of_gap, fill_pct

    r20 = retained(close_0920)
    r25 = retained(close_0925)

    return {
        "gap_points": gap_points,
        "gap_pct": gap_pct,
        "gap_retained_points_0920": r20[0],
        "gap_retained_pct_0920": r20[1],
        "gap_fill_pct_0920": r20[2],
        "gap_retained_points_0925": r25[0],
        "gap_retained_pct_0925": r25[1],
        "gap_fill_pct_0925": r25[2],
    }


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


def main():
    ap = argparse.ArgumentParser(description=MODEL)
    ap.add_argument("--session-date", action="append")
    ap.add_argument("--intraday-date")
    ap.add_argument("--warmup-calendar-days", type=int, default=7)
    ap.add_argument("--underlying", default=DEFAULT_UNDERLYING)
    ap.add_argument(
        "--csv",
        default="data/historical-evidence/branch-c-opening-gap-diagnostic-v2-0.csv",
    )
    args = ap.parse_args()

    requested = args.session_date or DEFAULT_DATES
    targets = sorted({date.fromisoformat(x) for x in requested})
    intraday_date = date.fromisoformat(args.intraday_date) if args.intraday_date else None

    load_dotenv(REPO_ROOT / ".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("UPSTOX_ACCESS_TOKEN missing")

    encoded = quote(args.underlying, safe="")
    fetch_start = min(targets) - timedelta(days=args.warmup_calendar_days)
    fetch_end = max(targets)

    raw = []
    available = set()

    with httpx.Client(base_url="https://api.upstox.com", timeout=30) as client:
        d = fetch_start
        while d <= fetch_end:
            ds = d.isoformat()
            try:
                intraday = intraday_date is not None and d == intraday_date
                candles = _fetch(client, token, encoded, ds, intraday=intraday)
                print(f"{'intraday' if intraday else 'fetch'} {ds}: candles={len(candles)}")
                if candles:
                    available.add(ds)
                raw.extend(candles)
            except Exception as exc:
                print(f"fetch {ds}: ERROR {exc}")
            d += timedelta(days=1)

    bars = make_5m(parse_1m(raw))
    closes = [b["close"] for b in bars]
    rsi9 = pine_rsi(closes, 9)
    ema3 = ema(rsi9, 3)
    wma21 = wma(rsi9, 21)

    by_date = {}
    for i, b in enumerate(bars):
        by_date.setdefault(b["start"].date().isoformat(), []).append((i, b))

    all_rows = []

    print("\n=== BRANCH C OPENING GAP DIAGNOSTIC V2.0 ===\n")

    for target in targets:
        ds = target.isoformat()
        session = by_date.get(ds, [])
        if not session:
            print(f"{ds}: UNAVAILABLE")
            continue

        # previous available trading session before target
        previous_dates = sorted(d for d in by_date if d < ds and by_date[d])
        if not previous_dates:
            print(f"{ds}: NO_PREVIOUS_SESSION")
            continue

        prev_ds = previous_dates[-1]
        prev_session = by_date[prev_ds]
        prev_close = float(prev_session[-1][1]["close"])

        time_map = {b["start"].strftime("%H:%M"): (i, b) for i, b in session}
        needed = ["09:15", "09:20", "09:25"]
        if not all(t in time_map for t in needed):
            print(f"{ds}: MISSING_OPENING_BARS")
            continue

        i15, b15 = time_map["09:15"]
        i20, b20 = time_map["09:20"]
        i25, b25 = time_map["09:25"]

        # 5m bar open should reflect 09:15 session open.
        open_0915 = float(b15["open"])
        close_0915 = float(b15["close"])
        close_0920 = float(b20["close"])
        close_0925 = float(b25["close"])

        gm = gap_metrics(prev_close, open_0915, close_0920, close_0925)

        row = {
            "session_date": ds,
            "previous_session_date": prev_ds,
            "previous_close": prev_close,
            "open_0915": open_0915,
            "gap_points": gm["gap_points"],
            "gap_pct": gm["gap_pct"],
            "close_0915": close_0915,
            "close_0920": close_0920,
            "close_0925": close_0925,
            "gap_retained_pct_0920": gm["gap_retained_pct_0920"],
            "gap_fill_pct_0920": gm["gap_fill_pct_0920"],
            "gap_retained_pct_0925": gm["gap_retained_pct_0925"],
            "gap_fill_pct_0925": gm["gap_fill_pct_0925"],
        }

        for label, idx in [("0915", i15), ("0920", i20), ("0925", i25)]:
            r = float(rsi9[idx])
            e = float(ema3[idx])
            w = float(wma21[idx])
            row[f"rsi_{label}"] = r
            row[f"ema_{label}"] = e
            row[f"wma_{label}"] = w
            row[f"rsi_wma_gap_{label}"] = r - w
            row[f"ema_wma_gap_{label}"] = e - w

        all_rows.append(row)

        print(f"--- {ds} ---")
        print(f"prev_session={prev_ds} prev_close={prev_close:.2f}")
        print(
            f"09:15 open={open_0915:.2f} close={close_0915:.2f} "
            f"gap={gm['gap_points']:+.2f} ({gm['gap_pct']:+.3f}%)"
        )
        print(
            f"09:20 close={close_0920:.2f} "
            f"gap_retained={gm['gap_retained_pct_0920']:.1f}% "
            f"gap_fill={gm['gap_fill_pct_0920']:.1f}%"
        )
        print(
            f"09:25 close={close_0925:.2f} "
            f"gap_retained={gm['gap_retained_pct_0925']:.1f}% "
            f"gap_fill={gm['gap_fill_pct_0925']:.1f}%"
        )
        print(
            f"09:15 RSI={row['rsi_0915']:.2f} EMA={row['ema_0915']:.2f} WMA={row['wma_0915']:.2f} "
            f"RSI-WMA={row['rsi_wma_gap_0915']:+.2f} EMA-WMA={row['ema_wma_gap_0915']:+.2f}"
        )
        print(
            f"09:20 RSI={row['rsi_0920']:.2f} EMA={row['ema_0920']:.2f} WMA={row['wma_0920']:.2f} "
            f"RSI-WMA={row['rsi_wma_gap_0920']:+.2f} EMA-WMA={row['ema_wma_gap_0920']:+.2f}"
        )
        print(
            f"09:25 RSI={row['rsi_0925']:.2f} EMA={row['ema_0925']:.2f} WMA={row['wma_0925']:.2f} "
            f"RSI-WMA={row['rsi_wma_gap_0925']:+.2f} EMA-WMA={row['ema_wma_gap_0925']:+.2f}"
        )
        print()

    csv_path = REPO_ROOT / args.csv
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if all_rows:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_rows)

    print(f"CSV={csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
