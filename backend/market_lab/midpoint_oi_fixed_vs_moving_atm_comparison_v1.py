from __future__ import annotations

"""
MIDPOINT_OI_FIXED_VS_MOVING_ATM_COMPARISON_V1

Compare fixed 09:20 ATM bands against already validated moving ATM bands:
- moving ±2 vs fixed ±2
- moving ±5 vs fixed ±5

Comparisons are made on matched event populations only.
"""

import argparse,csv,json
from pathlib import Path
from statistics import median

VERSION="MIDPOINT_OI_FIXED_VS_MOVING_ATM_COMPARISON_V1"


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


def bucket(rows,field):
    vals=[num(r.get(field)) for r in rows if num(r.get(field)) is not None]
    cuts=[qtile(vals,.25),qtile(vals,.50),qtile(vals,.75)]
    out=[]
    for i,name in enumerate(["Q1","Q2","Q3","Q4"]):
        if i==0:
            part=[r for r in rows if num(r.get(field)) is not None and num(r.get(field))<=cuts[0]]
        elif i==1:
            part=[r for r in rows if num(r.get(field)) is not None and cuts[0]<num(r.get(field))<=cuts[1]]
        elif i==2:
            part=[r for r in rows if num(r.get(field)) is not None and cuts[1]<num(r.get(field))<=cuts[2]]
        else:
            part=[r for r in rows if num(r.get(field)) is not None and num(r.get(field))>cuts[2]]
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


def moving_pm2_abs(r):
    return (
        abs((num(r.get("pm2_ce_oi")) or 0)-(num(r.get("pm2_ce_oi_previous")) or 0))+
        abs((num(r.get("pm2_pe_oi")) or 0)-(num(r.get("pm2_pe_oi_previous")) or 0))
    )


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--moving-pm2",required=True)
    ap.add_argument("--moving-pm5",required=True)
    ap.add_argument("--fixed",required=True)
    ap.add_argument("--output",required=True)
    a=ap.parse_args()

    m2={key(r):r for r in load(a.moving_pm2)}
    m5={key(r):r for r in load(a.moving_pm5)}
    fx={key(r):r for r in load(a.fixed)}

    common2=sorted(k for k in (set(m2)&set(fx)) if num(fx[k].get("fixed_pm2_total_abs_change")) is not None)
    common5=sorted(k for k in (set(m5)&set(fx)) if num(fx[k].get("fixed_pm5_total_abs_change")) is not None)

    rows2=[]
    for k in common2:
        r=dict(fx[k])
        r["moving_pm2_total_abs_change"]=moving_pm2_abs(m2[k])
        rows2.append(r)

    rows5=[]
    for k in common5:
        r=dict(fx[k])
        r["moving_pm5_total_abs_change"]=num(m5[k].get("pm5_total_abs_change"))
        rows5.append(r)

    result={
        "research_version":VERSION,
        "fixed_atm_definition":"09:20 session ATM frozen for full session",
        "pm2":{
            "matched_population":len(rows2),
            "moving":bucket(rows2,"moving_pm2_total_abs_change"),
            "fixed":bucket(rows2,"fixed_pm2_total_abs_change"),
        },
        "pm5":{
            "matched_population":len(rows5),
            "moving":bucket(rows5,"moving_pm5_total_abs_change"),
            "fixed":bucket(rows5,"fixed_pm5_total_abs_change"),
        },
        "directions":{},
        "integrity":{
            "matched_event_comparison":True,
            "thresholds_descriptive_only":True,
            "strategy_rule_changed":False,
            "fresh_oos_consumed":False,
            "oos_e_f_g_h_used":False,
        }
    }

    for d in ("BULLISH","BEARISH"):
        s2=[r for r in rows2 if str(r.get("direction","")).upper()==d]
        s5=[r for r in rows5 if str(r.get("direction","")).upper()==d]
        result["directions"][d]={
            "pm2":{
                "count":len(s2),
                "moving":bucket(s2,"moving_pm2_total_abs_change"),
                "fixed":bucket(s2,"fixed_pm2_total_abs_change"),
            },
            "pm5":{
                "count":len(s5),
                "moving":bucket(s5,"moving_pm5_total_abs_change"),
                "fixed":bucket(s5,"fixed_pm5_total_abs_change"),
            }
        }

    p=Path(a.output);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
