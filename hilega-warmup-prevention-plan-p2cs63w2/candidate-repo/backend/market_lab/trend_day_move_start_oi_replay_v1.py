from __future__ import annotations

"""
TREND_DAY_MOVE_START_OI_REPLAY_V1

Retrospective descriptive replay around the dominant intraday move start
for the already-frozen bullish/bearish trend days.

Move-start anchor (price-only, retrospective):
- Bullish day: LAST occurrence of the minimum 5-minute underlying close
  between 09:20 and 15:25.
- Bearish day: LAST occurrence of the maximum 5-minute underlying close
  between 09:20 and 15:25.

Why LAST occurrence?
It identifies the final opposing close-extreme before the dominant move
into the session trend. This is a retrospective anchor, NOT a causal
real-time signal and NOT an entry rule.

Replay window by default:
- T-10, T-5, T0, T+5, T+10, T+15, T+20

For each checkpoint it prints:
- ATM
- Moving ATM ±2
- Fixed 09:20 ATM ±2

Metrics:
- CE OI signed change
- CE OI %
- PE OI signed change
- PE OI %
- total activity = |CE delta| + |PE delta|
- PCR previous -> current

Historical-only. TRAIN/OOS_A-D. No OOS E/F/G/H.
"""

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

VERSION = "TREND_DAY_MOVE_START_OI_REPLAY_V1"
FORBIDDEN = {"OOS_E", "OOS_F", "OOS_G", "OOS_H"}

def f(v):
    if v in ("", None):
        return None
    try:
        return float(v)
    except Exception:
        return None

def dt(v):
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))

