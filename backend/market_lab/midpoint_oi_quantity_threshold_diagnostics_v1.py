from __future__ import annotations

"""
MIDPOINT_OI_QUANTITY_THRESHOLD_DIAGNOSTICS_V1

Descriptive research only.

Goal:
Quantify whether OI percentage changes are meaningful only when supported by
sufficient absolute OI quantity / absolute OI change.

Input:
midpoint-oi-magnitude-features-v1-development.csv

No strategy rule changes. No threshold promotion.
"""

import argparse
import csv
import json
from pathlib import Path
from statistics import median

RESEARCH_VERSION = "MIDPOINT_OI_QUANTITY_THRESHOLD_DIAGNOSTICS_V1"


def num(v):
    if v in ("", None):
        return None
    try:
        return float(v)
    except Exception:
        return None


def load(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def qtile(vals, q):
    vals=sorted(v for v in vals if v is not None)
    if not vals:
        return None
    if len(vals)==1:
        return vals[0]
    pos=(len(vals)-1)*q
    lo=int(pos)
    hi=min(lo+1,len(vals)-1)
    frac=pos-lo
    return vals[lo]*(1-frac)+vals[hi]*frac


def summarize(rows):
    n=len(rows)
    w=sum(1 for r in rows if r.get("outcome_group")=="WINNER")
    return {
        "count":n,
        "winner_count":w,
        "win_rate_pct":(w/n*100.0) if n else None,
        "median_net_5m_pct":median([num(r.get("net_5m_pct")) for r in rows if num(r.get("net_5m_pct")) is not None]) if rows else None,
    }


def abs_change_features(r):
    ce_cur=num(r.get("atm_ce_oi"))
    pe_cur=num(r.get("atm_pe_oi"))
    ce_prev=num(r.get("atm_ce_oi_previous"))
    pe_prev=num(r.get("atm_pe_oi_previous"))

    pm2_ce_cur=num(r.get("pm2_ce_oi"))
    pm2_pe_cur=num(r.get("pm2_pe_oi"))
    pm2_ce_prev=num(r.get("pm2_ce_oi_previous"))
    pm2_pe_prev=num(r.get("pm2_pe_oi_previous"))

    r["atm_ce_abs_change"]=None if ce_cur is None or ce_prev is None else abs(ce_cur-ce_prev)
    r["atm_pe_abs_change"]=None if pe_cur is None or pe_prev is None else abs(pe_cur-pe_prev)
    r["atm_total_oi"]=None if ce_cur is None or pe_cur is None else ce_cur+pe_cur
    r["atm_total_abs_change"]=None if r["atm_ce_abs_change"] is None or r["atm_pe_abs_change"] is None else r["atm_ce_abs_change"]+r["atm_pe_abs_change"]

    r["pm2_ce_abs_change"]=None if pm2_ce_cur is None or pm2_ce_prev is None else abs(pm2_ce_cur-pm2_ce_prev)
    r["pm2_pe_abs_change"]=None if pm2_pe_cur is None or pm2_pe_prev is None else abs(pm2_pe_cur-pm2_pe_prev)
    r["pm2_total_oi"]=None if pm2_ce_cur is None or pm2_pe_cur is None else pm2_ce_cur+pm2_pe_cur
    r["pm2_total_abs_change"]=None if r["pm2_ce_abs_change"] is None or r["pm2_pe_abs_change"] is None else r["pm2_ce_abs_change"]+r["pm2_pe_abs_change"]
    return r


def bucket_table(rows, field):
    vals=[num(r.get(field)) for r in rows if num(r.get(field)) is not None]
    cuts=[qtile(vals,0.25), qtile(vals,0.50), qtile(vals,0.75)]
    labels=["Q1_LOW","Q2","Q3","Q4_HIGH"]
    out=[]
    for i,label in enumerate(labels):
        if i==0:
            part=[r for r in rows if num(r.get(field)) is not None and num(r.get(field)) <= cuts[0]]
            lo=None; hi=cuts[0]
        elif i==1:
            part=[r for r in rows if num(r.get(field)) is not None and cuts[0] < num(r.get(field)) <= cuts[1]]
            lo=cuts[0]; hi=cuts[1]
        elif i==2:
            part=[r for r in rows if num(r.get(field)) is not None and cuts[1] < num(r.get(field)) <= cuts[2]]
            lo=cuts[1]; hi=cuts[2]
        else:
            part=[r for r in rows if num(r.get(field)) is not None and num(r.get(field)) > cuts[2]]
            lo=cuts[2]; hi=None
        out.append({"bucket":label,"lower_exclusive":lo,"upper_inclusive":hi,**summarize(part)})
    return {"quartiles":{"q25":cuts[0],"q50":cuts[1],"q75":cuts[2]},"buckets":out}


def pct_vs_quantity(rows, pct_field, abs_field):
    # Tests whether large % changes based on small absolute quantities behave differently.
    pct_vals=[abs(num(r.get(pct_field))) for r in rows if num(r.get(pct_field)) is not None]
    abs_vals=[num(r.get(abs_field)) for r in rows if num(r.get(abs_field)) is not None]
    pct_med=qtile(pct_vals,0.50)
    abs_med=qtile(abs_vals,0.50)

    groups={}
    for name,pct_hi,qty_hi in [
        ("HIGH_PCT_HIGH_QTY",True,True),
        ("HIGH_PCT_LOW_QTY",True,False),
        ("LOW_PCT_HIGH_QTY",False,True),
        ("LOW_PCT_LOW_QTY",False,False),
    ]:
        part=[]
        for r in rows:
            p=num(r.get(pct_field)); a=num(r.get(abs_field))
            if p is None or a is None:
                continue
            if (abs(p) >= pct_med)==pct_hi and (a >= abs_med)==qty_hi:
                part.append(r)
        groups[name]=summarize(part)

    return {
        "pct_abs_median_cut":pct_med,
        "absolute_quantity_median_cut":abs_med,
        "groups":groups,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--features",required=True)
    ap.add_argument("--output",required=True)
    a=ap.parse_args()

    rows=[abs_change_features(r) for r in load(a.features)]
    if not rows:
        raise RuntimeError("No input rows")

    result={
        "research_version":RESEARCH_VERSION,
        "population":summarize(rows),
        "quantity_distributions":{},
        "pct_vs_quantity":{},
        "direction_splits":{},
        "integrity":{
            "thresholds_are_descriptive_quantiles_only":True,
            "strategy_threshold_selected":False,
            "strategy_rule_changed":False,
            "fresh_oos_consumed":False,
            "oos_e_f_g_h_used":False,
            "paper_or_live_order_emission_allowed":False,
        }
    }

    fields=[
        "atm_total_oi",
        "atm_total_abs_change",
        "atm_ce_abs_change",
        "atm_pe_abs_change",
        "pm2_total_oi",
        "pm2_total_abs_change",
        "pm2_ce_abs_change",
        "pm2_pe_abs_change",
    ]
    for f in fields:
        result["quantity_distributions"][f]=bucket_table(rows,f)

    result["pct_vs_quantity"]["ATM_CE"]=pct_vs_quantity(rows,"atm_ce_oi_change_pct_5m","atm_ce_abs_change")
    result["pct_vs_quantity"]["ATM_PE"]=pct_vs_quantity(rows,"atm_pe_oi_change_pct_5m","atm_pe_abs_change")
    result["pct_vs_quantity"]["PM2_CE"]=pct_vs_quantity(rows,"pm2_ce_oi_change_pct_5m","pm2_ce_abs_change")
    result["pct_vs_quantity"]["PM2_PE"]=pct_vs_quantity(rows,"pm2_pe_oi_change_pct_5m","pm2_pe_abs_change")

    for direction in ("BULLISH","BEARISH"):
        sub=[r for r in rows if str(r.get("direction","")).upper()==direction]
        result["direction_splits"][direction]={
            "population":summarize(sub),
            "atm_total_oi":bucket_table(sub,"atm_total_oi"),
            "atm_total_abs_change":bucket_table(sub,"atm_total_abs_change"),
            "pm2_total_oi":bucket_table(sub,"pm2_total_oi"),
            "pm2_total_abs_change":bucket_table(sub,"pm2_total_abs_change"),
            "ATM_CE_pct_vs_qty":pct_vs_quantity(sub,"atm_ce_oi_change_pct_5m","atm_ce_abs_change"),
            "ATM_PE_pct_vs_qty":pct_vs_quantity(sub,"atm_pe_oi_change_pct_5m","atm_pe_abs_change"),
        }

    p=Path(a.output)
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
