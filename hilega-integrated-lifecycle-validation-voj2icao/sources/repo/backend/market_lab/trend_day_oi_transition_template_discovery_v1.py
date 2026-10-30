from __future__ import annotations

"""
TREND_DAY_OI_TRANSITION_TEMPLATE_DISCOVERY_V1

Discovers descriptive OI transition templates from the already-produced
TREND_DAY_MOVE_START_OI_REPLAY_V1 artifact.

Population:
- frozen 18 bullish trend days
- frozen 18 bearish trend days

Primary discovery mode:
- Moving ATM ±2

Relative checkpoints:
- T-10, T-5, T0, T+5, T+10, T+15, T+20 (whatever is causally available
  for each historical day around the retrospective price-only anchor)

Outputs at each relative checkpoint, separately for bullish/bearish:
- CE signed OI delta: median, q25, q75
- PE signed OI delta: median, q25, q75
- CE percentage: median, q25, q75
- PE percentage: median, q25, q75
- gross activity
- directional imbalance = PE delta - CE delta
- PCR previous/current/change
- sign-combo counts and percentages

Also outputs per-day Moving ±2 rows so that no aggregate can hide day-level
variation.

No threshold selection, no strategy rule, no paper/live action.
"""

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

VERSION = "TREND_DAY_OI_TRANSITION_TEMPLATE_DISCOVERY_V1"

OFFSETS = (-10, -5, 0, 5, 10, 15, 20)
CLASSES = ("BULLISH_TREND_DAY", "BEARISH_TREND_DAY")

def quantile(vals, q):
    xs = sorted(v for v in vals if v is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs)-1)*q
    lo = int(pos)
    hi = min(lo+1, len(xs)-1)
    frac = pos-lo
    return xs[lo]*(1-frac)+xs[hi]*frac

def stats(vals):
    xs=[v for v in vals if v is not None]
    return {
        "n": len(xs),
        "q25": quantile(xs, .25),
        "median": statistics.median(xs) if xs else None,
        "q75": quantile(xs, .75),
    }

def sign_combo(ce, pe):
    cs = "UP" if ce > 0 else "DOWN" if ce < 0 else "FLAT"
    ps = "UP" if pe > 0 else "DOWN" if pe < 0 else "FLAT"
    return f"CE_{cs}_PE_{ps}"

