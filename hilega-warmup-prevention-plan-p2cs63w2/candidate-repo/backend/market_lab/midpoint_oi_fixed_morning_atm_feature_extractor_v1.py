from __future__ import annotations

"""
MIDPOINT_OI_FIXED_MORNING_ATM_FEATURE_EXTRACTOR_V1

Research-only fixed-morning-ATM OI extractor.

Definition:
- For each session, freeze ATM from the exact 09:20 IST positioning checkpoint.
- Keep that same physical ATM center for the entire session.
- Compute both fixed ATM ±2 and fixed ATM ±5 bands.
- Compare identical physical strikes between checkpoint T0 and T-5m.
- Use the same global exemplar population and causal oi_vwap_checkpoint_timestamp.

Allowed: TRAIN + OOS_A-D
Forbidden: OOS_E/F/G/H
"""

import argparse
import csv
import json
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Any

ALLOWED={"TRAIN","OOS_A","OOS_B","OOS_C","OOS_D"}
FORBIDDEN={"OOS_E","OOS_F","OOS_G","OOS_H"}
WIN_BUCKETS={"EXCELLENT_5M_GE_10","GOOD_5M_3_TO_10"}
LOSS_BUCKETS={"LOSS_5M_0_TO_MINUS5","LARGE_LOSS_5M_LE_MINUS5"}
SMALL={"SMALL_WIN_5M_0_TO_3"}
VERSION="MIDPOINT_OI_FIXED_MORNING_ATM_FEATURE_EXTRACTOR_V1"


def num(v: Any):
    if v in ("",None): return None
    try: return float(v)
    except Exception: return None


def parse_ts(v):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception: return None


def pct(cur,prev):
    if cur is None or prev in (None,0): return None
    return (cur-prev)/prev*100.0


