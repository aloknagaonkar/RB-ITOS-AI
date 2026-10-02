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

MODEL = "HILEGA_MILEGA_MANUAL_VALIDATION_V1_7"
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


def build_manual_timeline(bars, rsi9, ema3, wma21, session_date):
    rows = []
    state = "NEUTRAL"
    armed_at = None
    strong = False

    for i in range(1, len(bars)):
        if bars[i]["start"].date().isoformat() != session_date:
            continue

        vals = (rsi9[i-1], ema3[i-1], wma21[i-1], rsi9[i], ema3[i], wma21[i])
        if any(v is None for v in vals):
            continue

        rp, ep, wp, r, e, w = map(float, vals)
        t = bars[i]["start"]
        state_before = state

        rsi_up_ema = cross_up(rp, ep, r, e)
        rsi_up_wma = cross_up(rp, wp, r, w)
        rsi_down_wma = cross_down(rp, wp, r, w)
        ema_up_wma = cross_up(ep, wp, e, w)

        events = []

        # Bullish-state invalidation has priority.
        if state == "BULLISH" and rsi_down_wma:
            events.append("RSI↓WMA / BULLISH_END")
            state = "NEUTRAL"
            armed_at = None
            strong = False

        # New RSI↑EMA sequence arm only when no bullish state is active.
        if state != "BULLISH" and rsi_up_ema:
            armed_at = t
            state = "ARMED"
            events.append("RSI↑EMA / ARMED")

        # Inside an existing bullish regime, RSI↑EMA is a continuation clue.
        elif state == "BULLISH" and rsi_up_ema:
            events.append("RSI↑EMA / CONTINUATION")

        # Bullish start requires the intended ordered sequence and RSI > 50.
        if state == "ARMED" and armed_at is not None and rsi_up_wma:
            events.append("RSI↑WMA")
            if r > 50.0:
                state = "BULLISH"
                events.append("BULLISH_START")
                strong = e > w
                if strong:
                    events.append("STRONG_BULLISH")
                armed_at = None
            else:
                events.append("RSI↑WMA BELOW_50 / NO_BULLISH")

        # Once already bullish, an RSI↑WMA event is continuation, not a new start.
        elif state == "BULLISH" and rsi_up_wma:
            events.append("RSI↑WMA / CONTINUATION")

        # Strong upgrade can occur later while bullish remains alive.
        if state == "BULLISH" and not strong and e > w:
            strong = True
            events.append("STRONG_BULLISH")

        # Record EMA↑WMA as a raw event even if strong status was already inferred by level.
        if ema_up_wma:
            events.append("EMA3↑WMA")

        # Only print/CSV actual structural events.
        if not events:
            continue

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
            "rsi_above_wma": r > w,
            "ema_above_wma": e > w,
            "rsi_slope_up": r > rp,
            "ema_slope_up": e > ep,
            "wma_slope_up": w > wp,
            "state_before": state_before,
            "state_after": state,
            "strong_active": strong,
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
        default="data/historical-evidence/branch-c-manual-validation-v1-7.csv",
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

    print("\n=== BRANCH C FIVE-DAY MANUAL VALIDATION ===\n")

    for target in targets:
        ds = target.isoformat()

        if ds not in available:
            print(f"\n{ds}: UNAVAILABLE")
            continue

        rows = build_manual_timeline(bars, rsi9, ema3, wma21, ds)
        all_rows.extend(rows)

        print(f"\n--- {ds} ---")
        if not rows:
            print("NO STRUCTURAL EVENTS")
            continue

        for row in rows:
            print(
                f"{row['time']}  "
                f"{row['events']}\n"
                f"       close={row['close']:.2f} "
                f"RSI={row['rsi9']:.4f} "
                f"EMA3={row['ema3']:.4f} "
                f"WMA21={row['wma21']:.4f}\n"
                f"       >50={'Y' if row['rsi_above_50'] else 'N'} "
                f"RSI>WMA={'Y' if row['rsi_above_wma'] else 'N'} "
                f"EMA>WMA={'Y' if row['ema_above_wma'] else 'N'} "
                f"slopes(R/E/W)="
                f"{'Y' if row['rsi_slope_up'] else 'N'}/"
                f"{'Y' if row['ema_slope_up'] else 'N'}/"
                f"{'Y' if row['wma_slope_up'] else 'N'} "
                f"state={row['state_before']}→{row['state_after']}"
            )

    csv_path = REPO_ROOT / args.csv
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fields = [
        "session_date", "time", "timestamp", "close", "events",
        "rsi9", "ema3", "wma21",
        "rsi_above_50", "rsi_above_wma", "ema_above_wma",
        "rsi_slope_up", "ema_slope_up", "wma_slope_up",
        "state_before", "state_after", "strong_active",
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
