
from __future__ import annotations

import argparse
import csv
import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path

VERSION = "VWAP_36_TREND_DAY_EXAMPLES_V1"

def parse_dt(s):
    return datetime.fromisoformat(s)

def direction_for(day_class):
    if day_class == "BULLISH_TREND_DAY":
        return "BULLISH"
    if day_class == "BEARISH_TREND_DAY":
        return "BEARISH"
    raise ValueError(day_class)

def aligned_side(day_class):
    return "ABOVE" if day_class == "BULLISH_TREND_DAY" else "BELOW"

def aligned_slope(day_class):
    return "RISING" if day_class == "BULLISH_TREND_DAY" else "FALLING"

def is_aligned(day_class, bar):
    return bar["side"] == aligned_side(day_class)

def first_aligned_acceptance(day_class, bars, n):
    key = f"accept_{n}cp"
    for b in bars:
        if is_aligned(day_class, b) and b.get(key):
            return b
    return None

def first_aligned_cross_acceptance(day_class, bars, n):
    wanted = "CROSS_ABOVE" if day_class == "BULLISH_TREND_DAY" else "CROSS_BELOW"
    key = f"accept_{n}cp"
    for b in bars:
        if b.get("cross") == wanted and b.get(key):
            return b
    return None

def bar_at_or_before(bars, t):
    eligible = [b for b in bars if parse_dt(b["candle_start"]) <= t]
    return eligible[-1] if eligible else None

def run_start_for_anchor(day_class, bars, anchor_index):
    """Start of the consecutive aligned VWAP-side run containing anchor bar."""
    if anchor_index is None or anchor_index < 0 or anchor_index >= len(bars):
        return None
    if not is_aligned(day_class, bars[anchor_index]):
        return None
    i = anchor_index
    while i > 0 and is_aligned(day_class, bars[i-1]):
        i -= 1
    return bars[i]

def minutes_between(a, b):
    if not a or not b:
        return None
    return (parse_dt(b) - parse_dt(a)).total_seconds() / 60.0

def nearest_anchor_bar(bars, move_start_ts):
    t=parse_dt(move_start_ts)
    # move-start timestamps are 5m START labels in the prior replay.
    exact=[(i,b) for i,b in enumerate(bars) if parse_dt(b["candle_start"]) == t]
    if exact:
        return exact[0]
    eligible=[(i,b) for i,b in enumerate(bars) if parse_dt(b["candle_start"]) <= t]
    return eligible[-1] if eligible else (None,None)

