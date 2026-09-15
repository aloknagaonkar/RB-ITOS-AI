from __future__ import annotations

import argparse, csv, json
from datetime import datetime
from pathlib import Path
from typing import Any

SESSION_DATE = "2026-08-25"
RESEARCH_VERSION = "MIDPOINT_AUG25_OI_MAGNITUDE_REPLAY_V1"
MORNING = ["09:20","09:25","09:30","09:35","09:40"]
AFTERNOON = ["13:35","13:40","13:45","13:50","13:55","14:00","14:05","14:10"]

def num(v: Any):
    if v in ("", None): return None
    try: return float(v)
    except Exception: return None

def parse_ts(v: Any):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception: return None

def pct(cur, prev):
    if cur is None or prev in (None, 0): return None
    return (cur-prev)/prev*100.0

def state(price_pct, oi_pct):
    if price_pct is None or oi_pct is None: return "UNAVAILABLE"
    if price_pct > 0 and oi_pct > 0: return "LONG_BUILDUP"
    if price_pct < 0 and oi_pct > 0: return "SHORT_BUILDUP"
    if price_pct > 0 and oi_pct < 0: return "SHORT_COVERING"
    if price_pct < 0 and oi_pct < 0: return "LONG_UNWINDING"
    return "NEUTRAL"

def load_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def infer(rows):
    keys=set().union(*(r.keys() for r in rows))
    cand={
      "timestamp":["timestamp","datetime","provider_timestamp","time"],
      "session_date":["session_date","date"],
      "strike":["strike","strike_price"],
      "strike_offset":["strike_offset","offset"],
      "moving_atm":["moving_atm","atm","atm_strike"],
      "ce_oi":["ce_oi","call_oi","ce_open_interest","call_open_interest"],
      "pe_oi":["pe_oi","put_oi","pe_open_interest","put_open_interest"],
      "ce_price":["ce_close","ce_price","call_close","call_price"],
      "pe_price":["pe_close","pe_price","put_close","put_price"],
    }
    out={}
    for k,opts in cand.items():
        for o in opts:
            if o in keys:
                out[k]=o; break
    req=["timestamp","strike","strike_offset","moving_atm","ce_oi","pe_oi","ce_price","pe_price"]
    miss=[k for k in req if k not in out]
    if miss:
        raise RuntimeError("Missing raw columns: "+", ".join(miss)+"\nAvailable:\n" + "\n".join(sorted(keys)))
    return out

def load_rows(path):
    raw=load_csv(path); cols=infer(raw); out=[]
    for r in raw:
        ts=parse_ts(r[cols["timestamp"]])
        if not ts: continue
        sess=r.get(cols.get("session_date",""),"") if "session_date" in cols else ts.date().isoformat()
        if (sess or ts.date().isoformat()) != SESSION_DATE: continue
        out.append({
          "timestamp":ts,
          "strike":num(r[cols["strike"]]),
          "strike_offset":num(r[cols["strike_offset"]]),
          "moving_atm":num(r[cols["moving_atm"]]),
          "ce_oi":num(r[cols["ce_oi"]]),
          "pe_oi":num(r[cols["pe_oi"]]),
          "ce_price":num(r[cols["ce_price"]]),
          "pe_price":num(r[cols["pe_price"]]),
        })
    out.sort(key=lambda x:(x["timestamp"], x["strike"] or -1))
    return out, cols

def latest_snapshot(rows, hm):
    h,m=map(int,hm.split(":"))
    xs=[r for r in rows if (r["timestamp"].hour,r["timestamp"].minute) <= (h,m)]
    if not xs: return []
    t=max(r["timestamp"] for r in xs)
    return [r for r in xs if r["timestamp"]==t]

def prev_snapshot(rows, cur_ts):
    xs=[r for r in rows if r["timestamp"] < cur_ts]
    if not xs: return []
    t=max(r["timestamp"] for r in xs)
    return [r for r in xs if r["timestamp"]==t]

def map_strike(rows):
    return {r["strike"]:r for r in rows if r["strike"] is not None}

def one_pair(r,p):
    ce_oi_pct=pct(r["ce_oi"], p["ce_oi"] if p else None)
    pe_oi_pct=pct(r["pe_oi"], p["pe_oi"] if p else None)
    ce_px_pct=pct(r["ce_price"], p["ce_price"] if p else None)
    pe_px_pct=pct(r["pe_price"], p["pe_price"] if p else None)
    return {
      "strike":r["strike"],"strike_offset":r["strike_offset"],
      "ce_oi":r["ce_oi"],"pe_oi":r["pe_oi"],
      "ce_oi_change_abs":None if not p else r["ce_oi"]-p["ce_oi"] if r["ce_oi"] is not None and p["ce_oi"] is not None else None,
      "pe_oi_change_abs":None if not p else r["pe_oi"]-p["pe_oi"] if r["pe_oi"] is not None and p["pe_oi"] is not None else None,
      "ce_oi_change_pct":ce_oi_pct,"pe_oi_change_pct":pe_oi_pct,
      "ce_price_change_pct":ce_px_pct,"pe_price_change_pct":pe_px_pct,
      "ce_state":state(ce_px_pct,ce_oi_pct),"pe_state":state(pe_px_pct,pe_oi_pct)
    }

