from __future__ import annotations

"""
MIDPOINT_AUG25_OI_MAGNITUDE_REPLAY_V1_FIX1

Fixes:
- exact 5-minute checkpoint-to-checkpoint OI deltas
- same-strike comparison across checkpoints
- explicit ATM-shift detection
- consistent checkpoint timing
"""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

SESSION_DATE = "2026-08-25"
RESEARCH_VERSION = "MIDPOINT_AUG25_OI_MAGNITUDE_REPLAY_V1_FIX1"

MORNING = ["09:20","09:25","09:30","09:35","09:40"]
AFTERNOON = ["13:35","13:40","13:45","13:50","13:55","14:00","14:05","14:10"]


def num(v: Any) -> float | None:
    if v in ("", None):
        return None
    try:
        return float(v)
    except Exception:
        return None


def parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception:
        return None


def pct(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev in (None, 0):
        return None
    return (cur-prev)/prev*100.0


def state(price_pct: float | None, oi_pct: float | None) -> str:
    if price_pct is None or oi_pct is None:
        return "UNAVAILABLE"
    if price_pct > 0 and oi_pct > 0:
        return "LONG_BUILDUP"
    if price_pct < 0 and oi_pct > 0:
        return "SHORT_BUILDUP"
    if price_pct > 0 and oi_pct < 0:
        return "SHORT_COVERING"
    if price_pct < 0 and oi_pct < 0:
        return "LONG_UNWINDING"
    return "NEUTRAL"


def load_csv(path: Path) -> list[dict[str,str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def infer(rows: list[dict[str,str]]) -> dict[str,str]:
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
                out[k]=o
                break
    req=["timestamp","strike","strike_offset","moving_atm","ce_oi","pe_oi","ce_price","pe_price"]
    miss=[k for k in req if k not in out]
    if miss:
        raise RuntimeError("Missing raw columns: "+", ".join(miss)+"\nAvailable:\n"+"\n".join(sorted(keys)))
    return out


def load_rows(path: Path):
    raw=load_csv(path)
    cols=infer(raw)
    out=[]
    for r in raw:
        ts=parse_ts(r[cols["timestamp"]])
        if not ts:
            continue
        sess=r.get(cols.get("session_date",""),"") if "session_date" in cols else ts.date().isoformat()
        if (sess or ts.date().isoformat()) != SESSION_DATE:
            continue
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
    out.sort(key=lambda x:(x["timestamp"],x["strike"] or -1))
    return out, cols


def exact_snapshot(rows, hm: str):
    hh,mm=map(int,hm.split(":"))
    xs=[r for r in rows if r["timestamp"].hour==hh and r["timestamp"].minute==mm]
    if not xs:
        return []
    ts=max(r["timestamp"] for r in xs)
    return [r for r in xs if r["timestamp"]==ts]


def by_strike(rows):
    return {r["strike"]:r for r in rows if r["strike"] is not None}


def compare_pair(cur, prev):
    ce_oi_pct=pct(cur["ce_oi"], prev["ce_oi"] if prev else None)
    pe_oi_pct=pct(cur["pe_oi"], prev["pe_oi"] if prev else None)
    ce_px_pct=pct(cur["ce_price"], prev["ce_price"] if prev else None)
    pe_px_pct=pct(cur["pe_price"], prev["pe_price"] if prev else None)
    return {
        "strike":cur["strike"],
        "ce_oi_previous":prev["ce_oi"] if prev else None,
        "ce_oi_current":cur["ce_oi"],
        "ce_oi_change_abs":None if not prev or cur["ce_oi"] is None or prev["ce_oi"] is None else cur["ce_oi"]-prev["ce_oi"],
        "ce_oi_change_pct_5m":ce_oi_pct,
        "pe_oi_previous":prev["pe_oi"] if prev else None,
        "pe_oi_current":cur["pe_oi"],
        "pe_oi_change_abs":None if not prev or cur["pe_oi"] is None or prev["pe_oi"] is None else cur["pe_oi"]-prev["pe_oi"],
        "pe_oi_change_pct_5m":pe_oi_pct,
        "ce_price_change_pct_5m":ce_px_pct,
        "pe_price_change_pct_5m":pe_px_pct,
        "ce_state_derived":state(ce_px_pct,ce_oi_pct),
        "pe_state_derived":state(pe_px_pct,pe_oi_pct),
    }


def aggregate_same_strikes(cur_rows, prev_rows, center_atm, width=2):
    step=50.0
    wanted={center_atm + i*step for i in range(-width,width+1)}
    cm=by_strike(cur_rows)
    pm=by_strike(prev_rows)
    common=sorted(wanted & set(cm) & set(pm))
    if not common:
        return {"available":False,"common_strike_count":0,"common_strikes":[]}

    cur_ce=sum(cm[s]["ce_oi"] or 0 for s in common)
    prev_ce=sum(pm[s]["ce_oi"] or 0 for s in common)
    cur_pe=sum(cm[s]["pe_oi"] or 0 for s in common)
    prev_pe=sum(pm[s]["pe_oi"] or 0 for s in common)

    return {
        "available":True,
        "common_strike_count":len(common),
        "common_strikes":common,
        "ce_oi_previous":prev_ce,
        "ce_oi_current":cur_ce,
        "ce_oi_change_abs":cur_ce-prev_ce,
        "ce_oi_change_pct_5m":pct(cur_ce,prev_ce),
        "pe_oi_previous":prev_pe,
        "pe_oi_current":cur_pe,
        "pe_oi_change_abs":cur_pe-prev_pe,
        "pe_oi_change_pct_5m":pct(cur_pe,prev_pe),
        "oi_pcr_previous":prev_pe/prev_ce if prev_ce else None,
        "oi_pcr_current":cur_pe/cur_ce if cur_ce else None,
        "oi_pcr_change":(cur_pe/cur_ce-prev_pe/prev_ce) if cur_ce and prev_ce else None,
    }


def checkpoint(rows, hm: str, prev_hm: str | None):
    cur=exact_snapshot(rows,hm)
    if not cur:
        return {"checkpoint":hm,"available":False,"reason":"missing_exact_snapshot"}
    prev=exact_snapshot(rows,prev_hm) if prev_hm else []

    cur_atm_rows=[r for r in cur if r["strike_offset"]==0]
    cur_atm=cur_atm_rows[0]["moving_atm"] if cur_atm_rows else None

    prev_atm_rows=[r for r in prev if r["strike_offset"]==0]
    prev_atm=prev_atm_rows[0]["moving_atm"] if prev_atm_rows else None

    pm=by_strike(prev)
    atm_same_strike = None
    if cur_atm is not None:
        cur_match=by_strike(cur).get(cur_atm)
        prev_match=pm.get(cur_atm)
        if cur_match:
            atm_same_strike=compare_pair(cur_match,prev_match)

    return {
        "checkpoint":hm,
        "previous_checkpoint":prev_hm,
        "source_timestamp":cur[0]["timestamp"].isoformat(),
        "previous_source_timestamp":prev[0]["timestamp"].isoformat() if prev else None,
        "available":True,
        "current_atm":cur_atm,
        "previous_atm":prev_atm,
        "atm_shifted":bool(prev and cur_atm != prev_atm),
        "atm_same_strike_comparison":atm_same_strike,
        "band_atm_pm2_same_strikes":aggregate_same_strikes(cur,prev,cur_atm,2) if prev and cur_atm is not None else {"available":False},
    }


def build_sequence(rows, times):
    out=[]
    for i,hm in enumerate(times):
        prev_hm=times[i-1] if i>0 else None
        out.append(checkpoint(rows,hm,prev_hm))
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--positioning",required=True)
    ap.add_argument("--output",required=True)
    a=ap.parse_args()

    rows,cols=load_rows(Path(a.positioning))
    morning=build_sequence(rows,MORNING)
    afternoon=build_sequence(rows,AFTERNOON)

    out={
        "research_version":RESEARCH_VERSION,
        "session_date":SESSION_DATE,
        "source_columns":cols,
        "morning_failed_setup":morning,
        "afternoon_successful_transition":afternoon,
        "integrity":{
            "exact_5m_checkpoint_comparison":True,
            "same_strike_comparison":True,
            "atm_shift_explicitly_flagged":True,
            "threshold_tuning_performed":False,
            "strategy_rule_changed":False,
            "fresh_oos_consumed":False,
            "oos_e_f_g_h_used":False,
            "paper_or_live_order_emission_allowed":False,
        }
    }

    p=Path(a.output)
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(out,indent=2,allow_nan=False)+"\n",encoding="utf-8")

    def compact(seq):
        x=[]
        for cp in seq:
            atm=cp.get("atm_same_strike_comparison") or {}
            band=cp.get("band_atm_pm2_same_strikes") or {}
            x.append({
                "checkpoint":cp.get("checkpoint"),
                "previous_checkpoint":cp.get("previous_checkpoint"),
                "current_atm":cp.get("current_atm"),
                "previous_atm":cp.get("previous_atm"),
                "atm_shifted":cp.get("atm_shifted"),
                "atm_ce_oi_change_pct_5m":atm.get("ce_oi_change_pct_5m"),
                "atm_pe_oi_change_pct_5m":atm.get("pe_oi_change_pct_5m"),
                "atm_ce_state":atm.get("ce_state_derived"),
                "atm_pe_state":atm.get("pe_state_derived"),
                "pm2_ce_oi_change_pct_5m":band.get("ce_oi_change_pct_5m"),
                "pm2_pe_oi_change_pct_5m":band.get("pe_oi_change_pct_5m"),
                "pm2_oi_pcr_previous":band.get("oi_pcr_previous"),
                "pm2_oi_pcr_current":band.get("oi_pcr_current"),
            })
        return x

    print(json.dumps({
        "research_version":RESEARCH_VERSION,
        "morning":compact(morning),
        "afternoon":compact(afternoon),
        "output":str(p),
    },indent=2))


if __name__=="__main__":
    main()
