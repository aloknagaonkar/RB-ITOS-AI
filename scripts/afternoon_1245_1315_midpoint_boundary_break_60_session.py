#!/usr/bin/env python3
"""
AFTERNOON 12:45–13:15 RANGE-MIDPOINT BREAK STUDY — 60 SESSIONS — V1

Interpretation used:
- Build one completed 30-minute reference window from 12:45:00 through 13:14:59.
- Reference HIGH = max 1m high in that window.
- Reference LOW  = min 1m low in that window.
- Reference MID  = (HIGH + LOW) / 2.  ("median" interpreted as range midpoint.)
- From 13:15 onward, observe:
    1) first 1m close above MID / below MID
    2) first 1m close above HIGH / below LOW
    3) which full boundary breaks first
    4) what happens after the first boundary break
- Wick-only boundary breaches do NOT count; CLOSE is required.
- Trusted end 15:14. Everything 15:15 onward excluded.
- If both boundaries somehow close-break on the same minute, classify BOTH_SAME_MINUTE.

Research only. No strategy/runtime changes and no relationship is assumed with Europe;
the session window is tested exactly as requested.
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
    / "afternoon-1245-1315-midpoint-boundary-break-60-session-v1"
)
EVENTS_CSV = OUTDIR / "afternoon-break-events-v1.csv"
SUMMARY_TXT = OUTDIR / "summary-v1.txt"

REF_START = "12:45"
REF_END_EXCLUSIVE = "13:15"
OBS_START = "13:15"
TRUSTED_END = "15:14"
HORIZONS = (1,3,5,10,15,30,60)

def dt(ts):
    return datetime.fromisoformat(ts)

def fnum(v):
    if v in (None, ""): return None
    return float(v)

def qdesc(vals):
    xs = sorted(float(x) for x in vals if x is not None)
    if not xs: return "n=0"
    def q(p): return xs[round((len(xs)-1)*p)]
    return (
        f"n={len(xs)} mean={mean(xs):+.2f} median={median(xs):+.2f} "
        f"p25={q(.25):+.2f} p75={q(.75):+.2f} min={xs[0]:+.2f} max={xs[-1]:+.2f}"
    )

def load_underlying():
    by_session = {}
    for p in sorted(glob.glob(UNDERLYING_GLOB)):
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                s, ts = r.get("session_date"), r.get("timestamp")
                if not s or not ts:
                    continue
                t = ts[11:16]
                if t > TRUSTED_END:
                    continue
                rec = {
                    "open": fnum(r.get("open")),
                    "high": fnum(r.get("high")),
                    "low": fnum(r.get("low")),
                    "close": fnum(r.get("close")),
                }
                if None in rec.values():
                    continue
                by_session.setdefault(s, {})[ts] = rec
    return by_session

def add_minutes(ts, n):
    return (dt(ts)+timedelta(minutes=n)).isoformat()

def directional_move(direction, entry, later):
    return later-entry if direction=="BULLISH" else entry-later

def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with path.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def analyze_session(session, u):
    ref = [(ts,b) for ts,b in sorted(u.items()) if REF_START <= ts[11:16] < REF_END_EXCLUSIVE]
    # Exact 30 one-minute rows required.
    if len(ref) != 30:
        return {
            "session_date": session,
            "status": "INCOMPLETE_REFERENCE_WINDOW",
            "reference_row_count": len(ref),
        }

    high = max(b["high"] for _,b in ref)
    low = min(b["low"] for _,b in ref)
    mid = (high+low)/2.0
    ref_open = ref[0][1]["open"]
    ref_close = ref[-1][1]["close"]
    ref_dir = "GREEN" if ref_close > ref_open else "RED" if ref_close < ref_open else "DOJI"

    after = [(ts,b) for ts,b in sorted(u.items()) if OBS_START <= ts[11:16] <= TRUSTED_END]

    first_mid_up = first_mid_down = None
    first_high_break = first_low_break = None

    for ts,b in after:
        c=b["close"]
        if first_mid_up is None and c > mid: first_mid_up = ts
        if first_mid_down is None and c < mid: first_mid_down = ts
        if first_high_break is None and c > high: first_high_break = ts
        if first_low_break is None and c < low: first_low_break = ts

    if first_high_break and first_low_break:
        if first_high_break < first_low_break:
            break_dir, entry_ts = "BULLISH", first_high_break
        elif first_low_break < first_high_break:
            break_dir, entry_ts = "BEARISH", first_low_break
        else:
            break_dir, entry_ts = "BOTH_SAME_MINUTE", first_high_break
    elif first_high_break:
        break_dir, entry_ts = "BULLISH", first_high_break
    elif first_low_break:
        break_dir, entry_ts = "BEARISH", first_low_break
    else:
        break_dir, entry_ts = "NO_BOUNDARY_BREAK", None

    row = {
        "session_date": session,
        "status": "OK",
        "reference_row_count": 30,
        "reference_open": ref_open,
        "reference_high": high,
        "reference_low": low,
        "reference_close": ref_close,
        "reference_midpoint": mid,
        "reference_range": high-low,
        "reference_candle_direction": ref_dir,
        "first_mid_close_above": first_mid_up or "",
        "first_mid_close_below": first_mid_down or "",
        "first_high_close_break": first_high_break or "",
        "first_low_close_break": first_low_break or "",
        "first_boundary_break_direction": break_dir,
        "entry_timestamp": entry_ts or "",
    }

    if not entry_ts or break_dir == "BOTH_SAME_MINUTE":
        return row

    entry = u[entry_ts]["close"]
    row["entry_close"] = entry

    # Causal post-entry MFE/MAE: start next 1m and run to 15:14.
    post = [(ts,b) for ts,b in after if ts > entry_ts]
    if post:
        if break_dir == "BULLISH":
            bt,bb=max(post,key=lambda x:x[1]["high"])
            wt,wb=min(post,key=lambda x:x[1]["low"])
            row["mfe_to_1514"]=bb["high"]-entry
            row["mae_to_1514"]=wb["low"]-entry
        else:
            bt,bb=min(post,key=lambda x:x[1]["low"])
            wt,wb=max(post,key=lambda x:x[1]["high"])
            row["mfe_to_1514"]=entry-bb["low"]
            row["mae_to_1514"]=entry-wb["high"]
        row["mfe_timestamp"]=bt
        row["mae_timestamp"]=wt

    for h in HORIZONS:
        t = add_minutes(entry_ts,h)
        if t in u and t[11:16] <= TRUSTED_END:
            row[f"move_{h}m"]=directional_move(break_dir,entry,u[t]["close"])
        else:
            row[f"move_{h}m"]=None

    # Opposite-boundary failure after entry.
    opp = None
    for ts,b in post:
        c=b["close"]
        if break_dir=="BULLISH" and c < low:
            opp=ts; break
        if break_dir=="BEARISH" and c > high:
            opp=ts; break
    row["opposite_boundary_break_after_entry"] = opp or ""

    return row

def main():
    by_session=load_underlying()
    sessions=sorted(by_session)[-60:]
    rows=[analyze_session(s,by_session[s]) for s in sessions]
    write_csv(EVENTS_CSV,rows)

    ok=[r for r in rows if r["status"]=="OK"]
    boundary=[r for r in ok if r.get("first_boundary_break_direction") in ("BULLISH","BEARISH")]
    no_break=[r for r in ok if r.get("first_boundary_break_direction")=="NO_BOUNDARY_BREAK"]

    lines=[]
    lines.append("AFTERNOON 12:45–13:15 RANGE-MIDPOINT BREAK STUDY — LATEST 60 SESSIONS — V1")
    lines.append("="*114)
    lines.append("Reference window = 12:45 through 13:14 (30 completed 1m bars).")
    lines.append("Midpoint = (reference high + reference low) / 2.")
    lines.append("Observation starts 13:15. Close-based breaks only. 15:15 onward excluded.")
    lines.append("")
    lines.append(f"selected sessions          = {len(sessions)}")
    lines.append(f"first session              = {sessions[0]}")
    lines.append(f"last session               = {sessions[-1]}")
    lines.append(f"complete reference windows = {len(ok)}")
    lines.append(f"boundary-break sessions    = {len(boundary)}")
    lines.append(f"no-boundary-break sessions = {len(no_break)}")
    lines.append("")

    dc=Counter(r["first_boundary_break_direction"] for r in boundary)
    lines.append("FIRST FULL-BOUNDARY BREAK")
    lines.append("-"*114)
    lines.append(f"BULLISH = {dc.get('BULLISH',0)}")
    lines.append(f"BEARISH = {dc.get('BEARISH',0)}")
    lines.append("")

    for direction in ("BULLISH","BEARISH","COMBINED"):
        sub=boundary if direction=="COMBINED" else [r for r in boundary if r["first_boundary_break_direction"]==direction]
        lines.append(f"{direction}")
        lines.append("-"*114)
        lines.append(f"events = {len(sub)}")
        lines.append(f"reference range: {qdesc(r.get('reference_range') for r in sub)}")
        lines.append(f"MFE to 15:14:   {qdesc(r.get('mfe_to_1514') for r in sub)}")
        lines.append(f"MAE to 15:14:   {qdesc(r.get('mae_to_1514') for r in sub)}")
        for h in HORIZONS:
            lines.append(f"+{h:2d}m move:       {qdesc(r.get(f'move_{h}m') for r in sub)}")
        failed=sum(bool(r.get("opposite_boundary_break_after_entry")) for r in sub)
        lines.append(f"later opposite-boundary break = {failed}/{len(sub)}")
        lines.append("")

    lines.append("REFERENCE-CANDLE COLOR x FIRST BREAK")
    lines.append("-"*114)
    ct=Counter((r["reference_candle_direction"],r["first_boundary_break_direction"]) for r in boundary)
    for refdir in ("GREEN","RED","DOJI"):
        lines.append(
            f"{refdir:<5} -> BULL={ct.get((refdir,'BULLISH'),0):2d} "
            f"BEAR={ct.get((refdir,'BEARISH'),0):2d}"
        )
    lines.append("")

    lines.append("25 AUG 2026")
    lines.append("-"*114)
    for r in rows:
        if r["session_date"]=="2026-08-25":
            for k,v in r.items():
                lines.append(f"{k} = {v}")
    lines.append("")
    lines.append("Interpretation guard:")
    lines.append("This is descriptive research only. Do not turn the 12:45–13:15 window, midpoint, or any horizon into a production rule from this run.")
    lines.append(f"EVENTS CSV = {EVENTS_CSV}")
    lines.append(f"SUMMARY    = {SUMMARY_TXT}")

    OUTDIR.mkdir(parents=True,exist_ok=True)
    SUMMARY_TXT.write_text("\n".join(lines)+"\n")
    print("\n".join(lines))

if __name__=="__main__":
    main()
