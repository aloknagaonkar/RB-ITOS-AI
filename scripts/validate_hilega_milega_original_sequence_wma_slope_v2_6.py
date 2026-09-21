from __future__ import annotations

"""
Branch C V2.6 — Original bullish sequence + upward WMA21 slope audit.

This deliberately returns to the broader pre-"same-candle crossover" sequence:

    RSI↑EMA3
        -> ARMED
    RSI↑WMA21
        -> ACTIVE_SETUP
    ACTIVE_SETUP and RSI > WMA21 and RSI > 50
        -> bullish candidate

NEW TEST CONDITION ONLY:
    At the candle where BULLISH actually begins:
        WMA21[t] > WMA21[t-1]

No minimum WMA slope magnitude is imposed.
EMA3 does NOT have to freshly cross WMA21 on the bullish-start candle.
If EMA3 > WMA21 at bullish start, the signal is STRONG immediately.
If EMA3 moves above WMA21 later, STRONG can occur later.

Two-stage invalidation is retained:
    first RSI↓WMA -> WEAKENING
    next candle still RSI<WMA -> BULLISH_END
    recovery RSI>WMA -> CONTINUATION
"""

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


def cross_up(prev_a: float, prev_b: float, a: float, b: float) -> bool:
    return prev_a <= prev_b and a > b


def cross_down(prev_a: float, prev_b: float, a: float, b: float) -> bool:
    return prev_a >= prev_b and a < b


def wma_slope_up(prev_wma: float, wma_now: float) -> bool:
    """Exact upward slope test. No arbitrary minimum threshold."""
    return wma_now > prev_wma


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
        return [], []

    accepted = []
    rejected_slope = []

    armed = False
    active_setup = False
    bullish = False
    weakening = False
    current = None

    for pos, i in enumerate(idxs):
        if i == idxs[0]:
            continue

        vals = (rsi9[i-1], ema3[i-1], wma21[i-1], rsi9[i], ema3[i], wma21[i])
        if any(v is None for v in vals):
            continue

        rp, ep, wp, r, e, w = map(float, vals)
        close = float(bars[i]["close"])
        t = bars[i]["start"].strftime("%H:%M")

        # Resolve a prior weakening state first.
        if weakening:
            if r < w:
                if current is not None:
                    current["bullish_end_time"] = t
                    current["bullish_end_close"] = close
                    current["move_to_end_points"] = close - current["signal_close"]
                armed = False
                active_setup = False
                bullish = False
                weakening = False
                current = None
            else:
                # Recovery above WMA: continuation of existing regime.
                weakening = False

        # If regime still exists, detect first RSI↓WMA as WEAKENING.
        if (active_setup or bullish) and not weakening and cross_down(rp, wp, r, w):
            weakening = True

        # Do not create a new setup while an accepted bullish regime remains active.
        if bullish or weakening:
            continue

        # Pre-crossover sequence: RSI↑EMA arms.
        if not active_setup and cross_up(rp, ep, r, e):
            armed = True

        # Armed setup progresses when RSI crosses WMA.
        if armed and cross_up(rp, wp, r, w):
            active_setup = True
            armed = False

        # Important historical behavior:
        # if RSI↑WMA happened below 50, ACTIVE_SETUP survives and can become
        # BULLISH later when RSI > 50 while RSI remains > WMA.
        candidate_bullish = active_setup and r > w and r > 50.0

        if candidate_bullish:
            row = {
                "session_date": session_date,
                "signal_time": t,
                "signal_close": close,
                "prev_rsi9": rp,
                "prev_ema3": ep,
                "prev_wma21": wp,
                "rsi9": r,
                "ema3": e,
                "wma21": w,
                "wma_slope": w - wp,
                "wma_slope_up": wma_slope_up(wp, w),
                "rsi_minus_ema3": r - e,
                "rsi_minus_wma21": r - w,
                "ema3_minus_wma21": e - w,
                "strong_at_start": e > w,
                "full_at_start": (
                    r > 50.0
                    and e > 50.0
                    and w > 50.0
                    and r > e > w
                ),
                "bullish_end_time": "",
                "bullish_end_close": "",
                "move_to_end_points": "",
            }

            if wma_slope_up(wp, w):
                bullish = True
                current = row
                accepted.append(row)
            else:
                # Diagnostic rejection only. The sequence is reset here because
                # this audit is testing "WMA must slope upward at bullish start".
                rejected_slope.append(row)
                active_setup = False
                armed = False

    return accepted, rejected_slope


