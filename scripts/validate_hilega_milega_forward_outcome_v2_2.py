from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
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

MODEL = "HILEGA_MILEGA_FORWARD_OUTCOME_AUDIT_V2_2"
DEFAULT_UNDERLYING = "NSE_INDEX|Nifty 50"
HORIZONS = (5, 10, 15, 30, 60)


def cross_up(prev_a, prev_b, a, b):
    return prev_a <= prev_b and a > b


def cross_down(prev_a, prev_b, a, b):
    return prev_a >= prev_b and a < b


def cross_level_up(prev_v, v, level=50.0):
    return prev_v <= level and v > level


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


def signal_events_for_session(bars, rsi9, ema3, wma21, session_date):
    idxs = [i for i, b in enumerate(bars) if b["start"].date().isoformat() == session_date]
    if not idxs:
        return [], []

    events = []
    end_events = []

    # Opening path
    time_to_idx = {bars[i]["start"].strftime("%H:%M"): i for i in idxs}
    if all(t in time_to_idx for t in ("09:15", "09:20", "09:25")):
        i15 = time_to_idx["09:15"]
        i20 = time_to_idx["09:20"]
        i25 = time_to_idx["09:25"]
        vals = (
            rsi9[i15], ema3[i15], wma21[i15],
            rsi9[i20], wma21[i20],
            rsi9[i25], wma21[i25],
        )
        if all(v is not None for v in vals):
            status = opening_status(*map(float, vals))
            if status == "OPENING_BULLISH_CONFIRMED":
                events.append({
                    "signal_type": "OPENING_BULLISH_CONFIRMED",
                    "index": i25,
                    "session_date": session_date,
                })

    # Shared normal path + shared two-stage invalidation
    armed = False
    active = False
    bullish = False
    strong = False
    full = False
    weakening = False

    # If opening confirmed, seed regime active at 09:25 as FULL.
    opening_confirmed_index = None
    for e in events:
        if e["signal_type"] == "OPENING_BULLISH_CONFIRMED":
            opening_confirmed_index = e["index"]
            break

    for i in idxs:
        if i == idxs[0]:
            continue
        if opening_confirmed_index is not None and i < opening_confirmed_index:
            continue
        if opening_confirmed_index is not None and i == opening_confirmed_index:
            active = bullish = strong = full = True
            continue

        vals = (rsi9[i-1], ema3[i-1], wma21[i-1], rsi9[i], ema3[i], wma21[i])
        if any(v is None for v in vals):
            continue
        rp, ep, wp, r, e, w = map(float, vals)

        # Resolve weakening first.
        if weakening:
            if r < w:
                end_events.append({
                    "session_date": session_date,
                    "index": i,
                    "event": "BULLISH_END_CONFIRMED",
                })
                armed = active = bullish = strong = full = False
                weakening = False
            else:
                weakening = False

        # Enter weakening on first RSI down WMA while regime exists.
        rsi_down_wma = cross_down(rp, wp, r, w)
        if not weakening and (active or bullish or strong or full) and rsi_down_wma:
            weakening = True

        rsi_up_ema = cross_up(rp, ep, r, e)
        rsi_up_wma = cross_up(rp, wp, r, w)
        ema_up_wma = cross_up(ep, wp, e, w)

        # If regime already active, normal-path crossovers are continuation only.
        regime_active = active or bullish or strong or full or weakening
        if not regime_active and rsi_up_ema:
            armed = True

        if armed and rsi_up_wma and not weakening:
            active = True
            armed = False

        # Emit only first transition into each state for this regime.
        if active and not bullish and r > w and r > 50.0:
            bullish = True
            events.append({
                "signal_type": "INTRADAY_BULLISH",
                "index": i,
                "session_date": session_date,
            })

        if active and bullish and not strong and r > w and e > w and r > 50.0:
            strong = True
            events.append({
                "signal_type": "INTRADAY_STRONG",
                "index": i,
                "session_date": session_date,
            })

        if strong and not full and r > 50.0 and e > 50.0 and w > 50.0 and r > e > w:
            full = True
            events.append({
                "signal_type": "INTRADAY_FULL",
                "index": i,
                "session_date": session_date,
            })

    return events, end_events


def first_end_after(signal_index, end_events):
    candidates = [e["index"] for e in end_events if e["index"] > signal_index]
    return min(candidates) if candidates else None