def median(vals):
    xs=[v for v in vals if v is not None]
    return statistics.median(xs) if xs else None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--vwap-profile", required=True)
    ap.add_argument("--move-replay", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--csv-output", required=True)
    a=ap.parse_args()

    vwap=json.loads(Path(a.vwap_profile).read_text())
    move=json.loads(Path(a.move_replay).read_text())

    sessions={
        s["session_date"]:s for s in vwap["sessions"]
        if s["day_class"] in ("BULLISH_TREND_DAY","BEARISH_TREND_DAY")
    }
    anchors={
        d["session_date"]:d for d in move["day_summaries"]
        if d["day_class"] in ("BULLISH_TREND_DAY","BEARISH_TREND_DAY")
        and d.get("status")=="AVAILABLE"
    }

    if len(sessions) != 36:
        raise RuntimeError(f"Expected 36 VWAP trend sessions, got {len(sessions)}")
    if len(anchors) != 36:
        raise RuntimeError(f"Expected 36 move-start sessions, got {len(anchors)}")
    if set(sessions) != set(anchors):
        raise RuntimeError(
            f"Date mismatch VWAP-only={sorted(set(sessions)-set(anchors))} "
            f"move-only={sorted(set(anchors)-set(sessions))}"
        )

    rows=[]
    for d in sorted(sessions):
        s=sessions[d]
        day_class=s["day_class"]
        bars=s["candles"]
        anchor=anchors[d]
        move_ts=anchor["move_start_timestamp"]
        idx, ab=nearest_anchor_bar(bars, move_ts)

        p2=first_aligned_acceptance(day_class,bars,2)
        p3=first_aligned_acceptance(day_class,bars,3)
        p4=first_aligned_acceptance(day_class,bars,4)
        cross_p3=first_aligned_cross_acceptance(day_class,bars,3)

        run_start=run_start_for_anchor(day_class,bars,idx)

        row={
            "session_date":d,
            "day_class":day_class,
            "direction":direction_for(day_class),
            "move_start_candle":anchor["move_start_time"],
            "move_start_close":anchor["move_start_close"],
            "move_points_from_anchor":anchor["move_points_from_anchor"],

            "first_p2_candle":p2["candle_label"] if p2 else None,
            "first_p2_available":p2["decision_available_at"][11:16] if p2 else None,
            "first_p3_candle":p3["candle_label"] if p3 else None,
            "first_p3_available":p3["decision_available_at"][11:16] if p3 else None,
            "first_p4_candle":p4["candle_label"] if p4 else None,
            "first_p4_available":p4["decision_available_at"][11:16] if p4 else None,

            "first_aligned_cross_p3_candle":cross_p3["candle_label"] if cross_p3 else None,
            "first_aligned_cross_p3_available":cross_p3["decision_available_at"][11:16] if cross_p3 else None,

            "anchor_vwap_side":ab["side"] if ab else None,
            "anchor_close":ab["close"] if ab else None,
            "anchor_vwap":ab["vwap"] if ab else None,
            "anchor_distance_points":ab["distance_points"] if ab else None,
            "anchor_vwap_slope":ab["vwap_slope"] if ab else None,
            "anchor_aligned":bool(ab and is_aligned(day_class,ab)),
            "anchor_slope_aligned":bool(ab and ab["vwap_slope"]==aligned_slope(day_class)),

            "aligned_run_start_candle":run_start["candle_label"] if run_start else None,
            "aligned_run_start_available":run_start["decision_available_at"][11:16] if run_start else None,
            "aligned_run_start_distance_points":run_start["distance_points"] if run_start else None,
        }

        if p3:
            row["p3_lead_minutes_to_move_start"] = (
                parse_dt(move_ts) - parse_dt(p3["decision_available_at"])
            ).total_seconds()/60.0
        else:
            row["p3_lead_minutes_to_move_start"] = None

        if run_start:
            row["run_start_lead_minutes_to_move_start"] = (
                parse_dt(move_ts) - parse_dt(run_start["decision_available_at"])
            ).total_seconds()/60.0
        else:
            row["run_start_lead_minutes_to_move_start"] = None

        rows.append(row)

    summary={}
    for dc in ("BULLISH_TREND_DAY","BEARISH_TREND_DAY"):
        xs=[r for r in rows if r["day_class"]==dc]
        summary[dc]={
            "day_count":len(xs),
            "anchor_vwap_aligned_count":sum(r["anchor_aligned"] for r in xs),
            "anchor_vwap_aligned_pct":100*sum(r["anchor_aligned"] for r in xs)/len(xs),
            "anchor_slope_aligned_count":sum(r["anchor_slope_aligned"] for r in xs),
            "anchor_slope_aligned_pct":100*sum(r["anchor_slope_aligned"] for r in xs)/len(xs),
            "first_p2_available_all_days":sum(r["first_p2_candle"] is not None for r in xs),
            "first_p3_available_all_days":sum(r["first_p3_candle"] is not None for r in xs),
            "first_p4_available_all_days":sum(r["first_p4_candle"] is not None for r in xs),
            "aligned_cross_p3_days":sum(r["first_aligned_cross_p3_candle"] is not None for r in xs),
            "median_p3_lead_minutes_to_move_start":median([r["p3_lead_minutes_to_move_start"] for r in xs]),
            "median_run_start_lead_minutes_to_move_start":median([r["run_start_lead_minutes_to_move_start"] for r in xs]),
        }

    overall={
        "day_count":len(rows),
        "anchor_vwap_aligned_count":sum(r["anchor_aligned"] for r in rows),
        "anchor_vwap_aligned_pct":100*sum(r["anchor_aligned"] for r in rows)/len(rows),
        "anchor_slope_aligned_count":sum(r["anchor_slope_aligned"] for r in rows),
        "anchor_slope_aligned_pct":100*sum(r["anchor_slope_aligned"] for r in rows)/len(rows),
        "aligned_cross_p3_days":sum(r["first_aligned_cross_p3_candle"] is not None for r in rows),
    }

    result={
        "research_version":VERSION,
        "purpose":"36 concrete chart-validatable VWAP examples on frozen 18 bullish + 18 bearish trend days",
        "important_causality":{
            "trend_day_label":"retrospective whole-session descriptive label",
            "move_start_anchor":"retrospective price-only last-minimum/last-maximum anchor; NOT live-available",
            "vwap_state":"prospective/causal at each completed candle",
            "chart_candle_label":"5m interval START",
            "available_time":"5 minutes after candle label, when the 5m candle has completed",
            "no_strategy_rule_changed":True,
        },
        "summary":summary,
        "overall":overall,
        "examples":rows,
    }
    Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")

    fields=list(rows[0].keys())
    with Path(a.csv_output).open("w",newline="",encoding="utf-8") as fh:
        w=csv.DictWriter(fh,fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(json.dumps({
        "research_version":VERSION,
        "overall":overall,
        "summary":summary,
        "output":a.output,
        "csv_output":a.csv_output,
    },indent=2,allow_nan=False))

if __name__=="__main__":
    main()
