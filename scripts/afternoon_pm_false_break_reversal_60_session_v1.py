#!/usr/bin/env python3
"""
PM FALSE-BREAK REVERSAL STUDY — LATEST 60 SESSIONS — V1

Frozen context:
- Families B, C V1.1, D are NOT changed by this script.
- This is a separate research family: PM / Family E candidate.

Reference structure:
- 12:45:00 through 13:14:59 = exactly 30 completed 1m candles
- HIGH = max high
- LOW  = min low
- MID  = (HIGH + LOW) / 2

Observation:
- starts 13:15
- 15:15 onward excluded
- full boundary break requires a 1m CLOSE, not a wick

Classification:
A) FIRST_BREAK_HOLDS
   First close breaks HIGH or LOW and the opposite boundary never closes through
   before 15:14.

B) FALSE_BREAK_OPPOSITE_BREAK
   First close breaks one boundary, price later recrosses MID in the opposite
   direction, and later closes through the opposite boundary.

For reversal events, entry/reference timestamp = opposite-boundary close-break.
Outcome measurement starts on the NEXT completed 1m candle.

Research only.
No runtime, Hilega, Candidate A, B, C, D, order, quantity, or execution changes.
"""

from __future__ import annotations

import csv
import glob
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path("data/historical-evidence")
UNDERLYING_GLOB = str(ROOT / "underlying-ohlc-*.csv")

OUTDIR = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "pm-false-break-reversal-60-session-v1"
)
EVENTS_CSV = OUTDIR / "pm-false-break-events-v1.csv"
REVERSALS_CSV = OUTDIR / "pm-reversal-events-v1.csv"
SUMMARY_TXT = OUTDIR / "summary-v1.txt"

REF_START = "12:45"
REF_END_EXCLUSIVE = "13:15"
OBS_START = "13:15"
TRUSTED_END = "15:14"

HORIZONS = (1, 3, 5, 10, 15, 30, 60)


def parse_ts(ts):
    return datetime.fromisoformat(ts)


def add_minutes(ts, n):
    return (parse_ts(ts) + timedelta(minutes=n)).isoformat()


def fnum(v):
    if v in (None, ""):
        return None
    return float(v)


def qdesc(values):
    xs = sorted(float(x) for x in values if x is not None)
    if not xs:
        return "n=0"

    def q(p):
        return xs[round((len(xs) - 1) * p)]

    return (
        f"n={len(xs)} mean={mean(xs):+.2f} median={median(xs):+.2f} "
        f"p25={q(.25):+.2f} p75={q(.75):+.2f} "
        f"min={xs[0]:+.2f} max={xs[-1]:+.2f}"
    )


def load_underlying():
    by_session = {}

    for p in sorted(glob.glob(UNDERLYING_GLOB)):
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                session = r.get("session_date")
                ts = r.get("timestamp")
                if not session or not ts:
                    continue
                if ts[11:16] > TRUSTED_END:
                    continue

                rec = {
                    "open": fnum(r.get("open")),
                    "high": fnum(r.get("high")),
                    "low": fnum(r.get("low")),
                    "close": fnum(r.get("close")),
                }

                if None in rec.values():
                    continue

                by_session.setdefault(session, {})[ts] = rec

    if not by_session:
        raise FileNotFoundError(UNDERLYING_GLOB)

    return by_session


def directional_move(direction, entry, later):
    return later - entry if direction == "BULLISH" else entry - later


def minutes_between(a, b):
    return (parse_ts(b) - parse_ts(a)).total_seconds() / 60.0


def first_mid_recross(after_first_break, first_dir, midpoint):
    """
    After a bearish first break, bullish reversal requires first close > midpoint.
    After a bullish first break, bearish reversal requires first close < midpoint.
    """
    for ts, bar in after_first_break:
        close = bar["close"]
        if first_dir == "BEARISH" and close > midpoint:
            return ts
        if first_dir == "BULLISH" and close < midpoint:
            return ts
    return None


def opposite_break(after_first_break, first_dir, high, low):
    for ts, bar in after_first_break:
        close = bar["close"]
        if first_dir == "BEARISH" and close > high:
            return ts, "BULLISH"
        if first_dir == "BULLISH" and close < low:
            return ts, "BEARISH"
    return None, None


