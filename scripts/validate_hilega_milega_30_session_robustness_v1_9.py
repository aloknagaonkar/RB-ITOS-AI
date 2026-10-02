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

MODEL = "HILEGA_MILEGA_30_SESSION_ROBUSTNESS_V1_9"
DEFAULT_UNDERLYING = "NSE_INDEX|Nifty 50"


def cross_up(prev_a, prev_b, a, b):
    return prev_a <= prev_b and a > b


def cross_down(prev_a, prev_b, a, b):
    return prev_a >= prev_b and a < b


def cross_level_up(prev_v, v, level=50.0):
    return prev_v <= level and v > level


def state_name(armed, active, bullish, strong, full, weakening):
    if weakening:
        return "WEAKENING"
    if full:
        return "FULL"
    if strong:
        return "STRONG"
    if bullish:
        return "BULLISH"
    if active:
        return "ACTIVE_SETUP"
    if armed:
        return "ARMED"
    return "NEUTRAL"


def build_session_timeline(bars, rsi9, ema3, wma21, session_date):
    rows = []

    idxs = [
        i for i, b in enumerate(bars)
        if b["start"].date().isoformat() == session_date
    ]
    if not idxs:
        return rows

    armed = active = bullish = strong = full = False
    weakening = False
    weakening_index = None
    opening_pending = False
    opening_index = None

    first_i = idxs[0]

    # Opening context: do not treat overnight transitions as ordinary intraday crossovers.
    r0, e0, w0 = rsi9[first_i], ema3[first_i], wma21[first_i]
    if None not in (r0, e0, w0):
        r0, e0, w0 = map(float, (r0, e0, w0))
        opening_full = (
            r0 > 50.0 and e0 > 50.0 and w0 > 50.0 and r0 > e0 > w0
        )
        if opening_full:
            opening_pending = True
            opening_index = first_i
            rows.append({
                "session_date": session_date,
                "time": bars[first_i]["start"].strftime("%H:%M"),
                "timestamp": bars[first_i]["start"].isoformat(),
                "close": float(bars[first_i]["close"]),
                "events": "OPENING_ALIGNMENT",
                "rsi9": r0, "ema3": e0, "wma21": w0,
                "rsi_above_50": r0 > 50,
                "ema_above_50": e0 > 50,
                "wma_above_50": w0 > 50,
                "rsi_above_wma": r0 > w0,
                "ema_above_wma": e0 > w0,
                "ordered_rsi_ema_wma": r0 > e0 > w0,
                "state_before": "NEUTRAL",
                "state_after": "OPENING_PENDING",
                "manual_label": "",
                "manual_notes": "",
            })

    for pos, i in enumerate(idxs):
        if i == first_i:
            continue

        vals = (rsi9[i-1], ema3[i-1], wma21[i-1], rsi9[i], ema3[i], wma21[i])
        if any(v is None for v in vals):
            continue

        rp, ep, wp, r, e, w = map(float, vals)
        t = bars[i]["start"]
        events = []
        before = state_name(armed, active, bullish, strong, full, weakening)

        # Opening candidate: only the immediately next 5m candle decides persistence.
        if opening_pending:
            if i == opening_index + 1:
                if r > w:
                    active = bullish = strong = full = True
                    events.append("OPENING_BULLISH_CONFIRMED")
                else:
                    events.append("OPENING_ALIGNMENT_FAILED")
                opening_pending = False
                opening_index = None
            else:
                # Defensive cleanup if exact next bar was missing.
                events.append("OPENING_ALIGNMENT_UNRESOLVED")
                opening_pending = False
                opening_index = None

        rsi_up_ema = cross_up(rp, ep, r, e)
        rsi_up_wma = cross_up(rp, wp, r, w)
        rsi_down_wma = cross_down(rp, wp, r, w)
        ema_up_wma = cross_up(ep, wp, e, w)

        rsi_up_50 = cross_level_up(rp, r)
        ema_up_50 = cross_level_up(ep, e)
        wma_up_50 = cross_level_up(wp, w)

        # Two-stage invalidation.
        if weakening:
            if r < w:
                events.append("BULLISH_END_CONFIRMED")
                armed = active = bullish = strong = full = False
                weakening = False
                weakening_index = None
            else:
                events.append("WEAKENING_RECOVERY / CONTINUATION")
                weakening = False
                weakening_index = None

        # First RSI↓WMA only enters weakening, not immediate invalidation.
        if not weakening and (active or bullish or strong or full) and rsi_down_wma:
            weakening = True
            weakening_index = i
            events.append("RSI↓WMA / WEAKENING")

        # Only build new setup if not in an established/weakening structure.
        if not (active or bullish or strong or full or weakening):
            if rsi_up_ema:
                armed = True
                events.append("RSI↑EMA / ARMED")
        elif rsi_up_ema:
            events.append("RSI↑EMA / CONTINUATION")

        if armed and rsi_up_wma and not weakening:
            active = True
            armed = False
            events.append("RSI↑WMA / ACTIVE_SETUP")
        elif (active or bullish or strong or full) and rsi_up_wma:
            events.append("RSI↑WMA / CONTINUATION")

        if ema_up_wma:
            events.append("EMA3↑WMA")
        if rsi_up_50:
            events.append("RSI↑50")
        if ema_up_50:
            events.append("EMA3↑50")
        if wma_up_50:
            events.append("WMA21↑50")

        # Normal intraday progression.
        if active and not bullish and r > w and r > 50.0:
            bullish = True
            events.append("BULLISH")

        if active and bullish and not strong and r > w and e > w and r > 50.0:
            strong = True
            events.append("STRONG_BULLISH")

        if strong and not full and r > 50.0 and e > 50.0 and w > 50.0 and r > e > w:
            full = True
            events.append("FULL_BULLISH_ALIGNMENT")

        after = state_name(armed, active, bullish, strong, full, weakening)

        if events:
            rows.append({
                "session_date": session_date,
                "time": t.strftime("%H:%M"),
                "timestamp": t.isoformat(),
                "close": float(bars[i]["close"]),
                "events": " | ".join(events),
                "rsi9": r, "ema3": e, "wma21": w,
                "rsi_above_50": r > 50,
                "ema_above_50": e > 50,
                "wma_above_50": w > 50,
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
    ap.add_argument("--end-date", default="2026-09-21")
    ap.add_argument("--trading-sessions", type=int, default=30)
    ap.add_argument("--calendar-lookback-days", type=int, default=50)
    ap.add_argument("--intraday-date", default="2026-09-21")
    ap.add_argument("--underlying", default=DEFAULT_UNDERLYING)
    ap.add_argument(
        "--csv",
        default="data/historical-evidence/branch-c-30-session-robustness-v1-9.csv",
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

    all_rows = []
    summary = {
        "opening_candidates": 0,
        "opening_confirmed": 0,
        "opening_failed": 0,
        "weakening_events": 0,
        "weakening_recoveries": 0,
        "bullish_end_confirmed": 0,
        "active_setups": 0,
        "bullish": 0,
        "strong": 0,
        "full": 0,
    }

    print("\n=== BRANCH C 30-SESSION ROBUSTNESS V1.9 ===")
    print(f"sessions={len(sessions)} first={sessions[0] if sessions else 'NA'} last={sessions[-1] if sessions else 'NA'}\n")

    for ds in sessions:
        rows = build_session_timeline(bars, rsi9, ema3, wma21, ds)
        all_rows.extend(rows)

        for row in rows:
            ev = row["events"]
            summary["opening_candidates"] += "OPENING_ALIGNMENT" == ev
            summary["opening_confirmed"] += "OPENING_BULLISH_CONFIRMED" in ev
            summary["opening_failed"] += "OPENING_ALIGNMENT_FAILED" in ev
            summary["weakening_events"] += "RSI↓WMA / WEAKENING" in ev
            summary["weakening_recoveries"] += "WEAKENING_RECOVERY" in ev
            summary["bullish_end_confirmed"] += "BULLISH_END_CONFIRMED" in ev
            summary["active_setups"] += "ACTIVE_SETUP" in ev
            summary["bullish"] += "BULLISH" in ev and "STRONG_BULLISH" not in ev and "OPENING_BULLISH" not in ev
            summary["strong"] += "STRONG_BULLISH" in ev
            summary["full"] += "FULL_BULLISH_ALIGNMENT" in ev

        print(f"--- {ds} ---")
        for row in rows:
            interesting = any(k in row["events"] for k in (
                "OPENING_", "ACTIVE_SETUP", "BULLISH", "WEAKENING", "BULLISH_END"
            ))
            if interesting:
                print(
                    f"{row['time']} {row['events']} "
                    f"RSI={row['rsi9']:.2f} EMA={row['ema3']:.2f} WMA={row['wma21']:.2f} "
                    f"state={row['state_before']}→{row['state_after']}"
                )

    csv_path = REPO_ROOT / args.csv
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "session_date", "time", "timestamp", "close", "events",
        "rsi9", "ema3", "wma21",
        "rsi_above_50", "ema_above_50", "wma_above_50",
        "rsi_above_wma", "ema_above_wma", "ordered_rsi_ema_wma",
        "state_before", "state_after", "manual_label", "manual_notes",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)

    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        print(f"{k}={v}")
    print(f"CSV={csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
