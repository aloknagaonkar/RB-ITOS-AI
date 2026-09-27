#!/usr/bin/env python3
"""
25 AUG 2026 — FULL-DAY MIDPOINT/VWAP RESEARCH AUDIT V1

Scope:
- Session: 2026-08-25 only
- Trusted analysis window: 09:15 through 15:14 inclusive
- Research only
- No runtime, order, quantity, execution, or Candidate-A rule changes

Purpose:
Validate the three currently identified trade candidates:
1) 09:42 BEARISH — delayed full Candidate A
2) 12:00 BEARISH — failed RED-midpoint reclaim + RED-low rebreak
3) 14:31 BULLISH — structural recovery + GREEN-high / RED-high rebreak

Outputs:
- exact entry snapshots
- +1/+3/+5/+10/+15 minute directional moves
- MFE/MAE through 15:14
- structural hold/invalidation diagnostics
- a chronological event audit for 25 Aug
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

DATE = "2026-08-25"
SESSION_START = "09:15"
SESSION_END = "15:14"

UNDERLYING = Path("data/historical-evidence/underlying-ohlc-train.csv")
FUTURES = Path(
    "data/historical-evidence/"
    "midpoint-v2-nifty-futures-vwap-v1-all180.csv"
)

OUTDIR = Path(
    "data/historical-evidence/"
    "hilega-pcr-oi-support-research-v1/"
    "midpoint-vwap-2026-08-25-full-day-audit-v1"
)

EVENT_CSV = OUTDIR / "candidate-events-v1.csv"
MINUTE_CSV = OUTDIR / "full-day-minute-audit-v1.csv"
SUMMARY_TXT = OUTDIR / "summary-v1.txt"

RED_HIGH = 24198.25
RED_MID = 24185.975
RED_LOW = 24173.70

GREEN_HIGH = 24189.85
GREEN_MID = 24180.325
GREEN_LOW = 24170.80

HORIZONS = (1, 3, 5, 10, 15)

CANDIDATES = [
    {
        "candidate_id": "C1_DELAYED_CANDIDATE_A_BEAR",
        "direction": "BEARISH",
        "entry_time": "09:42",
        "mechanism": "DELAYED_FULL_CANDIDATE_A",
        "origin_time": "09:39",
        "reason": (
            "RED low broke at 09:39; full bearish Candidate A "
            "first became true at 09:42."
        ),
    },
    {
        "candidate_id": "C2_RED_FAILED_RECLAIM_REBREAK",
        "direction": "BEARISH",
        "entry_time": "12:00",
        "mechanism": "FAILED_RED_MIDPOINT_RECLAIM_REBREAK",
        "origin_time": "11:58",
        "reason": (
            "RED midpoint reclaimed at 11:58, failed at 11:59, "
            "RED low freshly re-broke at 12:00."
        ),
    },
    {
        "candidate_id": "C3_BULLISH_FULL_RANGE_REBREAK",
        "direction": "BULLISH",
        "entry_time": "14:31",
        "mechanism": "BULLISH_STRUCTURAL_RECOVERY_REBREAK",
        "origin_time": "14:27",
        "reason": (
            "GREEN low recovered, GREEN midpoint reclaimed, pullback, "
            "then 14:31 close broke GREEN high and RED high."
        ),
    },
]


def load_underlying():
    out = {}
    with UNDERLYING.open(newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get("session_date") != DATE:
                continue
            t = row["timestamp"][11:16]
            if not (SESSION_START <= t <= SESSION_END):
                continue
            out[t] = {
                "timestamp": row["timestamp"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
    return out


def load_futures():
    out = {}
    with FUTURES.open(newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get("session_date") != DATE:
                continue
            t = row["timestamp"][11:16]
            if not (SESSION_START <= t <= SESSION_END):
                continue
            close = float(row["close"])
            vwap = float(row["session_vwap"])
            out[t] = {
                "close": close,
                "vwap": vwap,
                "diff": close - vwap,
            }
    return out


def add_minutes(hhmm, minutes):
    dt = datetime.strptime(f"{DATE} {hhmm}", "%Y-%m-%d %H:%M")
    return (dt + timedelta(minutes=minutes)).strftime("%H:%M")


def directional_move(direction, entry, later):
    if direction == "BULLISH":
        return later - entry
    return entry - later


def first_close_cross(data, start_time, condition):
    for t in sorted(data):
        if t < start_time:
            continue
        if condition(data[t]["close"]):
            return t
    return None


def candidate_metrics(c, u, fut):
    t0 = c["entry_time"]
    entry = u[t0]["close"]
    direction = c["direction"]

    row = dict(c)
    row["entry_close"] = entry
    row["entry_futures_vwap_distance"] = (
        fut[t0]["diff"] if t0 in fut else None
    )

    for h in HORIZONS:
        t = add_minutes(t0, h)
        if t in u and t <= SESSION_END:
            later = u[t]["close"]
            row[f"close_tplus_{h}m"] = later
            row[f"directional_move_tplus_{h}m"] = directional_move(
                direction, entry, later
            )
        else:
            row[f"close_tplus_{h}m"] = None
            row[f"directional_move_tplus_{h}m"] = None

    # MFE/MAE from entry through trusted end 15:14.
    window = [
        (t, x)
        for t, x in sorted(u.items())
        if t >= t0 and t <= SESSION_END
    ]

    if direction == "BULLISH":
        best_t, best = max(window, key=lambda z: z[1]["high"])
        worst_t, worst = min(window, key=lambda z: z[1]["low"])
        row["mfe_points_to_1514"] = best["high"] - entry
        row["mfe_timestamp"] = best_t
        row["mae_points_to_1514"] = worst["low"] - entry
        row["mae_timestamp"] = worst_t
    else:
        best_t, best = min(window, key=lambda z: z[1]["low"])
        worst_t, worst = max(window, key=lambda z: z[1]["high"])
        row["mfe_points_to_1514"] = entry - best["low"]
        row["mfe_timestamp"] = best_t
        row["mae_points_to_1514"] = entry - worst["high"]
        row["mae_timestamp"] = worst_t

    # Structural invalidation diagnostics.
    if c["candidate_id"] == "C1_DELAYED_CANDIDATE_A_BEAR":
        row["first_close_above_red_mid"] = first_close_cross(
            u, t0, lambda x: x > RED_MID
        )
        row["first_close_above_red_high"] = first_close_cross(
            u, t0, lambda x: x > RED_HIGH
        )

    elif c["candidate_id"] == "C2_RED_FAILED_RECLAIM_REBREAK":
        row["first_close_above_red_mid"] = first_close_cross(
            u, t0, lambda x: x > RED_MID
        )
        row["first_close_above_red_high"] = first_close_cross(
            u, t0, lambda x: x > RED_HIGH
        )

    else:
        row["first_close_below_green_high"] = first_close_cross(
            u, t0, lambda x: x < GREEN_HIGH
        )
        row["first_close_below_green_mid"] = first_close_cross(
            u, t0, lambda x: x < GREEN_MID
        )
        row["first_close_below_red_high"] = first_close_cross(
            u, t0, lambda x: x < RED_HIGH
        )

    return row


def minute_flags(t, x, f):
    c = x["close"]
    flags = []

    if c < RED_LOW:
        flags.append("BELOW_RED_LOW")
    if c > RED_HIGH:
        flags.append("ABOVE_RED_HIGH")
    if c < RED_MID:
        flags.append("BELOW_RED_MID")
    if c > RED_MID:
        flags.append("ABOVE_RED_MID")

    if c < GREEN_LOW:
        flags.append("BELOW_GREEN_LOW")
    if c > GREEN_HIGH:
        flags.append("ABOVE_GREEN_HIGH")
    if c < GREEN_MID:
        flags.append("BELOW_GREEN_MID")
    if c > GREEN_MID:
        flags.append("ABOVE_GREEN_MID")

    if f is not None:
        d = f["diff"]
        if d < -5:
            flags.append("VWAP_BEAR")
        elif d > 5:
            flags.append("VWAP_BULL")
        else:
            flags.append("VWAP_NEUTRAL")

    return ",".join(flags)


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    u = load_underlying()
    fut = load_futures()

    missing = [c["entry_time"] for c in CANDIDATES if c["entry_time"] not in u]
    if missing:
        raise RuntimeError(f"Missing candidate underlying rows: {missing}")

    event_rows = [candidate_metrics(c, u, fut) for c in CANDIDATES]

    minute_rows = []
    for t, x in sorted(u.items()):
        f = fut.get(t)
        minute_rows.append({
            "session_date": DATE,
            "time": t,
            "open": x["open"],
            "high": x["high"],
            "low": x["low"],
            "close": x["close"],
            "red_high": RED_HIGH,
            "red_mid": RED_MID,
            "red_low": RED_LOW,
            "green_high": GREEN_HIGH,
            "green_mid": GREEN_MID,
            "green_low": GREEN_LOW,
            "close_minus_red_mid": x["close"] - RED_MID,
            "close_minus_red_low": x["close"] - RED_LOW,
            "close_minus_red_high": x["close"] - RED_HIGH,
            "close_minus_green_mid": x["close"] - GREEN_MID,
            "close_minus_green_low": x["close"] - GREEN_LOW,
            "close_minus_green_high": x["close"] - GREEN_HIGH,
            "futures_close": f["close"] if f else None,
            "futures_vwap": f["vwap"] if f else None,
            "futures_close_minus_vwap": f["diff"] if f else None,
            "flags": minute_flags(t, x, f),
        })

    write_csv(EVENT_CSV, event_rows)
    write_csv(MINUTE_CSV, minute_rows)

    lines = []
    lines.append("25 AUG 2026 — FULL-DAY MIDPOINT/VWAP AUDIT V1")
    lines.append("=" * 100)
    lines.append("Trusted window: 09:15–15:14 only.")
    lines.append("15:15 onward intentionally excluded.")
    lines.append("Research only — no strategy/runtime/order changes.")
    lines.append("")

    for r in event_rows:
        lines.append(r["candidate_id"])
        lines.append("-" * 100)
        lines.append(f"direction          = {r['direction']}")
        lines.append(f"entry_time         = {r['entry_time']}")
        lines.append(f"entry_close        = {r['entry_close']:.2f}")
        lines.append(
            f"entry FUT-VWAP     = "
            f"{r['entry_futures_vwap_distance']:+.2f}"
            if r["entry_futures_vwap_distance"] is not None
            else "entry FUT-VWAP     = NA"
        )
        lines.append(f"mechanism          = {r['mechanism']}")
        lines.append(f"reason             = {r['reason']}")

        for h in HORIZONS:
            move = r[f"directional_move_tplus_{h}m"]
            lines.append(
                f"directional +{h:2d}m  = "
                + ("NA" if move is None else f"{move:+.2f}")
            )

        lines.append(
            f"MFE through 15:14  = {r['mfe_points_to_1514']:+.2f} "
            f"at {r['mfe_timestamp']}"
        )
        lines.append(
            f"MAE through 15:14  = {r['mae_points_to_1514']:+.2f} "
            f"at {r['mae_timestamp']}"
        )

        for k in (
            "first_close_above_red_mid",
            "first_close_above_red_high",
            "first_close_below_green_high",
            "first_close_below_green_mid",
            "first_close_below_red_high",
        ):
            if k in r:
                lines.append(f"{k:22s}= {r[k]}")

        lines.append("")

    lines.append("WORKING DAY MAP")
    lines.append("-" * 100)
    lines.append("09:31  GREEN break; Candidate A rejected; bullish attempt later failed.")
    lines.append("09:39  RED boundary break.")
    lines.append("09:42  Delayed full bearish Candidate A -> Candidate #1.")
    lines.append("11:58  RED midpoint temporary reclaim.")
    lines.append("11:59  Failed reclaim.")
    lines.append("12:00  RED-low rebreak -> Candidate #2.")
    lines.append("12:00–13:50  Bearish regime / continuation; no forced repeated entries.")
    lines.append("13:50 onward recovery develops.")
    lines.append("14:27  GREEN low recovered.")
    lines.append("14:29  GREEN midpoint recovered.")
    lines.append("14:30  Pullback.")
    lines.append("14:31  GREEN high + RED high break -> Candidate #3.")
    lines.append("14:31–15:14  Sustained bullish acceptance.")
    lines.append("")
    lines.append(f"EVENT CSV  = {EVENT_CSV}")
    lines.append(f"MINUTE CSV = {MINUTE_CSV}")
    lines.append(f"SUMMARY    = {SUMMARY_TXT}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