def pct(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / prev * 100.0

def read_dates(path):
    return {x.strip() for x in Path(path).read_text().splitlines() if x.strip()}

def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as h:
        return list(csv.DictReader(h))

def detect_underlying(rows):
    keys = set().union(*(r.keys() for r in rows))
    def first(*xs): return next((x for x in xs if x in keys), None)
    c = {
        "timestamp": first("timestamp", "datetime"),
        "close": first("close"),
    }
    missing = [k for k,v in c.items() if v is None]
    if missing:
        raise RuntimeError("Missing underlying columns: " + ", ".join(missing))
    return c

def detect_positioning(rows):
    keys = set().union(*(r.keys() for r in rows))
    def first(*xs): return next((x for x in xs if x in keys), None)
    c = {
        "timestamp": first("timestamp"),
        "spot": first("spot"),
        "atm": first("moving_atm"),
        "strike": first("strike"),
        "offset": first("strike_offset"),
        "ce_oi": first("ce_open_interest", "ce_oi"),
        "pe_oi": first("pe_open_interest", "pe_oi"),
    }
    missing = [k for k,v in c.items() if v is None]
    if missing:
        raise RuntimeError("Missing positioning columns: " + ", ".join(missing))
    return c

def snapshots(rows, c):
    out = {}
    for r in rows:
        t = dt(r[c["timestamp"]])
        out.setdefault(t, []).append(r)
    return out

def moving_atm(rows, c):
    for r in rows:
        if f(r[c["offset"]]) == 0:
            return f(r[c["atm"]])
    return None

def row_at_strike(rows, c, strike):
    for r in rows:
        if f(r[c["strike"]]) == strike:
            return r
    return None

def aggregate(cur, prev, c, strikes):
    cm = {f(r[c["strike"]]): r for r in cur}
    pm = {f(r[c["strike"]]): r for r in prev}
    common = sorted(set(strikes) & set(cm) & set(pm))
    if len(common) != len(set(strikes)):
        return None

    ce0 = sum(f(pm[s][c["ce_oi"]]) or 0 for s in common)
    ce1 = sum(f(cm[s][c["ce_oi"]]) or 0 for s in common)
    pe0 = sum(f(pm[s][c["pe_oi"]]) or 0 for s in common)
    pe1 = sum(f(cm[s][c["pe_oi"]]) or 0 for s in common)

    return {
        "ce_oi_previous": ce0,
        "ce_oi_current": ce1,
        "pe_oi_previous": pe0,
        "pe_oi_current": pe1,
        "ce_delta": ce1-ce0,
        "pe_delta": pe1-pe0,
        "ce_pct": pct(ce1, ce0),
        "pe_pct": pct(pe1, pe0),
        "activity": abs(ce1-ce0)+abs(pe1-pe0),
        "pcr_previous": pe0/ce0 if ce0 else None,
        "pcr_current": pe1/ce1 if ce1 else None,
        "strikes": common,
    }

def fixed_atm_for_day(sn, c, date_s, hhmm="09:20"):
    hh, mm = map(int, hhmm.split(":"))
    for t in sorted(sn):
        if t.date().isoformat() == date_s and (t.hour,t.minute) == (hh,mm):
            return moving_atm(sn[t], c)
    return None

def build_underlying_5m(rows, c, selected_dates):
    by_date = defaultdict(list)
    for r in rows:
        t = dt(r[c["timestamp"]])
        ds = t.date().isoformat()
        if ds not in selected_dates:
            continue
        if (t.hour,t.minute) < (9,20) or (t.hour,t.minute) > (15,25):
            continue
        if t.minute % 5 != 0:
            continue
        close = f(r[c["close"]])
        if close is not None:
            by_date[ds].append((t, close))
    for ds in by_date:
        by_date[ds].sort()
    return by_date

def move_anchor(points, day_class):
    if not points:
        return None
    if day_class == "BULLISH_TREND_DAY":
        extreme = min(v for _,v in points)
        candidates = [(t,v) for t,v in points if v == extreme]
    else:
        extreme = max(v for _,v in points)
        candidates = [(t,v) for t,v in points if v == extreme]
    # last occurrence of opposing close extreme
    return candidates[-1]

def mode_rows(cur, prev, c, current_atm, fixed_atm):
    out = []

    # ATM only
    a = aggregate(cur, prev, c, [current_atm])
    if a:
        out.append(("ATM", a))

    # Moving ±2
    mstrikes = [current_atm + i*50.0 for i in range(-2,3)]
    a = aggregate(cur, prev, c, mstrikes)
    if a:
        out.append(("Moving ±2", a))

    # Fixed 09:20 ±2
    if fixed_atm is not None:
        fstrikes = [fixed_atm + i*50.0 for i in range(-2,3)]
        a = aggregate(cur, prev, c, fstrikes)
        if a:
            out.append(("Fixed ±2", a))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bullish-dates", required=True)
    ap.add_argument("--bearish-dates", required=True)
    ap.add_argument("--underlying", action="append", required=True,
                    help="BLOCK|underlying.csv")
    ap.add_argument("--positioning", action="append", required=True,
                    help="BLOCK|positioning.csv")
    ap.add_argument("--fixed-atm-time", default="09:20")
    ap.add_argument("--pre-minutes", type=int, default=10)
    ap.add_argument("--post-minutes", type=int, default=20)
    ap.add_argument("--output", required=True)
    ap.add_argument("--csv-output", required=True)
    args = ap.parse_args()

    bull = read_dates(args.bullish_dates)
    bear = read_dates(args.bearish_dates)
    if bull & bear:
        raise RuntimeError("Bullish/bearish date overlap")
    class_map = {d:"BULLISH_TREND_DAY" for d in bull}
    class_map.update({d:"BEARISH_TREND_DAY" for d in bear})
    selected = set(class_map)

    underlying_points = {}
    for spec in args.underlying:
        block, path = spec.split("|",1)
        if block in FORBIDDEN:
            raise RuntimeError(f"Forbidden block: {block}")
        rows = read_csv(path)
        c = detect_underlying(rows)
        for ds, pts in build_underlying_5m(rows, c, selected).items():
            underlying_points[ds] = pts

    pos_by_date = defaultdict(dict)
    pos_cols_by_block = {}
    for spec in args.positioning:
        block, path = spec.split("|",1)
        if block in FORBIDDEN:
            raise RuntimeError(f"Forbidden block: {block}")
        rows = read_csv(path)
        c = detect_positioning(rows)
        pos_cols_by_block[block] = c
        sn = snapshots(rows, c)
        for t, rs in sn.items():
            ds = t.date().isoformat()
            if ds in selected:
                pos_by_date[ds][t] = (block, rs, c)

    day_summaries = []
    replay_rows = []

    for ds in sorted(selected):
        pts = underlying_points.get(ds, [])
        anchor = move_anchor(pts, class_map[ds])
        if anchor is None:
            day_summaries.append({
                "session_date":ds,
                "day_class":class_map[ds],
                "status":"NO_UNDERLYING_ANCHOR",
            })
            continue

        anchor_t, anchor_close = anchor
        snapmap = pos_by_date.get(ds, {})
        if not snapmap:
            day_summaries.append({
                "session_date":ds,
                "day_class":class_map[ds],
                "status":"NO_POSITIONING",
                "move_start_timestamp":anchor_t.isoformat(),
                "move_start_close":anchor_close,
            })
            continue

        sample_t = sorted(snapmap)[0]
        _, _, c = snapmap[sample_t]
        fixed_atm = fixed_atm_for_day(
            {t: triple[1] for t,triple in snapmap.items()},
            c, ds, args.fixed_atm_time
        )

        available_checkpoints = 0
        for off in range(-args.pre_minutes, args.post_minutes+1, 5):
            t = anchor_t + timedelta(minutes=off)
            prev_t = t - timedelta(minutes=5)
            if t not in snapmap or prev_t not in snapmap:
                continue
            _, cur, ccur = snapmap[t]
            _, prev, _ = snapmap[prev_t]
            current_atm = moving_atm(cur, ccur)
            if current_atm is None:
                continue
            available_checkpoints += 1
            for mode, metrics in mode_rows(cur, prev, ccur, current_atm, fixed_atm):
                replay_rows.append({
                    "session_date":ds,
                    "day_class":class_map[ds],
                    "move_start_timestamp":anchor_t.isoformat(),
                    "move_start_time":anchor_t.strftime("%H:%M"),
                    "move_start_close":anchor_close,
                    "offset_minutes":off,
                    "timestamp":t.isoformat(),
                    "time":t.strftime("%H:%M"),
                    "mode":mode,
                    "moving_atm":current_atm,
                    "fixed_atm":fixed_atm,
                    **metrics,
                })

        # move end / net from anchor to last 5m close
        last_t, last_close = pts[-1]
        signed_move = last_close - anchor_close
        day_summaries.append({
            "session_date":ds,
            "day_class":class_map[ds],
            "status":"AVAILABLE",
            "move_start_timestamp":anchor_t.isoformat(),
            "move_start_time":anchor_t.strftime("%H:%M"),
            "move_start_close":anchor_close,
            "last_5m_timestamp":last_t.isoformat(),
            "last_5m_close":last_close,
            "move_points_from_anchor":signed_move,
            "fixed_atm":fixed_atm,
            "replay_checkpoint_count":available_checkpoints,
        })

    result = {
        "research_version":VERSION,
        "anchor_definition":{
            "BULLISH_TREND_DAY":"LAST_MINIMUM_5M_CLOSE_09:20_TO_15:25",
            "BEARISH_TREND_DAY":"LAST_MAXIMUM_5M_CLOSE_09:20_TO_15:25",
            "retrospective_only":True,
            "causal_signal":False,
            "entry_rule":False,
        },
        "window":{
            "pre_minutes":args.pre_minutes,
            "post_minutes":args.post_minutes,
            "step_minutes":5,
        },
        "frozen_counts":{
            "bullish":len(bull),
            "bearish":len(bear),
        },
        "day_summaries":day_summaries,
        "rows":replay_rows,
        "integrity":{
            "frozen_day_lists_used":True,
            "price_only_move_anchor":True,
            "oi_not_used_to_choose_anchor":True,
            "historical_only":True,
            "oos_e_f_g_h_used":False,
            "strategy_rule_changed":False,
            "paper_or_live_action":False,
        }
    }

    op = Path(args.output)
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf-8")

    cp = Path(args.csv_output)
    cp.parent.mkdir(parents=True, exist_ok=True)
    if replay_rows:
        with cp.open("w", newline="", encoding="utf-8") as h:
            w = csv.DictWriter(h, fieldnames=list(replay_rows[0].keys()))
            w.writeheader()
            w.writerows(replay_rows)

    print(json.dumps({
        "research_version":VERSION,
        "bullish_count":len(bull),
        "bearish_count":len(bear),
        "available_day_count":sum(d.get("status")=="AVAILABLE" for d in day_summaries),
        "replay_row_count":len(replay_rows),
        "day_summaries":day_summaries,
        "output":args.output,
        "csv_output":args.csv_output,
    }, indent=2))

if __name__ == "__main__":
    main()
