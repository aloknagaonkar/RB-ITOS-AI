from __future__ import annotations

"""
OI_PATTERN_LIBRARY_90D_V1

Research-only historical pattern library + current-day similarity scanner.

Historical scope:
- latest N unique sessions from supplied development positioning files
- intended for TRAIN + OOS_A-D only
- no OOS_E/F/G/H
- every exact 5-minute checkpoint with T-5m available

Current day:
- supplied separately as an external reference
- never used to fit historical distributions
- no current-day forward outcome required

Primary comparison features:
- moving ATM ±2 CE/PE signed OI change
- CE/PE 5m OI percentage change
- total absolute OI activity
- PCR + PCR change
- ATM CE/PE price change when available
- derived CE/PE state (LB/SB/SC/LU) when price fields exist
- fixed 09:20 ATM ±2 context when available

Historical forward spot outcomes:
- +5m, +10m, +15m when exact spot checkpoint exists

No trade signal / threshold / paper / live action.
"""

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

VERSION = "OI_PATTERN_LIBRARY_90D_V1"
FORBIDDEN = {"OOS_E","OOS_F","OOS_G","OOS_H"}


def f(v):
    if v in ("", None): return None
    try: return float(v)
    except Exception: return None


def ts(v):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception: return None


def pct(cur, prev):
    if cur is None or prev in (None,0): return None
    return (cur-prev)/prev*100.0


def read_csv(path):
    with Path(path).open(newline="",encoding="utf-8-sig") as h:
        return list(csv.DictReader(h))


def detect(rows):
    keys=set().union(*(r.keys() for r in rows))
    def first(*xs): return next((x for x in xs if x in keys),None)
    c={
        "timestamp":first("timestamp","datetime","provider_timestamp","time"),
        "session_date":first("session_date","date"),
        "spot":first("spot","underlying_spot"),
        "strike":first("strike","strike_price"),
        "offset":first("strike_offset","offset"),
        "atm":first("moving_atm","atm","atm_strike"),
        "ce_oi":first("ce_oi","call_oi","ce_open_interest","call_open_interest"),
        "pe_oi":first("pe_oi","put_oi","pe_open_interest","put_open_interest"),
        "ce_close":first("ce_close","call_close","ce_price","call_price","ce_premium"),
        "pe_close":first("pe_close","put_close","pe_price","put_price","pe_premium"),
    }
    miss=[k for k in ("timestamp","spot","strike","offset","atm","ce_oi","pe_oi") if c[k] is None]
    if miss: raise RuntimeError("Missing positioning columns: "+", ".join(miss))
    return c


def snapshots(rows,c):
    out={}
    for r in rows:
        t=ts(r.get(c["timestamp"]))
        if t: out.setdefault(t,[]).append(r)
    return out


def atm(rows,c):
    xs=[r for r in rows if f(r.get(c["offset"]))==0]
    return f(xs[0].get(c["atm"])) if xs else None


def atm_row(rows,c,center):
    for r in rows:
        if f(r.get(c["strike"]))==center:
            return r
    return None


def fixed_atm(snaps,c,date_s,hhmm="09:20"):
    hh,mm=map(int,hhmm.split(":"))
    for t,rows in snaps.items():
        if t.date().isoformat()==date_s and t.hour==hh and t.minute==mm:
            return atm(rows,c)
    return None


def agg(cur,prev,c,center,width=2,step=50.0):
    wanted={center+i*step for i in range(-width,width+1)}
    cm={f(r[c["strike"]]):r for r in cur}
    pm={f(r[c["strike"]]):r for r in prev}
    common=sorted(wanted & set(cm) & set(pm))
    if not common: return None
    ce0=sum(f(pm[s][c["ce_oi"]]) or 0 for s in common)
    ce1=sum(f(cm[s][c["ce_oi"]]) or 0 for s in common)
    pe0=sum(f(pm[s][c["pe_oi"]]) or 0 for s in common)
    pe1=sum(f(cm[s][c["pe_oi"]]) or 0 for s in common)
    return {
        "ce_oi_previous":ce0,"ce_oi_current":ce1,
        "pe_oi_previous":pe0,"pe_oi_current":pe1,
        "ce_delta":ce1-ce0,"pe_delta":pe1-pe0,
        "ce_pct":pct(ce1,ce0),"pe_pct":pct(pe1,pe0),
        "activity":abs(ce1-ce0)+abs(pe1-pe0),
        "pcr_previous":pe0/ce0 if ce0 else None,
        "pcr_current":pe1/ce1 if ce1 else None,
        "strike_count":len(common),
    }


