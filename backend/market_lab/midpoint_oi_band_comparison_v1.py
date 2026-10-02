from __future__ import annotations

"""
MIDPOINT_OI_BAND_COMPARISON_V1

Compare ATM±2 versus ATM±5 OI quantity/activity distributions on the exact
same 159-event development population.
"""

import argparse,csv,json
from pathlib import Path
from statistics import median

VERSION="MIDPOINT_OI_BAND_COMPARISON_V1"


def num(v):
    if v in ("",None): return None
    try:return float(v)
    except:return None


def load(p):
    with Path(p).open(newline="",encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def key(r):
    return (r.get("block"),r.get("session_date"),r.get("direction"),r.get("signal_timestamp"))


def qtile(vals,q):
    vals=sorted(v for v in vals if v is not None)
    if not vals:return None
    pos=(len(vals)-1)*q
    lo=int(pos); hi=min(lo+1,len(vals)-1); frac=pos-lo
    return vals[lo]*(1-frac)+vals[hi]*frac


def summary(rows, field):
    vals=[num(r.get(field)) for r in rows if num(r.get(field)) is not None]
    return {
        "count":len(vals),
        "q25":qtile(vals,.25),
        "median":qtile(vals,.50),
        "q75":qtile(vals,.75),
    }


def bucket(rows,field):
    vals=[num(r.get(field)) for r in rows if num(r.get(field)) is not None]
    cuts=[qtile(vals,.25),qtile(vals,.50),qtile(vals,.75)]
    out=[]
    for i,name in enumerate(["Q1","Q2","Q3","Q4"]):
        if i==0: part=[r for r in rows if num(r.get(field)) is not None and num(r.get(field))<=cuts[0]]
        elif i==1: part=[r for r in rows if cuts[0]<num(r.get(field))<=cuts[1]]
        elif i==2: part=[r for r in rows if cuts[1]<num(r.get(field))<=cuts[2]]
        else: part=[r for r in rows if num(r.get(field))>cuts[2]]
        wins=sum(r.get("outcome_group")=="WINNER" for r in part)
        rets=[num(r.get("net_5m_pct")) for r in part if num(r.get("net_5m_pct")) is not None]
        out.append({
            "bucket":name,
            "count":len(part),
            "winner_count":wins,
            "win_rate_pct":wins/len(part)*100 if part else None,
            "median_net_5m_pct":median(rets) if rets else None,
        })
    return {"cuts":{"q25":cuts[0],"q50":cuts[1],"q75":cuts[2]},"buckets":out}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--pm2",required=True)
    ap.add_argument("--pm5",required=True)
    ap.add_argument("--output",required=True)
    a=ap.parse_args()

    r2=load(a.pm2); r5=load(a.pm5)
    m2={key(r):r for r in r2}; m5={key(r):r for r in r5}
    common=sorted(set(m2)&set(m5))
    if len(common)!=159:
        raise RuntimeError(f"Expected 159 matched events, got {len(common)}")

    joined=[]
    for k in common:
        a2=m2[k]; a5=m5[k]
        joined.append({
            **a5,
            "pm2_total_oi": (num(a2.get("pm2_ce_oi")) or 0)+(num(a2.get("pm2_pe_oi")) or 0),
            "pm2_total_abs_change":
                abs((num(a2.get("pm2_ce_oi")) or 0)-(num(a2.get("pm2_ce_oi_previous")) or 0))+
                abs((num(a2.get("pm2_pe_oi")) or 0)-(num(a2.get("pm2_pe_oi_previous")) or 0)),
        })

    result={
        "research_version":VERSION,
        "matched_population":len(joined),
        "overall":{
            "pm2_total_oi_distribution":summary(joined,"pm2_total_oi"),
            "pm5_total_oi_distribution":summary(joined,"pm5_total_oi"),
            "pm2_total_abs_change":bucket(joined,"pm2_total_abs_change"),
            "pm5_total_abs_change":bucket(joined,"pm5_total_abs_change"),
        },
        "directions":{},
        "integrity":{
            "same_events_compared":True,
            "thresholds_descriptive_only":True,
            "strategy_rule_changed":False,
            "fresh_oos_consumed":False,
            "oos_e_f_g_h_used":False,
        }
    }
    for d in ("BULLISH","BEARISH"):
        sub=[r for r in joined if str(r.get("direction","")).upper()==d]
        result["directions"][d]={
            "count":len(sub),
            "pm2_total_abs_change":bucket(sub,"pm2_total_abs_change"),
            "pm5_total_abs_change":bucket(sub,"pm5_total_abs_change"),
        }

    p=Path(a.output);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
