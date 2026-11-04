from __future__ import annotations

"""
MIDPOINT_OI_PM5_FEATURE_EXTRACTOR_V1

Research-only extractor for ATM ±5 strikes.

Uses the same frozen global exemplar population and causal
oi_vwap_checkpoint_timestamp as the validated ±2 study.

Allowed: TRAIN + OOS_A-D
Forbidden: OOS_E/F/G/H
"""

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ALLOWED={"TRAIN","OOS_A","OOS_B","OOS_C","OOS_D"}
FORBIDDEN={"OOS_E","OOS_F","OOS_G","OOS_H"}
WIN_BUCKETS={"EXCELLENT_5M_GE_10","GOOD_5M_3_TO_10"}
LOSS_BUCKETS={"LOSS_5M_0_TO_MINUS5","LARGE_LOSS_5M_LE_MINUS5"}
SMALL={"SMALL_WIN_5M_0_TO_3"}
VERSION="MIDPOINT_OI_PM5_FEATURE_EXTRACTOR_V1"


def num(v: Any):
    if v in ("",None): return None
    try: return float(v)
    except Exception: return None


def ts(v):
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
    def first(*names):
        return next((n for n in names if n in keys),None)
    c={
        "timestamp":first("timestamp","datetime","provider_timestamp","time"),
        "strike":first("strike","strike_price"),
        "offset":first("strike_offset","offset"),
        "atm":first("moving_atm","atm","atm_strike"),
        "ce_oi":first("ce_oi","call_oi","ce_open_interest","call_open_interest"),
        "pe_oi":first("pe_oi","put_oi","pe_open_interest","put_open_interest"),
    }
    missing=[k for k,v in c.items() if v is None]
    if missing: raise RuntimeError("Missing positioning columns: "+", ".join(missing))
    return c


def snapshots(rows,col):
    d={}
    for r in rows:
        t=ts(r.get(col))
        if t: d.setdefault(t,[]).append(r)
    return d


def outcome(e):
    b=str(e.get("quality_bucket") or "")
    if b in WIN_BUCKETS: return "WINNER"
    if b in LOSS_BUCKETS: return "LOSER"
    if b in SMALL: return "SMALL_WIN"
    return None


def band(cur,prev,c,center,width=5,step=50):
    wanted={center+i*step for i in range(-width,width+1)}
    cm={num(r[c["strike"]]):r for r in cur}
    pm={num(r[c["strike"]]):r for r in prev}
    common=sorted(wanted & set(cm) & set(pm))
    if not common: return {}

    ce0=sum(num(pm[s][c["ce_oi"]]) or 0 for s in common)
    ce1=sum(num(cm[s][c["ce_oi"]]) or 0 for s in common)
    pe0=sum(num(pm[s][c["pe_oi"]]) or 0 for s in common)
    pe1=sum(num(cm[s][c["pe_oi"]]) or 0 for s in common)

    return {
        "pm5_ce_oi_previous":ce0,
        "pm5_ce_oi":ce1,
        "pm5_pe_oi_previous":pe0,
        "pm5_pe_oi":pe1,
        "pm5_ce_change_abs":ce1-ce0,
        "pm5_pe_change_abs":pe1-pe0,
        "pm5_ce_abs_change":abs(ce1-ce0),
        "pm5_pe_abs_change":abs(pe1-pe0),
        "pm5_total_oi":ce1+pe1,
        "pm5_total_abs_change":abs(ce1-ce0)+abs(pe1-pe0),
        "pm5_ce_oi_change_pct_5m":pct(ce1,ce0),
        "pm5_pe_oi_change_pct_5m":pct(pe1,pe0),
        "pm5_oi_pcr_previous":pe0/ce0 if ce0 else None,
        "pm5_oi_pcr":pe1/ce1 if ce1 else None,
        "pm5_common_strike_count":len(common),
        "pm5_common_strikes":";".join(str(int(s)) for s in common),
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--events-json",required=True)
    ap.add_argument("--positioning",action="append",required=True)
    ap.add_argument("--output",required=True)
    a=ap.parse_args()

    doc=json.loads(Path(a.events_json).read_text(encoding="utf-8"))
    events=doc.get("events")
    if not isinstance(events,list) or len(events)!=184:
        raise RuntimeError(f"Expected 184 global exemplar events, got {None if not isinstance(events,list) else len(events)}")

    pos={}
    for spec in a.positioning:
        block,path=spec.split("|",1)
        if block in FORBIDDEN: raise RuntimeError(f"Forbidden block {block}")
        if block not in ALLOWED: continue
        rows=read_csv(path); c=detect(rows)
        pos[block]=(c,snapshots(rows,c["timestamp"]))

    out=[]
    excluded_small=0
    for e in events:
        block=str(e.get("block",""))
        if block in FORBIDDEN: raise RuntimeError(f"Forbidden event block {block}")
        if block not in ALLOWED: continue
        grp=outcome(e)
        if grp=="SMALL_WIN":
            excluded_small+=1; continue
        if grp not in {"WINNER","LOSER"}: continue

        cp=ts(e.get("oi_vwap_checkpoint_timestamp"))
        sig=ts(e.get("signal_timestamp"))
        if not cp or not sig or block not in pos: continue
        prev=cp-timedelta(minutes=5)
        c,snaps=pos[block]
        cur=snaps.get(cp,[]); prv=snaps.get(prev,[])
        if not cur or not prv: continue

        atm_rows=[r for r in cur if num(r[c["offset"]])==0]
        if not atm_rows: continue
        atm=num(atm_rows[0][c["atm"]])
        if atm is None: continue

        b=band(cur,prv,c,atm,5,50)
        if not b: continue
        econ=e.get("option_economics") or {}

        row={
            "block":block,
            "session_date":e.get("session_date"),
            "direction":e.get("direction"),
            "setup_type":e.get("setup_type"),
            "decision_family":e.get("decision_family"),
            "signal_timestamp":sig.isoformat(),
            "checkpoint_timestamp":cp.isoformat(),
            "previous_checkpoint_timestamp":prev.isoformat(),
            "quality_bucket":e.get("quality_bucket"),
            "outcome_group":grp,
            "net_5m_pct":num(econ.get("net_5m_pct")),
            "atm_strike":atm,
        }
        row.update(b)
        out.append(row)

    if len(out)!=159:
        raise RuntimeError(f"Expected 159 outcome-filtered rows, wrote {len(out)}")

    p=Path(a.output); p.parent.mkdir(parents=True,exist_ok=True)
    fields=[]
    for r in out:
        for k in r:
            if k not in fields: fields.append(k)
    with p.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(out)

    print(json.dumps({
        "research_version":VERSION,
        "global_event_count":184,
        "excluded_small_win_count":excluded_small,
        "rows_written":len(out),
        "winner_count":sum(r["outcome_group"]=="WINNER" for r in out),
        "loser_count":sum(r["outcome_group"]=="LOSER" for r in out),
        "min_common_strikes":min(r["pm5_common_strike_count"] for r in out),
        "max_common_strikes":max(r["pm5_common_strike_count"] for r in out),
        "integrity":{
            "band":"ATM_PLUS_MINUS_5",
            "same_physical_strikes":True,
            "checkpoint_source":"oi_vwap_checkpoint_timestamp",
            "oos_e_f_g_h_used":False,
            "threshold_tuning_performed":False,
        },
        "output":a.output,
    },indent=2))


if __name__=="__main__":
    main()