def analyze_session(session, bars):
    ref = [
        (ts, b)
        for ts, b in sorted(bars.items())
        if REF_START <= ts[11:16] < REF_END_EXCLUSIVE
    ]

    if len(ref) != 30:
        return {
            "session_date": session,
            "status": "INCOMPLETE_REFERENCE_WINDOW",
            "reference_row_count": len(ref),
        }

    ref_high = max(b["high"] for _, b in ref)
    ref_low = min(b["low"] for _, b in ref)
    ref_mid = (ref_high + ref_low) / 2.0
    ref_open = ref[0][1]["open"]
    ref_close = ref[-1][1]["close"]
    ref_color = (
        "GREEN" if ref_close > ref_open
        else "RED" if ref_close < ref_open
        else "DOJI"
    )

    obs = [
        (ts, b)
        for ts, b in sorted(bars.items())
        if OBS_START <= ts[11:16] <= TRUSTED_END
    ]

    first_break_ts = None
    first_break_dir = None

    for ts, bar in obs:
        c = bar["close"]
        if c > ref_high:
            first_break_ts = ts
            first_break_dir = "BULLISH"
            break
        if c < ref_low:
            first_break_ts = ts
            first_break_dir = "BEARISH"
            break

    row = {
        "session_date": session,
        "status": "OK",
        "reference_row_count": 30,
        "reference_open": ref_open,
        "reference_high": ref_high,
        "reference_low": ref_low,
        "reference_close": ref_close,
        "reference_midpoint": ref_mid,
        "reference_range": ref_high - ref_low,
        "reference_candle_color": ref_color,
        "first_break_timestamp": first_break_ts or "",
        "first_break_direction": first_break_dir or "NO_BOUNDARY_BREAK",
    }

    if not first_break_ts:
        row["classification"] = "NO_BOUNDARY_BREAK"
        return row

    after_first = [
        (ts, b) for ts, b in obs if ts > first_break_ts
    ]

    mid_recross_ts = first_mid_recross(
        after_first, first_break_dir, ref_mid
    )
    opp_ts, reversal_dir = opposite_break(
        after_first, first_break_dir, ref_high, ref_low
    )

    row["midpoint_recross_timestamp"] = mid_recross_ts or ""
    row["opposite_boundary_break_timestamp"] = opp_ts or ""
    row["reversal_direction"] = reversal_dir or ""

    if opp_ts:
        row["classification"] = "FALSE_BREAK_OPPOSITE_BREAK"
        row["minutes_first_break_to_opposite_break"] = minutes_between(
            first_break_ts, opp_ts
        )

        if mid_recross_ts:
            row["minutes_first_break_to_mid_recross"] = minutes_between(
                first_break_ts, mid_recross_ts
            )
            row["minutes_mid_recross_to_opposite_break"] = minutes_between(
                mid_recross_ts, opp_ts
            )
        else:
            row["minutes_first_break_to_mid_recross"] = ""
            row["minutes_mid_recross_to_opposite_break"] = ""

        entry = bars[opp_ts]["close"]
        row["reversal_entry_close"] = entry

        for h in HORIZONS:
            t = add_minutes(opp_ts, h)
            if t in bars and t[11:16] <= TRUSTED_END:
                row[f"reversal_move_{h}m"] = directional_move(
                    reversal_dir, entry, bars[t]["close"]
                )
            else:
                row[f"reversal_move_{h}m"] = None

        post = [
            (ts, b) for ts, b in obs if ts > opp_ts
        ]

        if post:
            if reversal_dir == "BULLISH":
                bt, bb = max(post, key=lambda x: x[1]["high"])
                wt, wb = min(post, key=lambda x: x[1]["low"])
                row["reversal_mfe_to_1514"] = bb["high"] - entry
                row["reversal_mae_to_1514"] = wb["low"] - entry
            else:
                bt, bb = min(post, key=lambda x: x[1]["low"])
                wt, wb = max(post, key=lambda x: x[1]["high"])
                row["reversal_mfe_to_1514"] = entry - bb["low"]
                row["reversal_mae_to_1514"] = entry - wb["high"]

            row["reversal_mfe_timestamp"] = bt
            row["reversal_mae_timestamp"] = wt

        # Did price later break BACK through the original first-break boundary?
        re_failure = None
        for ts, b in post:
            c = b["close"]
            if reversal_dir == "BULLISH" and c < ref_low:
                re_failure = ts
                break
            if reversal_dir == "BEARISH" and c > ref_high:
                re_failure = ts
                break
        row["reversal_failed_back_through_range_timestamp"] = (
            re_failure or ""
        )

    else:
        row["classification"] = "FIRST_BREAK_HOLDS"
        row["minutes_first_break_to_opposite_break"] = ""
        if mid_recross_ts:
            row["minutes_first_break_to_mid_recross"] = minutes_between(
                first_break_ts, mid_recross_ts
            )
        else:
            row["minutes_first_break_to_mid_recross"] = ""

    return row


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
    by_session = load_underlying()
    sessions = sorted(by_session)[-60:]

    rows = [analyze_session(s, by_session[s]) for s in sessions]
    reversals = [
        r for r in rows
        if r.get("classification") == "FALSE_BREAK_OPPOSITE_BREAK"
    ]
    holds = [
        r for r in rows
        if r.get("classification") == "FIRST_BREAK_HOLDS"
    ]
    no_break = [
        r for r in rows
        if r.get("classification") == "NO_BOUNDARY_BREAK"
    ]

    write_csv(EVENTS_CSV, rows)
    write_csv(REVERSALS_CSV, reversals)

    lines = []
    lines.append("PM FALSE-BREAK REVERSAL STUDY — LATEST 60 SESSIONS — V1")
    lines.append("=" * 116)
    lines.append(
        "Reference: 12:45–13:14. Observation from 13:15. "
        "Close-based boundaries. 15:15 onward excluded."
    )
    lines.append("B/C/D remain frozen and untouched.")
    lines.append("")
    lines.append(f"selected sessions              = {len(sessions)}")
    lines.append(f"first session                  = {sessions[0]}")
    lines.append(f"last session                   = {sessions[-1]}")
    lines.append(f"first-break-holds sessions     = {len(holds)}")
    lines.append(f"false-break reversal sessions  = {len(reversals)}")
    lines.append(f"no-boundary-break sessions     = {len(no_break)}")
    lines.append("")

    lines.append("REVERSAL DIRECTION")
    lines.append("-" * 116)
    dc = Counter(r.get("reversal_direction") for r in reversals)
    lines.append(f"BULLISH reversals = {dc.get('BULLISH', 0)}")
    lines.append(f"BEARISH reversals = {dc.get('BEARISH', 0)}")
    lines.append("")

    lines.append("REVERSAL TIMING")
    lines.append("-" * 116)
    lines.append(
        "first break -> midpoint recross: "
        + qdesc(r.get("minutes_first_break_to_mid_recross") for r in reversals)
    )
    lines.append(
        "midpoint recross -> opposite break: "
        + qdesc(r.get("minutes_mid_recross_to_opposite_break") for r in reversals)
    )
    lines.append(
        "first break -> opposite break: "
        + qdesc(r.get("minutes_first_break_to_opposite_break") for r in reversals)
    )
    lines.append("")

    for direction in ("BULLISH", "BEARISH", "COMBINED"):
        sub = (
            reversals if direction == "COMBINED"
            else [r for r in reversals if r.get("reversal_direction") == direction]
        )
        lines.append(f"REVERSAL OUTCOME — {direction}")
        lines.append("-" * 116)
        lines.append(f"events = {len(sub)}")
        lines.append(
            f"MFE to 15:14 = "
            f"{qdesc(r.get('reversal_mfe_to_1514') for r in sub)}"
        )
        lines.append(
            f"MAE to 15:14 = "
            f"{qdesc(r.get('reversal_mae_to_1514') for r in sub)}"
        )
        for h in HORIZONS:
            lines.append(
                f"+{h:2d}m move = "
                f"{qdesc(r.get(f'reversal_move_{h}m') for r in sub)}"
            )

        failed_back = sum(
            bool(r.get("reversal_failed_back_through_range_timestamp"))
            for r in sub
        )
        lines.append(
            f"later failed back through original range = "
            f"{failed_back}/{len(sub)}"
        )
        lines.append("")

    lines.append("REFERENCE CANDLE COLOR x REVERSAL DIRECTION")
    lines.append("-" * 116)
    cc = Counter(
        (r.get("reference_candle_color"), r.get("reversal_direction"))
        for r in reversals
    )
    for color in ("GREEN", "RED", "DOJI"):
        lines.append(
            f"{color:<5} -> "
            f"BULL={cc.get((color, 'BULLISH'), 0):2d} "
            f"BEAR={cc.get((color, 'BEARISH'), 0):2d}"
        )
    lines.append("")

    lines.append("FIRST BREAK DIRECTION x REVERSAL DIRECTION")
    lines.append("-" * 116)
    fc = Counter(
        (r.get("first_break_direction"), r.get("reversal_direction"))
        for r in reversals
    )
    for first in ("BULLISH", "BEARISH"):
        lines.append(
            f"first {first:<7} -> "
            f"reversal BULL={fc.get((first, 'BULLISH'), 0):2d} "
            f"reversal BEAR={fc.get((first, 'BEARISH'), 0):2d}"
        )
    lines.append("")

    lines.append("25 AUG 2026")
    lines.append("-" * 116)
    aug = [r for r in rows if r["session_date"] == "2026-08-25"]
    if not aug:
        lines.append("NOT FOUND")
    else:
        for k, v in aug[0].items():
            lines.append(f"{k} = {v}")

    lines.append("")
    lines.append("EXPECTED 25 AUG STRUCTURE")
    lines.append("  first bearish boundary break ~13:24")
    lines.append("  bullish midpoint recross ~13:52")
    lines.append("  bullish opposite-boundary break ~13:53")
    lines.append("")
    lines.append("INTERPRETATION GUARD")
    lines.append("-" * 116)
    lines.append(
        "This study tests the PM false-break reversal hypothesis only. "
        "Do not turn timing, range size, reference color, or outcome statistics "
        "into production filters from this 60-session run."
    )
    lines.append("")
    lines.append(f"EVENTS CSV    = {EVENTS_CSV}")
    lines.append(f"REVERSALS CSV = {REVERSALS_CSV}")
    lines.append(f"SUMMARY       = {SUMMARY_TXT}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
