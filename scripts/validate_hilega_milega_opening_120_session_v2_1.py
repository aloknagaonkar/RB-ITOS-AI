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

MODEL = "HILEGA_MILEGA_OPENING_120_SESSION_V2_1"
DEFAULT_UNDERLYING = "NSE_INDEX|Nifty 50"


def opening_status(r15, e15, w15, r20, w20, r25, w25):
    full_0915 = (
        r15 > 50.0
        and e15 > 50.0
        and w15 > 50.0
        and r15 > e15 > w15
    )
    if not full_0915:
        return "NO_OPENING_ALIGNMENT"

    if r20 <= w20:
        return "OPENING_REJECTED_0920"

    if r25 <= w25:
        return "OPENING_REJECTED_0925"

    return "OPENING_BULLISH_CONFIRMED"


def gap_context(prev_close, open_0915, close_0920, close_0925):
    gap_points = open_0915 - prev_close
    gap_pct = (gap_points / prev_close * 100.0) if prev_close else 0.0

    def retained(close_now):
        retained_points = close_now - prev_close
        retained_pct = (
            retained_points / gap_points * 100.0
            if gap_points != 0
            else 0.0
        )
        return retained_points, retained_pct, 100.0 - retained_pct

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
    ap.add_argument("--end-date", default="2026-09-21")
    ap.add_argument("--trading-sessions", type=int, default=120)
    ap.add_argument("--calendar-lookback-days", type=int, default=190)
    ap.add_argument("--intraday-date", default="2026-09-21")
    ap.add_argument("--underlying", default=DEFAULT_UNDERLYING)
    ap.add_argument(
        "--csv",
        default="data/historical-evidence/branch-c-opening-120-session-v2-1.csv",
    )
    args = ap.parse_args()

    end_date = date.fromisoformat(args.end_date)
    intraday_date = date.fromisoformat(args.intraday_date)
    fetch_start = end_date - timedelta(days=args.calendar_lookback_days)

    load_dotenv(REPO_ROOT / ".env")
    token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        raise SystemExit("UPSTOX_ACCESS_TOKEN missing")

    encoded = quote(args.underlying, safe="")
    raw = []
    available = []

    with httpx.Client(base_url="https://api.upstox.com", timeout=30) as client:
        d = fetch_start
        while d <= end_date:
            ds = d.isoformat()
            try:
                intraday = d == intraday_date
                candles = _fetch(client, token, encoded, ds, intraday=intraday)
                print(f"{'intraday' if intraday else 'fetch'} {ds}: candles={len(candles)}")
                if candles:
                    available.append(ds)
                raw.extend(candles)
            except Exception as exc:
                print(f"fetch {ds}: ERROR {exc}")
            d += timedelta(days=1)

    sessions = sorted(set(available))[-args.trading_sessions:]
    if len(sessions) < args.trading_sessions:
        print(
            f"WARNING requested={args.trading_sessions} "
            f"available={len(sessions)} within lookback={args.calendar_lookback_days} calendar days"
        )

    bars = make_5m(parse_1m(raw))
    closes = [b["close"] for b in bars]
    rsi9 = pine_rsi(closes, 9)
    ema3 = ema(rsi9, 3)
    wma21 = wma(rsi9, 21)

    by_date = {}
    for i, b in enumerate(bars):
        by_date.setdefault(b["start"].date().isoformat(), []).append((i, b))

    rows = []
    counts = {
        "sessions_tested": len(sessions),
        "opening_alignment": 0,
        "opening_holding_0920": 0,
        "opening_rejected_0920": 0,
        "opening_rejected_0925": 0,
        "opening_confirmed_0925": 0,
    }

    print("\n=== BRANCH C OPENING 120-SESSION ROBUSTNESS V2.1 ===")
    print(f"sessions={len(sessions)} first={sessions[0] if sessions else 'NA'} last={sessions[-1] if sessions else 'NA'}\n")

    for ds in sessions:
        session = by_date.get(ds, [])
        if not session:
            continue

        previous_dates = sorted(d for d in by_date if d < ds and by_date[d])
        if not previous_dates:
            continue

        prev_ds = previous_dates[-1]
        prev_close = float(by_date[prev_ds][-1][1]["close"])

        time_map = {b["start"].strftime("%H:%M"): (i, b) for i, b in session}
        if not all(t in time_map for t in ("09:15", "09:20", "09:25")):
            continue

        i15, b15 = time_map["09:15"]
        i20, b20 = time_map["09:20"]
        i25, b25 = time_map["09:25"]

        vals = (
            rsi9[i15], ema3[i15], wma21[i15],
            rsi9[i20], ema3[i20], wma21[i20],
            rsi9[i25], ema3[i25], wma21[i25],
        )
        if any(v is None for v in vals):
            continue

        r15, e15, w15, r20, e20, w20, r25, e25, w25 = map(float, vals)

        status = opening_status(r15, e15, w15, r20, w20, r25, w25)
        if status == "NO_OPENING_ALIGNMENT":
            continue

        counts["opening_alignment"] += 1
        if r20 > w20:
            counts["opening_holding_0920"] += 1

        if status == "OPENING_REJECTED_0920":
            counts["opening_rejected_0920"] += 1
        elif status == "OPENING_REJECTED_0925":
            counts["opening_rejected_0925"] += 1
        elif status == "OPENING_BULLISH_CONFIRMED":
            counts["opening_confirmed_0925"] += 1

        gc = gap_context(
            prev_close,
            float(b15["open"]),
            float(b20["close"]),
            float(b25["close"]),
        )

        row = {
            "session_date": ds,
            "previous_session_date": prev_ds,
            "status": status,
            "previous_close": prev_close,
            "open_0915": float(b15["open"]),
            "close_0915": float(b15["close"]),
            "close_0920": float(b20["close"]),
            "close_0925": float(b25["close"]),
            **gc,
            "rsi_0915": r15,
            "ema_0915": e15,
            "wma_0915": w15,
            "rsi_wma_gap_0915": r15 - w15,
            "ema_wma_gap_0915": e15 - w15,
            "rsi_0920": r20,
            "ema_0920": e20,
            "wma_0920": w20,
            "rsi_wma_gap_0920": r20 - w20,
            "ema_wma_gap_0920": e20 - w20,
            "rsi_0925": r25,
            "ema_0925": e25,
            "wma_0925": w25,
            "rsi_wma_gap_0925": r25 - w25,
            "ema_wma_gap_0925": e25 - w25,
        }
        rows.append(row)

        print(
            f"{ds} {status} "
            f"gap={gc['gap_pct']:+.3f}% "
            f"ret20={gc['gap_retained_pct_0920']:.1f}% "
            f"ret25={gc['gap_retained_pct_0925']:.1f}% "
            f"RSI-WMA 09:15={row['rsi_wma_gap_0915']:+.2f} "
            f"09:20={row['rsi_wma_gap_0920']:+.2f} "
            f"09:25={row['rsi_wma_gap_0925']:+.2f}"
        )

    csv_path = REPO_ROOT / args.csv
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    print("\n=== SUMMARY ===")
    for k, v in counts.items():
        print(f"{k}={v}")

    if counts["opening_alignment"]:
        align = counts["opening_alignment"]
        print(
            f"confirmation_rate_0925="
            f"{counts['opening_confirmed_0925'] / align * 100.0:.2f}%"
        )
        print(
            f"rejection_rate_0925_or_earlier="
            f"{(counts['opening_rejected_0920'] + counts['opening_rejected_0925']) / align * 100.0:.2f}%"
        )

    print(f"CSV={csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
