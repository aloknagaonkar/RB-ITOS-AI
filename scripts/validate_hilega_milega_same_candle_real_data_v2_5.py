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


def cross_up(prev_a, prev_b, a, b):
    return prev_a <= prev_b and a > b


def cross_down(prev_a, prev_b, a, b):
    return prev_a >= prev_b and a < b


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


def scan_session(bars, rsi9, ema3, wma21, session_date):
    idxs = [i for i, b in enumerate(bars) if b["start"].date().isoformat() == session_date]
    if not idxs:
        return []

    events = []
    armed = False
    active = False
    bullish = False
    weakening = False
    current_start = None

    for i in idxs:
        if i == idxs[0]:
            continue

        vals = (rsi9[i-1], ema3[i-1], wma21[i-1], rsi9[i], ema3[i], wma21[i])
        if any(v is None for v in vals):
            continue

        rp, ep, wp, r, e, w = map(float, vals)

        # resolve weakening
        if weakening:
            if r < w:
                if current_start is not None:
                    # complete all current regime events with this bullish end
                    for ev in events:
                        if ev.get("bullish_end_index") is None and ev["regime_id"] == current_start:
                            ev["bullish_end_index"] = i
                            ev["bullish_end_time"] = bars[i]["start"].strftime("%H:%M")
                            ev["bullish_end_close"] = float(bars[i]["close"])
                            ev["move_to_end_points"] = float(bars[i]["close"]) - ev["signal_close"]
                armed = active = bullish = weakening = False
                current_start = None
            else:
                weakening = False

        # first RSI down WMA -> weakening
        if (active or bullish) and not weakening and cross_down(rp, wp, r, w):
            weakening = True

        rsi_up_ema = cross_up(rp, ep, r, e)
        rsi_up_wma = cross_up(rp, wp, r, w)
        ema_up_wma = cross_up(ep, wp, e, w)

        regime_active = active or bullish or weakening

        if not regime_active and rsi_up_ema:
            armed = True

        if armed and rsi_up_wma and not weakening:
            active = True
            armed = False
            current_start = f"{session_date}-{bars[i]['start'].strftime('%H:%M')}"

            if r > 50.0:
                bullish = True

            # This is the key V2.5 classification:
            # RSI↑WMA and EMA3↑WMA on the SAME candle.
            if ema_up_wma and r > 50.0 and e > w:
                events.append({
                    "session_date": session_date,
                    "signal_time": bars[i]["start"].strftime("%H:%M"),
                    "signal_close": float(bars[i]["close"]),
                    "prev_rsi9": rp,
                    "prev_ema3": ep,
                    "prev_wma21": wp,
                    "rsi9": r,
                    "ema3": e,
                    "wma21": w,
                    "rsi_minus_ema3": r - e,
                    "rsi_minus_wma21": r - w,
                    "ema3_minus_wma21": e - w,
                    "same_candle_rsi_up_wma": True,
                    "same_candle_ema_up_wma": True,
                    "bullish": True,
                    "strong_bullish": True,
                    "regime_id": current_start,
                    "bullish_end_index": None,
                    "bullish_end_time": "",
                    "bullish_end_close": "",
                    "move_to_end_points": "",
                })

    return events


def main():
    ap = argparse.ArgumentParser(
        description="Branch C V2.5 real-data audit for same-candle RSI↑WMA + EMA3↑WMA"
    )
    ap.add_argument("--end-date", default="2026-09-21")
    ap.add_argument("--trading-sessions", type=int, default=120)
    ap.add_argument("--calendar-lookback-days", type=int, default=190)
    ap.add_argument("--intraday-date", default="2026-09-21")
    ap.add_argument("--underlying", default=DEFAULT_UNDERLYING)
    ap.add_argument(
        "--csv",
        default="data/historical-evidence/branch-c-same-candle-real-data-v2-5.csv",
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
            candles = _fetch(
                client,
                token,
                encoded,
                ds,
                intraday=(d == intraday_date),
            )
            print(f"fetch {ds}: candles={len(candles)}")
            if candles:
                available.append(ds)
            raw.extend(candles)
            d += timedelta(days=1)

    sessions = sorted(set(available))[-args.trading_sessions:]

    bars = make_5m(parse_1m(raw))
    closes = [b["close"] for b in bars]
    rsi9 = pine_rsi(closes, 9)
    ema3 = ema(rsi9, 3)
    wma21 = wma(rsi9, 21)

    rows = []
    for ds in sessions:
        rows.extend(scan_session(bars, rsi9, ema3, wma21, ds))

    print("\n=== SAME-CANDLE REAL-DATA EVENTS V2.5 ===\n")
    print(
        f"{'DATE':<12}{'TIME':<7}{'CLOSE':>10}"
        f"{'RSI9':>10}{'EMA3':>10}{'WMA21':>10}"
        f"{'R-W':>10}{'E-W':>10}{'END':>8}{'POINTS':>10}"
    )
    print("-" * 97)

    completed = []
    for r in rows:
        pts = r["move_to_end_points"]
        pts_s = f"{pts:+.2f}" if pts != "" else "NA"
        print(
            f"{r['session_date']:<12}{r['signal_time']:<7}{r['signal_close']:>10.2f}"
            f"{r['rsi9']:>10.4f}{r['ema3']:>10.4f}{r['wma21']:>10.4f}"
            f"{r['rsi_minus_wma21']:>10.4f}{r['ema3_minus_wma21']:>10.4f}"
            f"{r['bullish_end_time'] or 'NA':>8}{pts_s:>10}"
        )
        if pts != "":
            completed.append(float(pts))

    print("\n=== SUMMARY ===")
    print(f"sessions_tested = {len(sessions)}")
    print(f"same_candle_events = {len(rows)}")
    print(f"completed_events = {len(completed)}")

    if completed:
        print(f"positive_events = {sum(v > 0 for v in completed)}")
        print(f"positive_rate = {sum(v > 0 for v in completed) / len(completed) * 100:.2f}%")
        print(f"average_points_to_end = {sum(completed) / len(completed):+.2f}")
        print(f"best_points_to_end = {max(completed):+.2f}")
        print(f"worst_points_to_end = {min(completed):+.2f}")

    out = REPO_ROOT / args.csv
    out.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    print(f"\nCSV={out}")


if __name__ == "__main__":
    main()