def summarize(rows):
    combos=Counter(sign_combo(r["ce_delta"],r["pe_delta"]) for r in rows)
    n=len(rows)
    return {
        "day_count": len({r["session_date"] for r in rows}),
        "row_count": n,
        "ce_delta": stats([r["ce_delta"] for r in rows]),
        "pe_delta": stats([r["pe_delta"] for r in rows]),
        "ce_pct": stats([r["ce_pct"] for r in rows]),
        "pe_pct": stats([r["pe_pct"] for r in rows]),
        "activity": stats([r["activity"] for r in rows]),
        "imbalance": stats([r["pe_delta"]-r["ce_delta"] for r in rows]),
        "pcr_previous": stats([r["pcr_previous"] for r in rows]),
        "pcr_current": stats([r["pcr_current"] for r in rows]),
        "pcr_change": stats([
            (r["pcr_current"]-r["pcr_previous"])
            if r["pcr_current"] is not None and r["pcr_previous"] is not None
            else None for r in rows
        ]),
        "positive_imbalance_count": sum((r["pe_delta"]-r["ce_delta"]) > 0 for r in rows),
        "negative_imbalance_count": sum((r["pe_delta"]-r["ce_delta"]) < 0 for r in rows),
        "positive_imbalance_pct": (
            sum((r["pe_delta"]-r["ce_delta"]) > 0 for r in rows)/n*100.0 if n else None
        ),
        "negative_imbalance_pct": (
            sum((r["pe_delta"]-r["ce_delta"]) < 0 for r in rows)/n*100.0 if n else None
        ),
        "sign_combo_counts": dict(sorted(combos.items())),
        "sign_combo_pct": {
            k: v/n*100.0 for k,v in sorted(combos.items())
        } if n else {},
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--replay",required=True)
    ap.add_argument("--mode",default="Moving ±2",
                    choices=["ATM","Moving ±2","Fixed ±2"])
    ap.add_argument("--output",required=True)
    ap.add_argument("--csv-output",required=True)
    args=ap.parse_args()

    src=json.loads(Path(args.replay).read_text(encoding="utf-8"))
    if src.get("research_version") != "TREND_DAY_MOVE_START_OI_REPLAY_V1":
        raise RuntimeError(
            "Expected TREND_DAY_MOVE_START_OI_REPLAY_V1 input, got "
            + str(src.get("research_version"))
        )

    rows=[]
    for r in src.get("rows",[]):
        if r.get("mode") != args.mode:
            continue
        if r.get("day_class") not in CLASSES:
            continue
        off=r.get("offset_minutes")
        if off not in OFFSETS:
            continue
        rr=dict(r)
        rr["imbalance"]=rr["pe_delta"]-rr["ce_delta"]
        rr["pcr_change"]=(
            rr["pcr_current"]-rr["pcr_previous"]
            if rr.get("pcr_current") is not None and rr.get("pcr_previous") is not None
            else None
        )
        rr["sign_combo"]=sign_combo(rr["ce_delta"],rr["pe_delta"])
        rows.append(rr)

    by_class_offset={}
    for dc in CLASSES:
        by_class_offset[dc]={}
        for off in OFFSETS:
            xs=[r for r in rows if r["day_class"]==dc and r["offset_minutes"]==off]
            by_class_offset[dc][str(off)]=summarize(xs)

    # Sequence-level descriptive summaries, based only on actually available rows.
    per_day=[]
    by_day=defaultdict(list)
    for r in rows:
        by_day[(r["session_date"],r["day_class"])].append(r)

    for (ds,dc),xs in sorted(by_day.items()):
        xs=sorted(xs,key=lambda r:r["offset_minutes"])
        out={
            "session_date":ds,
            "day_class":dc,
            "move_start_time":xs[0].get("move_start_time"),
            "available_offsets":[r["offset_minutes"] for r in xs],
        }
        for r in xs:
            key = "m"+str(abs(r["offset_minutes"])) if r["offset_minutes"] < 0 else \
                  "p"+str(r["offset_minutes"]) if r["offset_minutes"] > 0 else "t0"
            out[f"{key}_ce_delta"]=r["ce_delta"]
            out[f"{key}_pe_delta"]=r["pe_delta"]
            out[f"{key}_ce_pct"]=r["ce_pct"]
            out[f"{key}_pe_pct"]=r["pe_pct"]
            out[f"{key}_activity"]=r["activity"]
            out[f"{key}_imbalance"]=r["imbalance"]
            out[f"{key}_pcr_previous"]=r["pcr_previous"]
            out[f"{key}_pcr_current"]=r["pcr_current"]
            out[f"{key}_pcr_change"]=r["pcr_change"]
            out[f"{key}_sign_combo"]=r["sign_combo"]
        per_day.append(out)

    # Compact "candidate template evidence": do not choose thresholds.
    evidence={}
    for dc in CLASSES:
        evidence[dc]=[]
        for off in OFFSETS:
            s=by_class_offset[dc][str(off)]
            evidence[dc].append({
                "offset_minutes":off,
                "day_count":s["day_count"],
                "median_ce_delta":s["ce_delta"]["median"],
                "median_pe_delta":s["pe_delta"]["median"],
                "median_ce_pct":s["ce_pct"]["median"],
                "median_pe_pct":s["pe_pct"]["median"],
                "median_activity":s["activity"]["median"],
                "median_imbalance":s["imbalance"]["median"],
                "positive_imbalance_pct":s["positive_imbalance_pct"],
                "negative_imbalance_pct":s["negative_imbalance_pct"],
                "median_pcr_previous":s["pcr_previous"]["median"],
                "median_pcr_current":s["pcr_current"]["median"],
                "median_pcr_change":s["pcr_change"]["median"],
                "sign_combo_pct":s["sign_combo_pct"],
            })

    result={
        "research_version":VERSION,
        "source_research_version":src.get("research_version"),
        "source_replay":args.replay,
        "discovery_mode":args.mode,
        "population":{
            "bullish_days":len({r["session_date"] for r in rows if r["day_class"]=="BULLISH_TREND_DAY"}),
            "bearish_days":len({r["session_date"] for r in rows if r["day_class"]=="BEARISH_TREND_DAY"}),
        },
        "definitions":{
            "directional_imbalance":"PE_DELTA_MINUS_CE_DELTA",
            "activity":"ABS(CE_DELTA)+ABS(PE_DELTA)",
            "relative_offsets_minutes":list(OFFSETS),
            "move_start_anchor_is_retrospective":True,
            "threshold_selection_performed":False,
            "template_frozen":False,
        },
        "by_class_offset":by_class_offset,
        "candidate_template_evidence":evidence,
        "per_day":per_day,
        "integrity":{
            "uses_frozen_trend_day_population":True,
            "quantity_preserved":True,
            "percentage_preserved":True,
            "pcr_preserved":True,
            "no_new_thresholds":True,
            "strategy_rule_changed":False,
            "paper_or_live_action":False,
        },
    }

    op=Path(args.output); op.parent.mkdir(parents=True,exist_ok=True)
    op.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")

    cp=Path(args.csv_output); cp.parent.mkdir(parents=True,exist_ok=True)
    flat=[]
    for dc in CLASSES:
        for e in evidence[dc]:
            flat.append({"day_class":dc, **{k:v for k,v in e.items() if k!="sign_combo_pct"},
                         **{f"pct_{k}":v for k,v in e["sign_combo_pct"].items()}})
    if flat:
        fields=sorted(set().union(*(r.keys() for r in flat)))
        with cp.open("w",newline="",encoding="utf-8") as h:
            w=csv.DictWriter(h,fieldnames=fields)
            w.writeheader(); w.writerows(flat)

    print(json.dumps({
        "research_version":VERSION,
        "mode":args.mode,
        "population":result["population"],
        "candidate_template_evidence":evidence,
        "output":args.output,
        "csv_output":args.csv_output,
    },indent=2))

if __name__=="__main__":
    main()
