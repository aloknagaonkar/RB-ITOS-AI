from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
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
from scripts.validate_hilega_milega_bullish_previous_dates_v1_3 import (
    detect_sequence_confirmations,
)

MODEL = "HILEGA_MILEGA_BULLISH_GAP_AUDIT_V1_4"
DEFAULT_UNDERLYING = "NSE_INDEX|Nifty 50"


def gap_metrics(prev_ema: float, prev_wma: float, ema_now: float, wma_now: float) -> dict:
    prev_gap = prev_ema - prev_wma
    current_gap = ema_now - wma_now
    gap_change = current_gap - prev_gap
    return {
        "prev_gap": prev_gap,
        "current_gap": current_gap,
        "gap_change": gap_change,
        "gap_expanding": gap_change > 0.0,
        "entry_delay_minutes": 0,
    }


def _fetch_historical(client, token, encoded, day):
    path = f"/v3/historical-candle/{encoded}/minutes/1/{day}/{day}"
    r = client.get(path, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"Upstox {day} HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Upstox {day} status={body.get('status')!r}")
    return body.get("data", {}).get("candles", [])


def _fetch_intraday(client, token, encoded):
    path = f"/v3/historical-candle/intraday/{encoded}/minutes/1"
    r = client.get(path, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"Upstox intraday HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Upstox intraday status={body.get('status')!r}")
    return body.get("data", {}).get("candles", [])


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def main() -> int:
    ap = argparse.ArgumentParser(description=MODEL)
    ap.add_argument("--session-date", action="append", required=True)
    ap.add_argument("--intraday-date")
    ap.add_argument("--warmup-calendar-days", type=int, default=7)
    ap.add_argument("--underlying", default=DEFAULT_UNDERLYING)
    args = ap.parse_args()

    targets = sorted({date.fromisoformat(x) for x in args.session_date})
    intraday_date = date.fromisoformat(args.intraday_date) if args.intraday_date else None

    load_dotenv(REPO_ROOT / ".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("UPSTOX_ACCESS_TOKEN missing")

    encoded = quote(args.underlying, safe="")
    fetch_start = min(targets) - timedelta(days=args.warmup_calendar_days)
    fetch_end = max(targets)

    raw = []
    with httpx.Client(base_url="https://api.upstox.com", timeout=30) as client:
        for d in daterange(fetch_start, fetch_end):
            ds = d.isoformat()
            try:
                if intraday_date is not None and d == intraday_date:
                    candles = _fetch_intraday(client, token, encoded)
                    print(f"intraday {ds}: candles={len(candles)}")
                else:
                    candles = _fetch_historical(client, token, encoded, ds)
                    print(f"fetch {ds}: candles={len(candles)}")
                raw.extend(candles)
            except Exception as exc:
                print(f"fetch {ds}: ERROR {exc}")

    bars = make_5m(parse_1m(raw))
    closes = [b["close"] for b in bars]
    rsi9 = pine_rsi(closes, 9)
    ema3 = ema(rsi9, 3)
    wma21 = wma(rsi9, 21)

    index_by_start = {b["start"].isoformat(): i for i, b in enumerate(bars)}

    print("\n=== BRANCH C SAME-CANDLE GAP AUDIT ===\n")
    for target in targets:
        ds = target.isoformat()
        rows = detect_sequence_confirmations(bars, rsi9, ema3, wma21, ds)
        print(f"{ds}: confirmations={len(rows)}")
        if not rows:
            print("  NONE/UNAVAILABLE")
            continue

        for n, row in enumerate(rows, 1):
            i = index_by_start.get(row["confirmation_time"])
            if i is None or i < 1:
                print(f"  {n:02d}. cannot compute previous-bar gap")
                continue

            vals = (ema3[i-1], wma21[i-1], ema3[i], wma21[i])
            if any(v is None for v in vals):
                print(f"  {n:02d}. insufficient indicator history")
                continue

            m = gap_metrics(float(ema3[i-1]), float(wma21[i-1]), float(ema3[i]), float(wma21[i]))
            cf = datetime.fromisoformat(row["confirmation_time"])

            print(
                f"  {n:02d}. {cf:%H:%M} "
                f"prev_gap={m['prev_gap']:+.4f} "
                f"current_gap={m['current_gap']:+.4f} "
                f"gap_change={m['gap_change']:+.4f} "
                f"EXPANDING={'PASS' if m['gap_expanding'] else 'FAIL'} "
                f"delay={m['entry_delay_minutes']}m"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
