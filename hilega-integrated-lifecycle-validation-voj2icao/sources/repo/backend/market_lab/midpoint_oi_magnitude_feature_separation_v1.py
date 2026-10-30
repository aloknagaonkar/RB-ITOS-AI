from __future__ import annotations

"""
MIDPOINT_OI_MAGNITUDE_FEATURE_SEPARATION_V1

Descriptive research only.

Purpose:
Test whether overall OI level + true 5-minute OI change % + CE/PE divergence
help separate winners from losers across the existing development population.

Scope:
- TRAIN + OOS_A + OOS_B + OOS_C + OOS_D only
- OOS_E/F/G/H forbidden
- no threshold tuning
- no strategy changes
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

RESEARCH_VERSION = "MIDPOINT_OI_MAGNITUDE_FEATURE_SEPARATION_V1"
FORBIDDEN = {"OOS_E","OOS_F","OOS_G","OOS_H"}


def num(v: Any):
    if v in ("", None):
        return None
    try:
        return float(v)
    except Exception:
        return None


def pct(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / prev * 100.0


def load_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def stats(vals):
    vals=[v for v in vals if v is not None]
    if not vals:
        return {"count":0,"mean":None,"median":None,"min":None,"max":None}
    return {
        "count":len(vals),
        "mean":mean(vals),
        "median":median(vals),
        "min":min(vals),
        "max":max(vals),
    }


def summarize_group(rows):
    keys = [
        "atm_ce_oi","atm_pe_oi",
        "atm_ce_oi_change_pct_5m","atm_pe_oi_change_pct_5m",
        "pm2_ce_oi","pm2_pe_oi",
        "pm2_ce_oi_change_pct_5m","pm2_pe_oi_change_pct_5m",
        "pm2_oi_pcr",
        "ce_minus_pe_change_pct",
        "abs_change_divergence",
    ]
    return {k:stats([num(r.get(k)) for r in rows]) for k in keys}


def normalize_row(r):
    block=str(r.get("block","")).strip()
    if block in FORBIDDEN:
        raise RuntimeError(f"Forbidden block present: {block}")

    out=dict(r)
    ce=num(r.get("atm_ce_oi_change_pct_5m"))
    pe=num(r.get("atm_pe_oi_change_pct_5m"))
    out["ce_minus_pe_change_pct"] = None if ce is None or pe is None else ce - pe
    out["abs_change_divergence"] = None if ce is None or pe is None else abs(ce - pe)
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--features", required=True,
                    help="CSV produced by the development-wide OI feature extractor")
    ap.add_argument("--output", required=True)
    args=ap.parse_args()

    raw=load_csv(Path(args.features))
    rows=[normalize_row(r) for r in raw]

    winners=[r for r in rows if str(r.get("outcome_group","")).upper() == "WINNER"]
    losers=[r for r in rows if str(r.get("outcome_group","")).upper() == "LOSER"]

    result={
        "research_version":RESEARCH_VERSION,
        "population":{
            "rows":len(rows),
            "winners":len(winners),
            "losers":len(losers),
            "blocks":sorted(set(str(r.get("block","")) for r in rows)),
        },
        "winner_summary":summarize_group(winners),
        "loser_summary":summarize_group(losers),
        "direction_splits":{},
        "integrity":{
            "threshold_tuning_performed":False,
            "strategy_rule_changed":False,
            "fresh_oos_consumed":False,
            "oos_e_f_g_h_used":False,
            "retrospective_outcome_used_only_for_grouping":True,
            "paper_or_live_order_emission_allowed":False,
        }
    }

    for direction in ("BULLISH","BEARISH"):
        d=[r for r in rows if str(r.get("direction","")).upper()==direction]
        dw=[r for r in d if str(r.get("outcome_group","")).upper()=="WINNER"]
        dl=[r for r in d if str(r.get("outcome_group","")).upper()=="LOSER"]
        result["direction_splits"][direction]={
            "winner_summary":summarize_group(dw),
            "loser_summary":summarize_group(dl),
            "winner_count":len(dw),
            "loser_count":len(dl),
        }

    p=Path(args.output)
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