def _print_rows(title, rows):
    print(f"\n=== {title} ===\n")
    print(
        f"{'DATE':<12}{'TIME':<7}{'CLOSE':>10}"
        f"{'RSI9':>10}{'EMA3':>10}{'WMA21':>10}"
        f"{'WMAΔ':>10}{'STRONG':>9}{'END':>8}{'POINTS':>10}"
    )
    print("-" * 96)

    for r in rows:
        pts = r["move_to_end_points"]
        pts_s = f"{float(pts):+.2f}" if pts != "" else "NA"
        print(
            f"{r['session_date']:<12}{r['signal_time']:<7}{r['signal_close']:>10.2f}"
            f"{r['rsi9']:>10.4f}{r['ema3']:>10.4f}{r['wma21']:>10.4f}"
            f"{r['wma_slope']:>+10.4f}{str(r['strong_at_start']):>9}"
            f"{(r['bullish_end_time'] or 'NA'):>8}{pts_s:>10}"
        )


def main():
    ap = argparse.ArgumentParser(
        description="Branch C V2.6 original sequence with WMA21 upward-slope condition"
    )
    ap.add_argument("--end-date", default="2026-09-21")
    ap.add_argument("--trading-sessions", type=int, default=120)
    ap.add_argument("--calendar-lookback-days", type=int, default=190)
    ap.add_argument("--intraday-date", default="2026-09-21")
    ap.add_argument("--underlying", default=DEFAULT_UNDERLYING)
    ap.add_argument(
        "--csv",
        default="data/historical-evidence/branch-c-original-sequence-wma-up-v2-6.csv",
    )
    ap.add_argument(
        "--rejected-csv",
        default="data/historical-evidence/branch-c-original-sequence-wma-not-up-v2-6.csv",
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

    accepted = []
    rejected = []
    for ds in sessions:
        a, r = scan_session(bars, rsi9, ema3, wma21, ds)
        accepted.extend(a)
        rejected.extend(r)

    _print_rows("ACCEPTED: ORIGINAL SEQUENCE + WMA21 SLOPE UP", accepted)

    completed = [float(r["move_to_end_points"]) for r in accepted if r["move_to_end_points"] != ""]

    print("\n=== SUMMARY ===")
    print(f"sessions_tested = {len(sessions)}")
    print(f"accepted_bullish_starts = {len(accepted)}")
    print(f"rejected_because_wma_not_up = {len(rejected)}")
    print(f"completed_accepted = {len(completed)}")
    if completed:
        positives = sum(v > 0 for v in completed)
        print(f"positive_events = {positives}")
        print(f"positive_rate = {positives / len(completed) * 100:.2f}%")
        print(f"net_points_to_end = {sum(completed):+.2f}")
        print(f"average_points_to_end = {sum(completed) / len(completed):+.2f}")
        print(f"best_points_to_end = {max(completed):+.2f}")
        print(f"worst_points_to_end = {min(completed):+.2f}")

    out = REPO_ROOT / args.csv
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = list(accepted[0].keys()) if accepted else []
    if fields:
        with out.open("w", newline="", encoding="utf-8") as f:
            wtr = csv.DictWriter(f, fieldnames=fields)
            wtr.writeheader()
            wtr.writerows(accepted)

    rout = REPO_ROOT / args.rejected_csv
    if rejected:
        with rout.open("w", newline="", encoding="utf-8") as f:
            wtr = csv.DictWriter(f, fieldnames=list(rejected[0].keys()))
            wtr.writeheader()
            wtr.writerows(rejected)

    print(f"\nACCEPTED_CSV={out}")
    print(f"REJECTED_CSV={rout}")


if __name__ == "__main__":
    main()
