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

MODEL = "HILEGA_MILEGA_BULLISH_STRONG_BULLISH_V1_6"
DEFAULT_UNDERLYING = "NSE_INDEX|Nifty 50"


def detect_states(bars, rsi9, ema3, wma21, session_date):
    rows = []
    armed_at = None
    pending_strong = None

    for i in range(1, len(bars)):
        if bars[i]["start"].date().isoformat() != session_date:
            continue

        vals = (rsi9[i-1], ema3[i-1], wma21[i-1], rsi9[i], ema3[i], wma21[i])
        if any(v is None for v in vals):
            continue

        rp, ep, wp, r, e, w = map(float, vals)

        rsi_cross_ema = rp <= ep and r > e
        rsi_cross_wma = rp <= wp and r > w

        if rsi_cross_ema:
            armed_at = bars[i]["start"]

        # First create BULLISH only after the intended sequence.
        if armed_at is not None and rsi_cross_wma and r > 50.0:
            bullish_time = bars[i]["start"]
            row = {
                "session_date": session_date,
                "rsi_ema_cross_time": armed_at.isoformat(),
                "bullish_time": bullish_time.isoformat(),
                "bullish_close": float(bars[i]["close"]),
                "rsi9": r,
                "ema3": e,
                "wma21": w,
                "sequence_duration_minutes": int(
                    (bullish_time - armed_at).total_seconds() // 60
                ),
                "strong_time": None,
                "strong_delay_minutes": None,
                "strong_same_candle": False,
            }

            # If both RSI and EMA3 are already above WMA21, STRONG is immediate.
            if r > w and e > w:
                row["strong_time"] = bullish_time.isoformat()
                row["strong_delay_minutes"] = 0
                row["strong_same_candle"] = True
                rows.append(row)
                pending_strong = None
            else:
                rows.append(row)
                pending_strong = len(rows) - 1

            armed_at = None
            continue

        # If bullish was formed but EMA3 was not above WMA21 yet,
        # upgrade later when EMA3 becomes > WMA21 while RSI remains > WMA21 and >50.
        if pending_strong is not None:
            if r > 50.0 and r > w and e > w:
                bt = datetime.fromisoformat(rows[pending_strong]["bullish_time"])
                st = bars[i]["start"]
                rows[pending_strong]["strong_time"] = st.isoformat()
                rows[pending_strong]["strong_delay_minutes"] = int(
                    (st - bt).total_seconds() // 60
                )
                pending_strong = None

    return rows


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
    return body.get("data", {}).get("candles", [])


def main():
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
    start = min(targets) - timedelta(days=args.warmup_calendar_days)
    end = max(targets)

    raw = []
    available = set()

    with httpx.Client(base_url="https://api.upstox.com", timeout=30) as client:
        d = start
        while d <= end:
            ds = d.isoformat()
            try:
                candles = _fetch(client, token, encoded, ds, intraday=(intraday_date == d))
                print(f"{'intraday' if intraday_date == d else 'fetch'} {ds}: candles={len(candles)}")
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

    print("\n=== BRANCH C BULLISH / STRONG BULLISH ===\n")

    total_bull = total_strong = 0

    for target in targets:
        ds = target.isoformat()

        if ds not in available:
            print(f"{ds}: UNAVAILABLE")
            continue

        rows = detect_states(bars, rsi9, ema3, wma21, ds)
        print(f"{ds}: bullish={len(rows)} strong={sum(r['strong_time'] is not None for r in rows)}")

        if not rows:
            print("  NONE")
            continue

        for n, row in enumerate(rows, 1):
            total_bull += 1
            bt = datetime.fromisoformat(row["bullish_time"])
            c1 = datetime.fromisoformat(row["rsi_ema_cross_time"])

            if row["strong_time"] is not None:
                total_strong += 1
                st = datetime.fromisoformat(row["strong_time"])
                strong_txt = (
                    f"STRONG={st:%H:%M} "
                    f"strong_delay={row['strong_delay_minutes']}m"
                )
            else:
                strong_txt = "STRONG=NOT_REACHED"

            print(
                f"  {n:02d}. "
                f"C1(RSI↑EMA)={c1:%H:%M} "
                f"BULLISH(RSI↑WMA & RSI>50)={bt:%H:%M} "
                f"seq_duration={row['sequence_duration_minutes']}m "
                f"RSI9={row['rsi9']:.4f} "
                f"EMA3={row['ema3']:.4f} "
                f"WMA21={row['wma21']:.4f} "
                f"{strong_txt}"
            )

    print(
        f"\ntotal_bullish={total_bull} "
        f"total_strong={total_strong}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