def outcome_for_signal(bars, signal_index, end_index=None):
    entry = float(bars[signal_index]["close"])
    session_date = bars[signal_index]["start"].date()

    session_indices = [
        i for i in range(signal_index, len(bars))
        if bars[i]["start"].date() == session_date
    ]
    session_last = max(session_indices) if session_indices else signal_index

    out = {
        "entry_close": entry,
        "entry_time": bars[signal_index]["start"].strftime("%H:%M"),
    }

    for minutes in HORIZONS:
        steps = minutes // 5
        target = signal_index + steps
        if target <= session_last and bars[target]["start"].date() == session_date:
            px = float(bars[target]["close"])
            out[f"close_{minutes}m"] = px
            out[f"move_{minutes}m_points"] = px - entry
            out[f"move_{minutes}m_pct"] = (px - entry) / entry * 100.0
        else:
            out[f"close_{minutes}m"] = ""
            out[f"move_{minutes}m_points"] = ""
            out[f"move_{minutes}m_pct"] = ""

    audit_end = end_index if end_index is not None else session_last
    audit_end = min(audit_end, session_last)
    window = bars[signal_index:audit_end + 1]

    highs = [float(b["high"]) for b in window]
    lows = [float(b["low"]) for b in window]

    max_high = max(highs) if highs else entry
    min_low = min(lows) if lows else entry

    mfe = max_high - entry
    mae = min_low - entry

    mfe_idx = signal_index + highs.index(max_high) if highs else signal_index
    mae_idx = signal_index + lows.index(min_low) if lows else signal_index

    out.update({
        "mfe_points_to_end": mfe,
        "mae_points_to_end": mae,
        "mfe_pct_to_end": mfe / entry * 100.0,
        "mae_pct_to_end": mae / entry * 100.0,
        "time_to_mfe_min": (mfe_idx - signal_index) * 5,
        "time_to_mae_min": (mae_idx - signal_index) * 5,
        "bullish_end_time": bars[end_index]["start"].strftime("%H:%M") if end_index is not None else "",
        "move_to_end_points": (
            float(bars[end_index]["close"]) - entry if end_index is not None else ""
        ),
    })

    return out


def summarize(rows):
    signal_types = [
        "OPENING_BULLISH_CONFIRMED",
        "INTRADAY_BULLISH",
        "INTRADAY_STRONG",
        "INTRADAY_FULL",
    ]
    summary = []
    for st in signal_types:
        subset = [r for r in rows if r["signal_type"] == st]
        if not subset:
            continue
        item = {"signal_type": st, "count": len(subset)}
        for minutes in HORIZONS:
            vals = [
                float(r[f"move_{minutes}m_points"])
                for r in subset
                if r[f"move_{minutes}m_points"] != ""
            ]
            if vals:
                item[f"avg_move_{minutes}m"] = sum(vals) / len(vals)
                item[f"positive_rate_{minutes}m"] = sum(v > 0 for v in vals) / len(vals) * 100.0
            else:
                item[f"avg_move_{minutes}m"] = None
                item[f"positive_rate_{minutes}m"] = None

        mfes = [float(r["mfe_points_to_end"]) for r in subset]
        maes = [float(r["mae_points_to_end"]) for r in subset]
        item["avg_mfe_to_end"] = sum(mfes) / len(mfes)
        item["avg_mae_to_end"] = sum(maes) / len(maes)
        summary.append(item)
    return summary


def main():
    ap = argparse.ArgumentParser(description=MODEL)
    ap.add_argument("--end-date", default="2026-09-21")
    ap.add_argument("--trading-sessions", type=int, default=120)
    ap.add_argument("--calendar-lookback-days", type=int, default=190)
    ap.add_argument("--intraday-date", default="2026-09-21")
    ap.add_argument("--underlying", default=DEFAULT_UNDERLYING)
    ap.add_argument(
        "--csv",
        default="data/historical-evidence/branch-c-forward-outcome-v2-2.csv",
    )
    ap.add_argument(
        "--summary-csv",
        default="data/historical-evidence/branch-c-forward-outcome-summary-v2-2.csv",
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
    bars = make_5m(parse_1m(raw))
    closes = [b["close"] for b in bars]
    rsi9 = pine_rsi(closes, 9)
    ema3 = ema(rsi9, 3)
    wma21 = wma(rsi9, 21)

    rows = []

    print("\n=== BRANCH C FORWARD OUTCOME AUDIT V2.2 ===")
    print(f"sessions={len(sessions)} first={sessions[0] if sessions else 'NA'} last={sessions[-1] if sessions else 'NA'}\n")

    for ds in sessions:
        events, ends = signal_events_for_session(bars, rsi9, ema3, wma21, ds)
        for ev in events:
            end_index = first_end_after(ev["index"], ends)
            o = outcome_for_signal(bars, ev["index"], end_index=end_index)
            row = {
                "session_date": ds,
                "signal_type": ev["signal_type"],
                "signal_timestamp": bars[ev["index"]]["start"].isoformat(),
                **o,
            }
            rows.append(row)

    csv_path = REPO_ROOT / args.csv
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    summary = summarize(rows)
    summary_path = REPO_ROOT / args.summary_csv
    if summary:
        fields = list(summary[0].keys())
        with summary_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(summary)

    print("=== SUMMARY ===")
    for item in summary:
        print(f"\n{item['signal_type']} count={item['count']}")
        for minutes in HORIZONS:
            avg = item.get(f"avg_move_{minutes}m")
            pos = item.get(f"positive_rate_{minutes}m")
            if avg is not None:
                print(f"  +{minutes}m avg_move={avg:+.2f} pts positive_rate={pos:.1f}%")
        print(
            f"  avg_MFE_to_end={item['avg_mfe_to_end']:+.2f} "
            f"avg_MAE_to_end={item['avg_mae_to_end']:+.2f}"
        )

    print(f"\nDETAIL_CSV={csv_path}")
    print(f"SUMMARY_CSV={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
