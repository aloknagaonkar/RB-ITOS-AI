#!/usr/bin/env python3
"""
PM T1/T2/T3 + FUTURES VWAP CONTEXT STUDY — LATEST 60 SESSIONS — V1

Separate PM / Family-E research only.

Reference box:
- 12:45:00 through 13:14:59
- HIGH = max high
- LOW  = min low
- MID  = (HIGH + LOW) / 2

Timestamps:
- T1 = first full boundary close-break after 13:15
- T2 = midpoint recross in the opposite direction after T1
- T3 = opposite full boundary close-break after T2

For T1/T2/T3:
- NIFTY underlying close
- NIFTY futures close
- session VWAP
- futures close - VWAP
- 5-minute change in futures close - VWAP
- directional VWAP agreement with the PM reversal direction

Outcome:
- Compare causal performance from T2 vs T3
- +1/+3/+5/+10/+15/+30/+60 minute directional movement
- causal MFE/MAE through 15:14

IMPORTANT:
- VWAP is descriptive only in this study.
- It is NOT an entry filter.
- Candidate A/B VWAP rules remain unchanged.
- B, C V1.1 and D remain frozen and untouched.
- No production/runtime/execution changes.
- 15:15 onward excluded.
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
FUTURES_CSV = ROOT / "midpoint-v2-nifty-futures-vwap-v1-all180.csv"

OUTDIR = (
    ROOT
    / "hilega-pcr-oi-support-research-v1"
    / "pm-t1-t2-t3-vwap-context-60-session-v1"
)
EVENTS_CSV = OUTDIR / "pm-t1-t2-t3-vwap-events-v1.csv"
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
        return xs[round((len(xs)-1)*p)]

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
                if not session or not ts or ts[11:16] > TRUSTED_END:
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
    return by_session


def load_futures():
    if not FUTURES_CSV.exists():
        raise FileNotFoundError(FUTURES_CSV)

    by_session = {}
    with FUTURES_CSV.open(newline="") as f:
        for r in csv.DictReader(f):
            session = r.get("session_date")
            ts = r.get("timestamp")
            if not session or not ts or ts[11:16] > TRUSTED_END:
                continue

            close = fnum(r.get("close"))
            vwap = fnum(r.get("session_vwap") or r.get("vwap"))
            if close is None or vwap is None:
                continue

            by_session.setdefault(session, {})[ts] = {
                "close": close,
                "vwap": vwap,
                "diff": close - vwap,
            }
    return by_session


def directional_move(direction, entry, later):
    return later - entry if direction == "BULLISH" else entry - later


def minutes_between(a, b):
    return (parse_ts(b) - parse_ts(a)).total_seconds() / 60.0


def vwap_context(ts, fut):
    cur = fut.get(ts)
    if not cur:
        return {
            "futures_close": None,
            "futures_vwap": None,
            "futures_diff": None,
            "futures_diff_change_5m": None,
        }

    prev = fut.get(add_minutes(ts, -5))
    d5 = None
    if prev:
        d5 = cur["diff"] - prev["diff"]

    return {
        "futures_close": cur["close"],
        "futures_vwap": cur["vwap"],
        "futures_diff": cur["diff"],
        "futures_diff_change_5m": d5,
    }


def vwap_agrees(direction, diff):
    if diff is None:
        return None
    if direction == "BULLISH":
        return diff > 0
    return diff < 0


def measure_from(ts, direction, bars):
    if ts not in bars:
        return {}

    entry = bars[ts]["close"]
    out = {"entry_close": entry}

    for h in HORIZONS:
        t = add_minutes(ts, h)
        if t in bars and t[11:16] <= TRUSTED_END:
            out[f"move_{h}m"] = directional_move(
                direction, entry, bars[t]["close"]
            )
        else:
            out[f"move_{h}m"] = None

    post = [
        (t, b)
        for t, b in sorted(bars.items())
        if t > ts and t[11:16] <= TRUSTED_END
    ]

    if post:
        if direction == "BULLISH":
            bt, bb = max(post, key=lambda x: x[1]["high"])
            wt, wb = min(post, key=lambda x: x[1]["low"])
            out["mfe"] = bb["high"] - entry
            out["mae"] = wb["low"] - entry
        else:
            bt, bb = min(post, key=lambda x: x[1]["low"])
            wt, wb = max(post, key=lambda x: x[1]["high"])
            out["mfe"] = entry - bb["low"]
            out["mae"] = entry - wb["high"]

        out["mfe_timestamp"] = bt
        out["mae_timestamp"] = wt

    return out


def analyze_session(session, bars, fut):
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

    high = max(b["high"] for _, b in ref)
    low = min(b["low"] for _, b in ref)
    mid = (high + low) / 2.0
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

    t1 = None
    first_dir = None

    for ts, b in obs:
        c = b["close"]
        if c > high:
            t1, first_dir = ts, "BULLISH"
            break
        if c < low:
            t1, first_dir = ts, "BEARISH"
            break

    row = {
        "session_date": session,
        "status": "OK",
        "reference_open": ref_open,
        "reference_high": high,
        "reference_low": low,
        "reference_close": ref_close,
        "reference_midpoint": mid,
        "reference_range": high - low,
        "reference_candle_color": ref_color,
        "t1_timestamp": t1 or "",
        "t1_direction": first_dir or "NO_BOUNDARY_BREAK",
    }

    if not t1:
        row["classification"] = "NO_BOUNDARY_BREAK"
        return row

    # T2: midpoint recross opposite to first break.
    t2 = None
    reversal_dir = "BEARISH" if first_dir == "BULLISH" else "BULLISH"

    for ts, b in obs:
        if ts <= t1:
            continue
        c = b["close"]
        if first_dir == "BEARISH" and c > mid:
            t2 = ts
            break
        if first_dir == "BULLISH" and c < mid:
            t2 = ts
            break

    if not t2:
        row["classification"] = "FIRST_BREAK_HOLDS_NO_MID_RECLAIM"
        return row

    # T3: opposite full boundary close-break after T2.
    t3 = None
    for ts, b in obs:
        if ts < t2:
            continue
        c = b["close"]
        if reversal_dir == "BULLISH" and c > high:
            t3 = ts
            break
        if reversal_dir == "BEARISH" and c < low:
            t3 = ts
            break

    row["t2_timestamp"] = t2
    row["t2_direction"] = reversal_dir
    row["minutes_t1_to_t2"] = minutes_between(t1, t2)

    if not t3:
        row["classification"] = "MIDPOINT_RECLAIM_NO_OPPOSITE_BOUNDARY_BREAK"
        return row

    row["classification"] = "FALSE_BREAK_FULL_REVERSAL"
    row["t3_timestamp"] = t3
    row["t3_direction"] = reversal_dir
    row["minutes_t2_to_t3"] = minutes_between(t2, t3)
    row["minutes_t1_to_t3"] = minutes_between(t1, t3)

    # VWAP context at all three timestamps.
    for label, ts, direction in (
        ("t1", t1, first_dir),
        ("t2", t2, reversal_dir),
        ("t3", t3, reversal_dir),
    ):
        vc = vwap_context(ts, fut)
        row[f"{label}_futures_close"] = vc["futures_close"]
        row[f"{label}_futures_vwap"] = vc["futures_vwap"]
        row[f"{label}_futures_diff"] = vc["futures_diff"]
        row[f"{label}_futures_diff_change_5m"] = vc["futures_diff_change_5m"]
        row[f"{label}_vwap_agrees_with_direction"] = vwap_agrees(
            direction, vc["futures_diff"]
        )

    # Did VWAP sign flip between T1 and T2 / T3?
    d1 = row.get("t1_futures_diff")
    d2 = row.get("t2_futures_diff")
    d3 = row.get("t3_futures_diff")

    row["vwap_sign_flip_t1_to_t2"] = (
        None if d1 is None or d2 is None
        else (d1 <= 0 < d2 or d1 >= 0 > d2)
    )
    row["vwap_sign_flip_t1_to_t3"] = (
        None if d1 is None or d3 is None
        else (d1 <= 0 < d3 or d1 >= 0 > d3)
    )

    # Measure from T2 and T3.
    for label, ts in (("t2", t2), ("t3", t3)):
        metrics = measure_from(ts, reversal_dir, bars)
        for k, v in metrics.items():
            row[f"{label}_{k}"] = v

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


def bool_count(rows, key, wanted=True):
    return sum(r.get(key) is wanted for r in rows)


def report_outcome(lines, rows, prefix, title):
    lines.append(title)
    lines.append("-" * 118)
    lines.append(f"events = {len(rows)}")
    lines.append(f"MFE = {qdesc(r.get(prefix+'_mfe') for r in rows)}")
    lines.append(f"MAE = {qdesc(r.get(prefix+'_mae') for r in rows)}")
    for h in HORIZONS:
        lines.append(
            f"+{h:2d}m = "
            f"{qdesc(r.get(prefix+f'_move_{h}m') for r in rows)}"
        )
    lines.append("")


def main():
    underlying = load_underlying()
    futures = load_futures()

    sessions = sorted(underlying)[-60:]
    rows = [
        analyze_session(
            s,
            underlying[s],
            futures.get(s, {}),
        )
        for s in sessions
    ]

    write_csv(EVENTS_CSV, rows)

    reversals = [
        r for r in rows
        if r.get("classification") == "FALSE_BREAK_FULL_REVERSAL"
    ]

    lines = []
    lines.append("PM T1/T2/T3 + FUTURES VWAP CONTEXT — LATEST 60 SESSIONS — V1")
    lines.append("=" * 118)
    lines.append("VWAP is descriptive only; no VWAP filter is applied.")
    lines.append("Candidate A/B unchanged. B/C V1.1/D remain frozen.")
    lines.append("")
    lines.append(f"selected sessions = {len(sessions)}")
    lines.append(f"first session     = {sessions[0]}")
    lines.append(f"last session      = {sessions[-1]}")
    lines.append(f"full reversals    = {len(reversals)}")
    lines.append("")

    cc = Counter(r.get("classification") for r in rows)
    lines.append("SESSION CLASSIFICATION")
    lines.append("-" * 118)
    for k in (
        "FALSE_BREAK_FULL_REVERSAL",
        "FIRST_BREAK_HOLDS_NO_MID_RECLAIM",
        "MIDPOINT_RECLAIM_NO_OPPOSITE_BOUNDARY_BREAK",
        "NO_BOUNDARY_BREAK",
        "INCOMPLETE_REFERENCE_WINDOW",
    ):
        lines.append(f"{k:<45} = {cc.get(k,0)}")
    lines.append("")

    lines.append("VWAP CONTEXT AT T1 / T2 / T3")
    lines.append("-" * 118)
    for label in ("t1", "t2", "t3"):
        lines.append(
            f"{label.upper()} diff: "
            f"{qdesc(r.get(label+'_futures_diff') for r in reversals)}"
        )
        lines.append(
            f"{label.upper()} 5m diff-change: "
            f"{qdesc(r.get(label+'_futures_diff_change_5m') for r in reversals)}"
        )
        lines.append(
            f"{label.upper()} VWAP agrees with direction = "
            f"{bool_count(reversals, label+'_vwap_agrees_with_direction', True)}/"
            f"{len(reversals)}"
        )
    lines.append("")

    lines.append(
        f"VWAP sign flip T1->T2 = "
        f"{bool_count(reversals,'vwap_sign_flip_t1_to_t2',True)}/{len(reversals)}"
    )
    lines.append(
        f"VWAP sign flip T1->T3 = "
        f"{bool_count(reversals,'vwap_sign_flip_t1_to_t3',True)}/{len(reversals)}"
    )
    lines.append("")

    # T2/T3 comparison all reversals.
    report_outcome(
        lines,
        reversals,
        "t2",
        "OUTCOME FROM T2 — MIDPOINT RECROSS",
    )
    report_outcome(
        lines,
        reversals,
        "t3",
        "OUTCOME FROM T3 — OPPOSITE BOUNDARY BREAK",
    )

    # Compare reversal-aligned VWAP at T2/T3.
    for label in ("t2", "t3"):
        agree = [
            r for r in reversals
            if r.get(label+"_vwap_agrees_with_direction") is True
        ]
        disagree = [
            r for r in reversals
            if r.get(label+"_vwap_agrees_with_direction") is False
        ]

        report_outcome(
            lines,
            agree,
            label,
            f"{label.upper()} OUTCOME — VWAP AGREES WITH REVERSAL",
        )
        report_outcome(
            lines,
            disagree,
            label,
            f"{label.upper()} OUTCOME — VWAP DISAGREES WITH REVERSAL",
        )

    # Reference color relation.
    lines.append("REFERENCE COLOR x REVERSAL DIRECTION")
    lines.append("-" * 118)
    rc = Counter(
        (r.get("reference_candle_color"), r.get("t3_direction"))
        for r in reversals
    )
    for color in ("GREEN", "RED", "DOJI"):
        lines.append(
            f"{color:<5} -> "
            f"BULL={rc.get((color,'BULLISH'),0):2d} "
            f"BEAR={rc.get((color,'BEARISH'),0):2d}"
        )
    lines.append("")

    # 25 Aug.
    lines.append("25 AUG 2026")
    lines.append("-" * 118)
    aug = [r for r in rows if r["session_date"] == "2026-08-25"]
    if not aug:
        lines.append("NOT FOUND")
    else:
        r = aug[0]
        for k in (
            "reference_high","reference_midpoint","reference_low",
            "reference_candle_color",
            "t1_timestamp","t1_direction",
            "t1_futures_diff","t1_futures_diff_change_5m",
            "t2_timestamp","t2_direction",
            "t2_futures_diff","t2_futures_diff_change_5m",
            "t3_timestamp","t3_direction",
            "t3_futures_diff","t3_futures_diff_change_5m",
            "vwap_sign_flip_t1_to_t2","vwap_sign_flip_t1_to_t3",
            "minutes_t1_to_t2","minutes_t2_to_t3","minutes_t1_to_t3",
            "t2_entry_close","t2_mfe","t2_mae",
            "t3_entry_close","t3_mfe","t3_mae",
        ):
            lines.append(f"{k} = {r.get(k)}")
        for h in HORIZONS:
            lines.append(
                f"T2 +{h}m = {r.get(f't2_move_{h}m')} | "
                f"T3 +{h}m = {r.get(f't3_move_{h}m')}"
            )

    lines.append("")
    lines.append("INTERPRETATION GUARD")
    lines.append("-" * 118)
    lines.append(
        "Do not convert VWAP sign, 5-minute VWAP change, reference color, "
        "or T2/T3 performance into a production filter from this run. "
        "This study only establishes whether VWAP context is informative."
    )
    lines.append("")
    lines.append(f"EVENTS CSV = {EVENTS_CSV}")
    lines.append(f"SUMMARY    = {SUMMARY_TXT}")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