def state(price_pct, oi_pct):
    if price_pct is None or oi_pct is None: return "UNAVAILABLE"
    if price_pct>0 and oi_pct>0: return "LONG_BUILDUP"
    if price_pct<0 and oi_pct>0: return "SHORT_BUILDUP"
    if price_pct>0 and oi_pct<0: return "SHORT_COVERING"
    if price_pct<0 and oi_pct<0: return "LONG_UNWINDING"
    return "NEUTRAL"


def checkpoint_features(t,cur,prev,c,fixed_center=None):
    moving=atm(cur,c)
    if moving is None: return None
    m=agg(cur,prev,c,moving,2)
    if not m: return None

    ar_cur=atm_row(cur,c,moving)
    ar_prev=atm_row(prev,c,moving)
    ce_price_pct=pe_price_pct=None
    if ar_cur and ar_prev and c["ce_close"]:
        ce_price_pct=pct(f(ar_cur.get(c["ce_close"])),f(ar_prev.get(c["ce_close"])))
    if ar_cur and ar_prev and c["pe_close"]:
        pe_price_pct=pct(f(ar_cur.get(c["pe_close"])),f(ar_prev.get(c["pe_close"])))

    fixed=agg(cur,prev,c,fixed_center,2) if fixed_center is not None else None
    spot=f(cur[0].get(c["spot"])) if cur else None

    return {
        "timestamp":t.isoformat(),
        "session_date":t.date().isoformat(),
        "time":t.strftime("%H:%M"),
        "spot":spot,
        "moving_atm":moving,
        "fixed_atm":fixed_center,
        "m_ce_oi":m["ce_oi_current"],
        "m_pe_oi":m["pe_oi_current"],
        "m_ce_delta":m["ce_delta"],
        "m_pe_delta":m["pe_delta"],
        "m_ce_pct":m["ce_pct"],
        "m_pe_pct":m["pe_pct"],
        "m_activity":m["activity"],
        "m_pcr":m["pcr_current"],
        "m_pcr_change":(
            m["pcr_current"]-m["pcr_previous"]
            if m["pcr_current"] is not None and m["pcr_previous"] is not None else None
        ),
        "atm_ce_price_pct":ce_price_pct,
        "atm_pe_price_pct":pe_price_pct,
        "ce_state":state(ce_price_pct,m["ce_pct"]),
        "pe_state":state(pe_price_pct,m["pe_pct"]),
        "f_ce_delta":fixed["ce_delta"] if fixed else None,
        "f_pe_delta":fixed["pe_delta"] if fixed else None,
        "f_activity":fixed["activity"] if fixed else None,
        "f_pcr":fixed["pcr_current"] if fixed else None,
    }


def exact_forward_spot(snaps,c,t,mins):
    rows=snaps.get(t+timedelta(minutes=mins))
    if not rows:return None
    return f(rows[0].get(c["spot"]))


FEATURES=[
    "m_ce_delta","m_pe_delta","m_ce_pct","m_pe_pct",
    "m_activity","m_pcr","m_pcr_change",
    "atm_ce_price_pct","atm_pe_price_pct",
]


def robust_stats(rows):
    out={}
    for name in FEATURES:
        vals=sorted(f(r.get(name)) for r in rows if f(r.get(name)) is not None)
        if not vals: continue
        med=median(vals)
        q1=vals[int((len(vals)-1)*.25)]
        q3=vals[int((len(vals)-1)*.75)]
        scale=q3-q1
        if scale==0:
            scale=max(abs(med),1.0)
        out[name]=(med,scale)
    return out


def distance(a,b,stats):
    parts=[]
    for name,(med,scale) in stats.items():
        av=f(a.get(name)); bv=f(b.get(name))
        if av is None or bv is None: continue
        parts.append(((av-bv)/scale)**2)
    if not parts:return None
    return math.sqrt(sum(parts)/len(parts))


def directional_label(r):
    """Descriptive only, not a strategy rule."""
    ce=r.get("ce_state"); pe=r.get("pe_state")
    if ce in {"SHORT_COVERING","LONG_UNWINDING"} and pe=="LONG_BUILDUP":
        return "BULLISH_OI_TRANSITION"
    if ce=="SHORT_BUILDUP" and pe in {"LONG_BUILDUP","LONG_UNWINDING"}:
        return "BEARISH_OI_TRANSITION"
    if r.get("m_ce_delta") is not None and r.get("m_pe_delta") is not None:
        if r["m_ce_delta"]<0 and r["m_pe_delta"]>0:
            return "BULLISH_QUANTITY_DIVERGENCE"
        if r["m_ce_delta"]>0 and r["m_pe_delta"]<0:
            return "BEARISH_QUANTITY_DIVERGENCE"
    return "MIXED"