def read_csv(path):
    with Path(path).open(newline="",encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def detect(rows):
    keys=set().union(*(r.keys() for r in rows))
    def first(*xs):
        return next((x for x in xs if x in keys),None)
    c={
        "timestamp":first("timestamp","datetime","provider_timestamp","time"),
        "strike":first("strike","strike_price"),
        "offset":first("strike_offset","offset"),
        "atm":first("moving_atm","atm","atm_strike"),
        "ce_oi":first("ce_oi","call_oi","ce_open_interest","call_open_interest"),
        "pe_oi":first("pe_oi","put_oi","pe_open_interest","put_open_interest"),
    }
    miss=[k for k,v in c.items() if v is None]
    if miss: raise RuntimeError("Missing positioning columns: "+", ".join(miss))
    return c


def snapshots(rows,c):
    out={}
    for r in rows:
        t=parse_ts(r.get(c["timestamp"]))
        if t:
            out.setdefault(t,[]).append(r)
    return out


def outcome(e):
    b=str(e.get("quality_bucket") or "")
    if b in WIN_BUCKETS: return "WINNER"
    if b in LOSS_BUCKETS: return "LOSER"
    if b in SMALL: return "SMALL_WIN"
    return None


def fixed_atm_by_session(snaps,c,hhmm="09:20"):
    hh,mm=[int(x) for x in hhmm.split(":")]
    out={}
    for t,rows in snaps.items():
        if t.hour==hh and t.minute==mm:
            atm_rows=[r for r in rows if num(r.get(c["offset"]))==0]
            if atm_rows:
                atm=num(atm_rows[0].get(c["atm"]))
                if atm is not None:
                    out[t.date().isoformat()]=atm
    return out


def aggregate_band(cur,prev,c,center,width,step=50,prefix="fixed_pm2"):
    wanted={center+i*step for i in range(-width,width+1)}
    cm={num(r[c["strike"]]):r for r in cur}
    pm={num(r[c["strike"]]):r for r in prev}
    common=sorted(wanted & set(cm) & set(pm))
    if not common:
        return {}

    ce_prev=sum(num(pm[s][c["ce_oi"]]) or 0 for s in common)
    ce_cur=sum(num(cm[s][c["ce_oi"]]) or 0 for s in common)
    pe_prev=sum(num(pm[s][c["pe_oi"]]) or 0 for s in common)
    pe_cur=sum(num(cm[s][c["pe_oi"]]) or 0 for s in common)

    return {
        f"{prefix}_ce_oi_previous":ce_prev,
        f"{prefix}_ce_oi":ce_cur,
        f"{prefix}_pe_oi_previous":pe_prev,
        f"{prefix}_pe_oi":pe_cur,
        f"{prefix}_ce_change_abs":ce_cur-ce_prev,
        f"{prefix}_pe_change_abs":pe_cur-pe_prev,
        f"{prefix}_ce_abs_change":abs(ce_cur-ce_prev),
        f"{prefix}_pe_abs_change":abs(pe_cur-pe_prev),
        f"{prefix}_total_oi":ce_cur+pe_cur,
        f"{prefix}_total_abs_change":abs(ce_cur-ce_prev)+abs(pe_cur-pe_prev),
        f"{prefix}_ce_oi_change_pct_5m":pct(ce_cur,ce_prev),
        f"{prefix}_pe_oi_change_pct_5m":pct(pe_cur,pe_prev),
        f"{prefix}_pcr_previous":pe_prev/ce_prev if ce_prev else None,
        f"{prefix}_pcr":pe_cur/ce_cur if ce_cur else None,
        f"{prefix}_common_strike_count":len(common),
        f"{prefix}_common_strikes":";".join(str(int(s)) for s in common),
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--events-json",required=True)
    ap.add_argument("--positioning",action="append",required=True)
    ap.add_argument("--fixed-atm-time",default="09:20")
    ap.add_argument("--output",required=True)
    a=ap.parse_args()

    doc=json.loads(Path(a.events_json).read_text(encoding="utf-8"))
    events=doc.get("events")
    if not isinstance(events,list) or len(events)!=184:
        raise RuntimeError(f"Expected 184 global exemplar events, got {None if not isinstance(events,list) else len(events)}")

    pos={}
    fixed={}
    for spec in a.positioning:
        block,path=spec.split("|",1)
        if block in FORBIDDEN: raise RuntimeError(f"Forbidden block: {block}")
        if block not in ALLOWED: continue
        rows=read_csv(path)
        c=detect(rows)
        snaps=snapshots(rows,c)
        pos[block]=(c,snaps)
        fixed[block]=fixed_atm_by_session(snaps,c,a.fixed_atm_time)

    out=[]
    excluded_small=0
    missing_fixed_atm=0
    missing_checkpoint=0
    missing_pm2=0
    missing_pm5=0

    for e in events:
        block=str(e.get("block",""))
        if block in FORBIDDEN: raise RuntimeError(f"Forbidden event block: {block}")
        if block not in ALLOWED: continue

        grp=outcome(e)
        if grp=="SMALL_WIN":
            excluded_small+=1
            continue
        if grp not in {"WINNER","LOSER"}:
            continue

        session=str(e.get("session_date") or "")
        center=fixed.get(block,{}).get(session)
        if center is None:
            missing_fixed_atm+=1
            continue

        cp=parse_ts(e.get("oi_vwap_checkpoint_timestamp"))
        sig=parse_ts(e.get("signal_timestamp"))
        if not cp or not sig or block not in pos:
            missing_checkpoint+=1
            continue

        prev=cp-timedelta(minutes=5)
        c,snaps=pos[block]
        cur=snaps.get(cp,[])
        prv=snaps.get(prev,[])
        if not cur or not prv:
            missing_checkpoint+=1
            continue

        pm2=aggregate_band(cur,prv,c,center,2,50,"fixed_pm2")
        pm5=aggregate_band(cur,prv,c,center,5,50,"fixed_pm5")
        if not pm2:
            missing_pm2+=1
        if not pm5:
            missing_pm5+=1
        if not pm2 and not pm5:
            continue

        econ=e.get("option_economics") or {}
        row={
            "block":block,
            "session_date":session,
            "direction":e.get("direction"),
            "setup_type":e.get("setup_type"),
            "decision_family":e.get("decision_family"),
            "signal_timestamp":sig.isoformat(),
            "checkpoint_timestamp":cp.isoformat(),
            "previous_checkpoint_timestamp":prev.isoformat(),
            "quality_bucket":e.get("quality_bucket"),
            "outcome_group":grp,
            "net_5m_pct":num(econ.get("net_5m_pct")),
            "fixed_atm_time":a.fixed_atm_time,
            "fixed_atm_strike":center,
        }
        row.update(pm2)
        row.update(pm5)
        out.append(row)

    if not out:
        raise RuntimeError("Fixed morning ATM extraction produced zero rows")

    p=Path(a.output); p.parent.mkdir(parents=True,exist_ok=True)
    fields=[]
    for r in out:
        for k in r:
            if k not in fields: fields.append(k)
    with p.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader(); w.writerows(out)

    def present(prefix):
        return sum(1 for r in out if r.get(f"{prefix}_total_abs_change") not in ("",None))

    print(json.dumps({
        "research_version":VERSION,
        "global_event_count":184,
        "excluded_small_win_count":excluded_small,
        "expected_outcome_filtered_population":159,
        "rows_written":len(out),
        "fixed_atm_time":a.fixed_atm_time,
        "missing_fixed_atm":missing_fixed_atm,
        "missing_checkpoint":missing_checkpoint,
        "fixed_pm2_rows":present("fixed_pm2"),
        "fixed_pm5_rows":present("fixed_pm5"),
        "missing_pm2":missing_pm2,
        "missing_pm5":missing_pm5,
        "winner_rows":sum(r["outcome_group"]=="WINNER" for r in out),
        "loser_rows":sum(r["outcome_group"]=="LOSER" for r in out),
        "integrity":{
            "fixed_atm_once_per_session":True,
            "fixed_atm_checkpoint":a.fixed_atm_time,
            "same_physical_strikes_current_vs_previous":True,
            "event_checkpoint_source":"oi_vwap_checkpoint_timestamp",
            "oos_e_f_g_h_used":False,
            "threshold_tuning_performed":False,
            "strategy_rule_changed":False,
            "fresh_oos_consumed":False,
        },
        "output":a.output,
    },indent=2))


if __name__=="__main__":
    main()
