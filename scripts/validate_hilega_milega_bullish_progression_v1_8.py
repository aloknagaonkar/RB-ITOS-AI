from __future__ import annotations

import argparse
import csv
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

MODEL = "HILEGA_MILEGA_BULLISH_PROGRESSION_V1_8"
DEFAULT_UNDERLYING = "NSE_INDEX|Nifty 50"
DEFAULT_DATES = [
    "2026-09-15",
    "2026-09-16",
    "2026-09-17",
    "2026-09-18",
    "2026-09-21",
]


def cross_up(prev_a, prev_b, a, b):
    return prev_a <= prev_b and a > b


def cross_down(prev_a, prev_b, a, b):
    return prev_a >= prev_b and a < b


def cross_level_up(prev_v, v, level=50.0):
    return prev_v <= level and v > level


def build_progression_timeline(bars, rsi9, ema3, wma21, session_date):
    rows = []

    armed = False
    active_setup = False
    bullish = False
    strong = False
    full = False

    for i in range(1, len(bars)):
        if bars[i]["start"].date().isoformat() != session_date:
            continue

        vals = (rsi9[i-1], ema3[i-1], wma21[i-1], rsi9[i], ema3[i], wma21[i])
        if any(v is None for v in vals):
            continue

        rp, ep, wp, r, e, w = map(float, vals)
        t = bars[i]["start"]

        rsi_up_ema = cross_up(rp, ep, r, e)
        rsi_up_wma = cross_up(rp, wp, r, w)
        rsi_down_wma = cross_down(rp, wp, r, w)
        ema_up_wma = cross_up(ep, wp, e, w)

        rsi_up_50 = cross_level_up(rp, r)
        ema_up_50 = cross_level_up(ep, e)
        wma_up_50 = cross_level_up(wp, w)

        events = []
        before = (
            "FULL" if full else
            "STRONG" if strong else
            "BULLISH" if bullish else
            "ACTIVE_SETUP" if active_setup else
            "ARMED" if armed else
            "NEUTRAL"
        )

        # Invalidation remains an observed/manual-review event.
        if (active_setup or bullish or strong or full) and rsi_down_wma:
            events.append("RSI↓WMA / INVALIDATION")
            armed = active_setup = bullish = strong = full = False

        if not (active_setup or bullish or strong or full) and rsi_up_ema:
            armed = True
            events.append("RSI↑EMA / ARMED")
        elif (active_setup or bullish or strong or full) and rsi_up_ema:
            events.append("RSI↑EMA / CONTINUATION")

        if armed and rsi_up_wma:
            active_setup = True
            armed = False
            events.append("RSI↑WMA / ACTIVE_SETUP")
        elif (active_setup or bullish or strong or full) and rsi_up_wma:
            events.append("RSI↑WMA / CONTINUATION")

        if ema_up_wma:
            events.append("EMA3↑WMA")
        if rsi_up_50:
            events.append("RSI↑50")
        if ema_up_50:
            events.append("EMA3↑50")
        if wma_up_50:
            events.append("WMA21↑50")

        # Progression uses current relationships; crossings may occur on different candles.
        if active_setup and not bullish and r > w and r > 50.0:
            bullish = True
            events.append("BULLISH")

        if active_setup and bullish and not strong and r > w and e > w and r > 50.0:
            strong = True
            events.append("STRONG_BULLISH")

        if strong and not full and r > 50.0 and e > 50.0 and w > 50.0 and r > e > w:
            full = True
            events.append("FULL_BULLISH_ALIGNMENT")

        after = (
            "FULL" if full else
            "STRONG" if strong else
            "BULLISH" if bullish else
            "ACTIVE_SETUP" if active_setup else
            "ARMED" if armed else
            "NEUTRAL"
        )

        if events:
            rows.append({
                "session_date": session_date,
                "time": t.strftime("%H:%M"),
                "timestamp": t.isoformat(),
                "close": float(bars[i]["close"]),
                "events": " | ".join(events),
                "rsi9": r,
                "ema3": e,
                "wma21": w,
                "rsi_above_50": r > 50.0,
                "ema_above_50": e > 50.0,
                "wma_above_50": w > 50.0,
                "rsi_above_wma": r > w,
                "ema_above_wma": e > w,
                "ordered_rsi_ema_wma": r > e > w,
                "state_before": before,
                "state_after": after,
                "manual_label": "",
                "manual_notes": "",
            })

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
        default="data/historical-evidence/branch-c-bullish-progression-v1-8.csv",
    )
    args = ap.parse_args()

    requested = args.session_date or DEFAULT_DATES
    targets = sorted({date.fromisoformat(x) for x in requested})
    intraday_date = (
        date.fromisoformat(args.intraday_date)
        if args.intraday_date
        else max(targets)
    )

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
                intraday = d == intraday_date
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

    all_rows = []

    print("\n=== BRANCH C BULLISH PROGRESSION V1.8 ===\n")

    for target in targets:
        ds = target.isoformat()

        if ds not in available:
            print(f"\n{ds}: UNAVAILABLE")
            continue

        rows = build_progression_timeline(bars, rsi9, ema3, wma21, ds)
        all_rows.extend(rows)

        print(f"\n--- {ds} ---")
        if not rows:
            print("NO STRUCTURAL EVENTS")
            continue

        for row in rows:
            print(
                f"{row['time']}  {row['events']}\n"
                f"       close={row['close']:.2f} "
                f"RSI={row['rsi9']:.4f} "
                f"EMA3={row['ema3']:.4f} "
                f"WMA21={row['wma21']:.4f}\n"
                f"       >50(R/E/W)="
                f"{'Y' if row['rsi_above_50'] else 'N'}/"
                f"{'Y' if row['ema_above_50'] else 'N'}/"
                f"{'Y' if row['wma_above_50'] else 'N'} "
                f"RSI>WMA={'Y' if row['rsi_above_wma'] else 'N'} "
                f"EMA>WMA={'Y' if row['ema_above_wma'] else 'N'} "
                f"R>E>W={'Y' if row['ordered_rsi_ema_wma'] else 'N'} "
                f"state={row['state_before']}→{row['state_after']}"
            )

    csv_path = REPO_ROOT / args.csv
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "session_date", "time", "timestamp", "close", "events",
        "rsi9", "ema3", "wma21",
        "rsi_above_50", "ema_above_50", "wma_above_50",
        "rsi_above_wma", "ema_above_wma", "ordered_rsi_ema_wma",
        "state_before", "state_after",
        "manual_label", "manual_notes",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nCSV={csv_path}")
    print("Manual labels: CORRECT / FALSE / LATE / EARLY / CONTINUATION / MISSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