def build_rows(block,path,latest_dates=None,fixed_time="09:20"):
    rows=read_csv(path); c=detect(rows); sn=snapshots(rows,c)
    result=[]
    bydate=defaultdict(list)
    for t in sn: bydate[t.date().isoformat()].append(t)
    for date_s,times in bydate.items():
        if latest_dates is not None and date_s not in latest_dates: continue
        fa=fixed_atm(sn,c,date_s,fixed_time)
        for t in sorted(times):
            # exact completed 5m checkpoints only
            if t.minute % 5 != 0: continue
            prev=sn.get(t-timedelta(minutes=5))
            if not prev: continue
            feat=checkpoint_features(t,sn[t],prev,c,fa)
            if not feat: continue
            feat["block"]=block
            feat["pattern_family"]=directional_label(feat)
            spot=feat.get("spot")
            for mins in (5,10,15):
                fs=exact_forward_spot(sn,c,t,mins)
                feat[f"forward_{mins}m_points"]=(fs-spot) if fs is not None and spot is not None else None
            result.append(feat)
    return result


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--historical-positioning",action="append",required=True,
                    help="BLOCK|path.csv; intended TRAIN/OOS_A-D")
    ap.add_argument("--current-positioning",required=True)
    ap.add_argument("--current-block",default="CURRENT_DAY_EXTERNAL")
    ap.add_argument("--latest-sessions",type=int,default=90)
    ap.add_argument("--fixed-atm-time",default="09:20")
    ap.add_argument("--top-n",type=int,default=10)
    ap.add_argument("--output",required=True)
    a=ap.parse_args()

    hist_specs=[]
    all_dates=set()
    for spec in a.historical_positioning:
        block,path=spec.split("|",1)
        if block in FORBIDDEN:
            raise RuntimeError(f"Forbidden historical block: {block}")
        hist_specs.append((block,path))
        rows=read_csv(path); c=detect(rows)
        for r in rows:
            t=ts(r.get(c["timestamp"]))
            if t: all_dates.add(t.date().isoformat())

    latest=set(sorted(all_dates)[-a.latest_sessions:])
    historical=[]
    for block,path in hist_specs:
        historical.extend(build_rows(block,path,latest,a.fixed_atm_time))

    current=build_rows(a.current_block,a.current_positioning,None,a.fixed_atm_time)
    stats=robust_stats(historical)

    matches=[]
    for cur in current:
        scored=[]
        for h in historical:
            d=distance(cur,h,stats)
            if d is None: continue
            scored.append((d,h))
        scored.sort(key=lambda x:x[0])
        top=[]
        for d,h in scored[:a.top_n]:
            top.append({
                "distance":d,
                "session_date":h["session_date"],
                "time":h["time"],
                "block":h["block"],
                "pattern_family":h["pattern_family"],
                "m_activity":h["m_activity"],
                "m_ce_delta":h["m_ce_delta"],
                "m_pe_delta":h["m_pe_delta"],
                "m_ce_pct":h["m_ce_pct"],
                "m_pe_pct":h["m_pe_pct"],
                "m_pcr":h["m_pcr"],
                "ce_state":h["ce_state"],
                "pe_state":h["pe_state"],
                "forward_5m_points":h["forward_5m_points"],
                "forward_10m_points":h["forward_10m_points"],
                "forward_15m_points":h["forward_15m_points"],
            })
        matches.append({
            "current":cur,
            "nearest_historical":top,
        })

    result={
        "research_version":VERSION,
        "historical_session_count":len(latest),
        "historical_first_session":min(latest) if latest else None,
        "historical_last_session":max(latest) if latest else None,
        "historical_checkpoint_count":len(historical),
        "current_checkpoint_count":len(current),
        "feature_names_used_for_similarity":[k for k in FEATURES if k in stats],
        "pattern_family_counts":dict(__import__("collections").Counter(r["pattern_family"] for r in historical)),
        "current_pattern_family_counts":dict(__import__("collections").Counter(r["pattern_family"] for r in current)),
        "matches":matches,
        "integrity":{
            "current_day_external_only":True,
            "current_day_used_to_fit_scaling":False,
            "historical_blocks_forbidden_e_f_g_h":True,
            "exact_t_minus_5m_same_physical_strikes":True,
            "moving_atm_pm2_primary":True,
            "fixed_atm_pm2_context":True,
            "strategy_rule_changed":False,
            "paper_or_live_action":False,
        }
    }
    p=Path(a.output);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({
        "research_version":VERSION,
        "historical_session_count":result["historical_session_count"],
        "historical_checkpoint_count":len(historical),
        "current_checkpoint_count":len(current),
        "historical_range":[result["historical_first_session"],result["historical_last_session"]],
        "pattern_family_counts":result["pattern_family_counts"],
        "current_pattern_family_counts":result["current_pattern_family_counts"],
        "output":a.output,
    },indent=2))


if __name__=="__main__":
    main()