def summarize(cur, prev, maxoff):
    pm=map_strike(prev)
    chosen=[r for r in cur if r["strike_offset"] is not None and abs(r["strike_offset"])<=maxoff]
    details=[one_pair(r,pm.get(r["strike"])) for r in sorted(chosen,key=lambda x:x["strike_offset"])]
    ce=sum(r["ce_oi"] or 0 for r in chosen); pe=sum(r["pe_oi"] or 0 for r in chosen)
    common=[(r,pm.get(r["strike"])) for r in chosen if pm.get(r["strike"])]
    pce=sum(p["ce_oi"] or 0 for _,p in common); ppe=sum(p["pe_oi"] or 0 for _,p in common)
    return {
      "ce_oi":ce,"pe_oi":pe,
      "ce_oi_change_abs": ce-pce if common else None,
      "pe_oi_change_abs": pe-ppe if common else None,
      "ce_oi_change_pct": pct(ce,pce) if common else None,
      "pe_oi_change_pct": pct(pe,ppe) if common else None,
      "oi_pcr": pe/ce if ce else None,
      "strikes":details
    }

def checkpoint(rows, hm):
    cur=latest_snapshot(rows,hm)
    if not cur: return {"time":hm,"available":False}
    prev=prev_snapshot(rows,cur[0]["timestamp"])
    atm=[r for r in cur if r["strike_offset"]==0]
    pm=map_strike(prev)
    atm_obj=one_pair(atm[0], pm.get(atm[0]["strike"])) if atm else {"available":False}
    return {
      "time":hm,
      "source_timestamp":cur[0]["timestamp"].isoformat(),
      "previous_source_timestamp":prev[0]["timestamp"].isoformat() if prev else None,
      "atm":atm_obj,
      "atm_pm2":summarize(cur,prev,2),
    }

def add_accel(seq):
    for scope in ("atm","atm_pm2"):
        prev_ce=prev_pe=None
        for cp in seq:
            obj=cp.get(scope,{})
            ce=obj.get("ce_oi_change_pct"); pe=obj.get("pe_oi_change_pct")
            obj["ce_oi_change_pct_acceleration"]=None if ce is None or prev_ce is None else ce-prev_ce
            obj["pe_oi_change_pct_acceleration"]=None if pe is None or prev_pe is None else pe-prev_pe
            if ce is not None: prev_ce=ce
            if pe is not None: prev_pe=pe

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--positioning",required=True)
    ap.add_argument("--output",required=True)
    a=ap.parse_args()

    rows,cols=load_rows(a.positioning)
    morning=[checkpoint(rows,t) for t in MORNING]
    afternoon=[checkpoint(rows,t) for t in AFTERNOON]
    add_accel(morning); add_accel(afternoon)

    out={
      "research_version":RESEARCH_VERSION,
      "session_date":SESSION_DATE,
      "source_columns":cols,
      "morning_failed_setup":morning,
      "afternoon_successful_transition":afternoon,
      "integrity":{
        "retrospective_case_study":True,
        "threshold_tuning_performed":False,
        "strategy_rule_changed":False,
        "fresh_oos_consumed":False,
        "oos_e_f_g_h_used":False,
        "paper_or_live_order_emission_allowed":False
      }
    }
    p=Path(a.output); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(out,indent=2,allow_nan=False)+"\n",encoding="utf-8")

    def compact(seq):
        z=[]
        for cp in seq:
            atm=cp.get("atm",{}); band=cp.get("atm_pm2",{})
            z.append({
              "time":cp["time"],"source_timestamp":cp.get("source_timestamp"),
              "atm_strike":atm.get("strike"),
              "atm_ce_oi":atm.get("ce_oi"),"atm_ce_oi_change_pct":atm.get("ce_oi_change_pct"),
              "atm_pe_oi":atm.get("pe_oi"),"atm_pe_oi_change_pct":atm.get("pe_oi_change_pct"),
              "atm_ce_state":atm.get("ce_state"),"atm_pe_state":atm.get("pe_state"),
              "pm2_ce_oi_change_pct":band.get("ce_oi_change_pct"),
              "pm2_pe_oi_change_pct":band.get("pe_oi_change_pct"),
              "pm2_oi_pcr":band.get("oi_pcr")
            })
        return z

    print(json.dumps({"morning":compact(morning),"afternoon":compact(afternoon),"output":str(p)},indent=2))

if __name__=="__main__":
    main()
