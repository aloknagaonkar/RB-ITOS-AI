from __future__ import annotations

"""
DAY_TREND_CLASSIFICATION_90D_V1

Price-only day classification for the latest N sessions.

Research design:
- Input: underlying OHLC only (TRAIN + OOS_A-D).
- 09:20 onward; 09:15-09:19 excluded.
- 5-minute close path for trend efficiency.
- Full 1-minute highs/lows for session range.
- No OI/PCR/option data used in classification.
- No hand-tuned threshold.
- Rank sessions by a signed trend score and select the strongest top/bottom fraction.

trend_efficiency = abs(last_close - 09:20_close) / sum(abs(5m_close_change))
range_displacement = abs(last_close - 09:20_close) / (day_high - day_low)
trend_score = sign(net_points) * trend_efficiency * range_displacement

Top fraction among positive-score sessions = BULLISH_TREND_DAY
Bottom fraction among negative-score sessions = BEARISH_TREND_DAY
All remaining sessions = MIXED_DAY
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

VERSION = "DAY_TREND_CLASSIFICATION_90D_V1"
FORBIDDEN = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}


def f(v):
    if v in ("", None):
        return None
    try:
        return float(v)
    except Exception:
        return None


def dt(v):
    if not v:
        return None
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as h:
        return list(csv.DictReader(h))


def detect(rows):
    keys = set().union(*(r.keys() for r in rows))

    def first(*xs):
        return next((x for x in xs if x in keys), None)

    c = {
        "timestamp": first("timestamp", "datetime", "time"),
        "session_date": first("session_date", "date"),
        "open": first("open"),
        "high": first("high"),
        "low": first("low"),
        "close": first("close"),
    }
    missing = [k for k, v in c.items() if v is None]
    if missing:
        raise RuntimeError("Missing underlying columns: " + ", ".join(missing))
    return c


def classify_session(block, date_s, rows, c):
    ordered = sorted(rows, key=lambda r: dt(r[c["timestamp"]]))
    active = []
    for r in ordered:
        t = dt(r[c["timestamp"]])
        if (t.hour, t.minute) < (9, 20):
            continue
        if (t.hour, t.minute) > (15, 29):
            continue
        active.append(r)

    if not active:
        return None

    first = min(active, key=lambda r: dt(r[c["timestamp"]]))
    last = max(active, key=lambda r: dt(r[c["timestamp"]]))
    first_close = f(first[c["close"]])
    last_close = f(last[c["close"]])
    if first_close is None or last_close is None:
        return None

    checkpoint_rows = []
    for r in active:
        t = dt(r[c["timestamp"]])
        if t.minute % 5 == 0:
            checkpoint_rows.append(r)

    # Ensure final 15:29 close participates even though not divisible by 5.
    if checkpoint_rows and dt(checkpoint_rows[-1][c["timestamp"]]) != dt(last[c["timestamp"]]):
        checkpoint_rows.append(last)

    closes = [f(r[c["close"]]) for r in checkpoint_rows]
    closes = [x for x in closes if x is not None]
    if len(closes) < 2:
        return None

    path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    net = last_close - first_close
    efficiency = abs(net) / path if path else 0.0

    highs = [f(r[c["high"]]) for r in active if f(r[c["high"]]) is not None]
    lows = [f(r[c["low"]]) for r in active if f(r[c["low"]]) is not None]
    day_high = max(highs)
    day_low = min(lows)
    day_range = day_high - day_low
    range_disp = abs(net) / day_range if day_range else 0.0
    close_location = (last_close - day_low) / day_range if day_range else None

    sign = 1.0 if net > 0 else -1.0 if net < 0 else 0.0
    score = sign * efficiency * range_disp

    return {
        "block": block,
        "session_date": date_s,
        "first_timestamp": dt(first[c["timestamp"]]).isoformat(),
        "last_timestamp": dt(last[c["timestamp"]]).isoformat(),
        "start_close_0920": first_close,
        "last_close": last_close,
        "net_points": net,
        "day_high": day_high,
        "day_low": day_low,
        "day_range_points": day_range,
        "trend_efficiency": efficiency,
        "range_displacement": range_disp,
        "close_location": close_location,
        "trend_score": score,
        "five_min_checkpoint_count": len(closes),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--underlying", action="append", required=True,
                    help="BLOCK|underlying.csv; TRAIN/OOS_A-D only")
    ap.add_argument("--latest-sessions", type=int, default=90)
    ap.add_argument("--extreme-fraction", type=float, default=0.20)
    ap.add_argument("--output", required=True)
    ap.add_argument("--csv-output")
    a = ap.parse_args()

    if not (0 < a.extreme_fraction < 0.5):
        raise RuntimeError("--extreme-fraction must be between 0 and 0.5")

    specs = []
    all_rows = []
    all_dates = set()

    for spec in a.underlying:
        block, path = spec.split("|", 1)
        if block in FORBIDDEN:
            raise RuntimeError(f"Forbidden block: {block}")
        rows = read_csv(path)
        c = detect(rows)
        specs.append((block, rows, c))
        for r in rows:
            t = dt(r[c["timestamp"]])
            if t:
                all_dates.add(t.date().isoformat())

    selected_dates = sorted(all_dates)[-a.latest_sessions:]
    selected_set = set(selected_dates)

    sessions = []
    for block, rows, c in specs:
        grouped = defaultdict(list)
        for r in rows:
            t = dt(r[c["timestamp"]])
            if t and t.date().isoformat() in selected_set:
                grouped[t.date().isoformat()].append(r)
        for date_s, rs in grouped.items():
            x = classify_session(block, date_s, rs, c)
            if x:
                sessions.append(x)

    sessions.sort(key=lambda r: r["session_date"])

    target_count = max(1, round(len(sessions) * a.extreme_fraction))
    positives = sorted([r for r in sessions if r["trend_score"] > 0],
                       key=lambda r: r["trend_score"], reverse=True)
    negatives = sorted([r for r in sessions if r["trend_score"] < 0],
                       key=lambda r: r["trend_score"])

    bull_dates = {r["session_date"] for r in positives[:target_count]}
    bear_dates = {r["session_date"] for r in negatives[:target_count]}

    for r in sessions:
        if r["session_date"] in bull_dates:
            r["day_class"] = "BULLISH_TREND_DAY"
        elif r["session_date"] in bear_dates:
            r["day_class"] = "BEARISH_TREND_DAY"
        else:
            r["day_class"] = "MIXED_DAY"

    result = {
        "research_version": VERSION,
        "scope": {
            "latest_sessions_requested": a.latest_sessions,
            "selected_session_count": len(sessions),
            "first_session": sessions[0]["session_date"] if sessions else None,
            "last_session": sessions[-1]["session_date"] if sessions else None,
            "blocks": sorted({b for b, _, _ in specs}),
            "forbidden_blocks": sorted(FORBIDDEN),
            "classification_start_time": "09:20",
            "classification_end_time": "15:29",
        },
        "methodology": {
            "price_only": True,
            "oi_used": False,
            "pcr_used": False,
            "manual_direction_threshold_used": False,
            "extreme_fraction": a.extreme_fraction,
            "target_count_each_side": target_count,
            "trend_efficiency": "ABS(NET_POINTS)/SUM(ABS(SEQUENTIAL_5M_CLOSE_CHANGES))",
            "range_displacement": "ABS(NET_POINTS)/(DAY_HIGH-DAY_LOW)",
            "trend_score": "SIGN(NET_POINTS)*TREND_EFFICIENCY*RANGE_DISPLACEMENT",
        },
        "class_counts": {
            "BULLISH_TREND_DAY": sum(r["day_class"] == "BULLISH_TREND_DAY" for r in sessions),
            "BEARISH_TREND_DAY": sum(r["day_class"] == "BEARISH_TREND_DAY" for r in sessions),
            "MIXED_DAY": sum(r["day_class"] == "MIXED_DAY" for r in sessions),
        },
        "sessions": sessions,
        "integrity": {
            "historical_only": True,
            "oos_e_f_g_h_used": False,
            "strategy_rule_changed": False,
            "paper_or_live_action": False,
        },
    }

    p = Path(a.output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    if a.csv_output and sessions:
        cp = Path(a.csv_output)
        cp.parent.mkdir(parents=True, exist_ok=True)
        with cp.open("w", newline="", encoding="utf-8") as h:
            w = csv.DictWriter(h, fieldnames=list(sessions[0].keys()))
            w.writeheader()
            w.writerows(sessions)

    print(json.dumps({
        "research_version": VERSION,
        "selected_session_count": len(sessions),
        "historical_range": [
            result["scope"]["first_session"],
            result["scope"]["last_session"],
        ],
        "class_counts": result["class_counts"],
        "top_bullish": [
            {
                "date": r["session_date"],
                "net_points": r["net_points"],
                "trend_score": r["trend_score"],
                "efficiency": r["trend_efficiency"],
                "close_location": r["close_location"],
            }
            for r in positives[:target_count]
        ],
        "top_bearish": [
            {
                "date": r["session_date"],
                "net_points": r["net_points"],
                "trend_score": r["trend_score"],
                "efficiency": r["trend_efficiency"],
                "close_location": r["close_location"],
            }
            for r in negatives[:target_count]
        ],
        "output": a.output,
        "csv_output": a.csv_output,
    }, indent=2))


if __name__ == "__main__":
    main()
