from __future__ import annotations

"""
OI_PATTERN_CONTROL_TIMING_V1

Purpose
-------
Causal scan of the 90-session development universe (TRAIN + OOS_A-D only).

Answers:
1) On which completed 5-minute candle did OI evidence first become bullish/bearish?
2) How many similar pattern occurrences were seen during each session?
3) How often do the same patterns occur on the 54 mixed/control sessions?
4) What happened to price +5/+10/+15/+20 minutes after detection?
5) How do quantity, session-to-date OI, PCR and persistence differ across
   bullish trend, bearish trend and mixed days?

IMPORTANT:
- No fitted quantity threshold is used here.
- Pattern detection uses signs/direction only.
- The output preserves quantities so threshold discovery can follow.
- OOS_E/F/G/H are forbidden.
- Historical research only; no strategy/paper/live changes.

Definitions
-----------
Short-term:
  Moving ATM ±2, comparing the SAME physical five strikes at T vs T-5.

Session context:
  Fixed 09:20 ATM ±2, following the same five physical strikes all day.

Candidate bullish detection at completed candle T:
  - prior checkpoint 5m imbalance <= 0
  - current 5m imbalance > 0
  - current 5m PCR change > 0
  - current fixed-band session imbalance is improving vs previous checkpoint
  Optional persistence N means the bullish short-term sign remains > 0 for
  N consecutive completed checkpoints starting at the flip candle.

Candidate bearish detection is the exact mirror.

An occurrence is a fresh sign-transition event. Persistent checkpoints after the
same transition are not counted as new occurrences.
"""

import argparse, csv, json, statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

VERSION = "OI_PATTERN_CONTROL_TIMING_V1"
FORBIDDEN = {"OOS_E","OOS_F","OOS_G","OOS_H"}
HORIZONS = (5,10,15,20)

def f(v):
    if v in ("",None): return None
    try: return float(v)
    except Exception: return None

def dt(v): return datetime.fromisoformat(str(v).replace("Z","+00:00"))

def pct(cur,prev):
    if cur is None or prev in (None,0): return None
    return (cur-prev)/prev*100.0

def quantile(vals,q):
    xs=sorted(v for v in vals if v is not None)
    if not xs: return None
    if len(xs)==1: return xs[0]
    pos=(len(xs)-1)*q; lo=int(pos); hi=min(lo+1,len(xs)-1); frac=pos-lo
    return xs[lo]*(1-frac)+xs[hi]*frac

def stats(vals):
    xs=[v for v in vals if v is not None]
    return {"n":len(xs),"q25":quantile(xs,.25),
            "median":statistics.median(xs) if xs else None,
            "q75":quantile(xs,.75)}

def read_dates(path):
    return {x.strip() for x in Path(path).read_text().splitlines() if x.strip()}

def read_csv(path):
    with Path(path).open(newline="",encoding="utf-8-sig") as h:
        return list(csv.DictReader(h))

def detect(rows):
    keys=set().union(*(r.keys() for r in rows))
    def first(*xs): return next((x for x in xs if x in keys),None)
    c={"timestamp":first("timestamp"),"spot":first("spot","underlying_close","close"),
       "atm":first("moving_atm"),"strike":first("strike"),
       "offset":first("strike_offset"),"ce_oi":first("ce_open_interest","ce_oi"),
       "pe_oi":first("pe_open_interest","pe_oi")}
    missing=[k for k,v in c.items() if v is None]
    if missing: raise RuntimeError("Missing positioning columns: "+", ".join(missing))
    return c

def snapshots(rows,c):
    out={}
    for r in rows: out.setdefault(dt(r[c["timestamp"]]),[]).append(r)
    return out

def moving_atm(rows,c):
    for r in rows:
        if f(r[c["offset"]])==0: return f(r[c["atm"]])
    return None

def spot(rows,c):
    vals=[f(r[c["spot"]]) for r in rows if f(r[c["spot"]]) is not None]
    return vals[0] if vals else None

def aggregate(rows,c,strikes):
    mp={f(r[c["strike"]]):r for r in rows}
    strikes=list(strikes)
    if not all(s in mp for s in strikes): return None
    return {"ce_oi":sum(f(mp[s][c["ce_oi"]]) or 0 for s in strikes),
            "pe_oi":sum(f(mp[s][c["pe_oi"]]) or 0 for s in strikes)}

def short_term(cur,prev,c,center):
    strikes=[center+i*50.0 for i in range(-2,3)]
    a0=aggregate(prev,c,strikes); a1=aggregate(cur,c,strikes)
    if not a0 or not a1: return None
    ced=a1["ce_oi"]-a0["ce_oi"]; ped=a1["pe_oi"]-a0["pe_oi"]
    p0=a0["pe_oi"]/a0["ce_oi"] if a0["ce_oi"] else None
    p1=a1["pe_oi"]/a1["ce_oi"] if a1["ce_oi"] else None
    return {"moving_atm":center,
            "moving_ce_oi":a1["ce_oi"],"moving_pe_oi":a1["pe_oi"],
            "ce_delta_5m":ced,"pe_delta_5m":ped,
            "ce_pct_5m":pct(a1["ce_oi"],a0["ce_oi"]),
            "pe_pct_5m":pct(a1["pe_oi"],a0["pe_oi"]),
            "activity_5m":abs(ced)+abs(ped),
            "imbalance_5m":ped-ced,
            "pcr_previous_5m":p0,"pcr_current_5m":p1,
            "pcr_change_5m":(p1-p0) if p0 is not None and p1 is not None else None}

def fixed_base(sn,c,ds):
    t=next((x for x in sorted(sn) if x.date().isoformat()==ds and (x.hour,x.minute)==(9,20)),None)
    if t is None: return None
    atm=moving_atm(sn[t],c)
    if atm is None: return None
    strikes=[atm+i*50.0 for i in range(-2,3)]
    a=aggregate(sn[t],c,strikes)
    if a is None: return None
    return {"atm":atm,"strikes":strikes,**a}

def session_context(cur,c,base):
    a=aggregate(cur,c,base["strikes"])
    if not a: return None
    ce0,pe0=base["ce_oi"],base["pe_oi"]; ce1,pe1=a["ce_oi"],a["pe_oi"]
    ced,ped=ce1-ce0,pe1-pe0
    p0=pe0/ce0 if ce0 else None; p1=pe1/ce1 if ce1 else None
    return {"fixed_0920_atm":base["atm"],
            "ce_0920_oi":ce0,"pe_0920_oi":pe0,
            "ce_session_delta":ced,"pe_session_delta":ped,
            "ce_session_pct":pct(ce1,ce0),"pe_session_pct":pct(pe1,pe0),
            "session_activity":abs(ced)+abs(ped),
            "session_imbalance":ped-ced,
            "pcr_0920":p0,"pcr_current_session":p1,
            "pcr_session_change":(p1-p0) if p0 is not None and p1 is not None else None}

def candidate(prev,cur,direction):
    if prev is None: return False
    pc=cur["pcr_change_5m"]
    if pc is None: return False
    si0=prev["session_imbalance"]; si1=cur["session_imbalance"]
    if direction=="BULLISH":
        return (prev["imbalance_5m"] <= 0 and cur["imbalance_5m"] > 0
                and pc > 0 and si1 > si0)
    return (prev["imbalance_5m"] >= 0 and cur["imbalance_5m"] < 0
            and pc < 0 and si1 < si0)

def persistence(stream,idx,direction,n):
    sign=1 if direction=="BULLISH" else -1
    if idx+n > len(stream): return False
    xs=stream[idx:idx+n]
    ts=[dt(r["timestamp"]) for r in xs]
    if any(ts[j]-ts[j-1] != timedelta(minutes=5) for j in range(1,len(ts))):
        return False
    return all((1 if r["imbalance_5m"]>0 else -1 if r["imbalance_5m"]<0 else 0)==sign
               for r in xs)

def future_move(sn,c,t,spot0,direction,h):
    target=t+timedelta(minutes=h)
    if target not in sn or spot0 is None: return None
    s1=spot(sn[target],c)
    if s1 is None: return None
    raw=s1-spot0
    return raw if direction=="BULLISH" else -raw

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--bullish-dates",required=True)
    ap.add_argument("--bearish-dates",required=True)
    ap.add_argument("--positioning",action="append",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--csv-output",required=True)
    a=ap.parse_args()

    bull=read_dates(a.bullish_dates); bear=read_dates(a.bearish_dates)
    if bull & bear: raise RuntimeError("bull/bear overlap")
    known=bull|bear

    events=[]; sessions=[]
    all_dates=set()

    for spec in a.positioning:
        block,path=spec.split("|",1)
        if block in FORBIDDEN: raise RuntimeError(f"Forbidden block: {block}")
        rows=read_csv(path); c=detect(rows); sn=snapshots(rows,c)
        dates=sorted({t.date().isoformat() for t in sn})
        all_dates.update(dates)
        for ds in dates:
            base=fixed_base(sn,c,ds)
            if base is None: continue
            day_class=("BULLISH_TREND_DAY" if ds in bull else
                       "BEARISH_TREND_DAY" if ds in bear else "MIXED_DAY")
            stream=[]
            for t in sorted(sn):
                if t.date().isoformat()!=ds: continue
                if (t.hour,t.minute)<(9,25) or (t.hour,t.minute)>(15,25) or t.minute%5!=0: continue
                prevrows=sn.get(t-timedelta(minutes=5))
                if prevrows is None: continue
                ma=moving_atm(sn[t],c)
                if ma is None: continue
                sh=short_term(sn[t],prevrows,c,ma); se=session_context(sn[t],c,base)
                if sh is None or se is None: continue
                stream.append({"block":block,"session_date":ds,"day_class":day_class,
                               "timestamp":t.isoformat(),"candle_time":t.strftime("%H:%M"),
                               "spot_close":spot(sn[t],c),**sh,**se})
            day_counts={"BULLISH":0,"BEARISH":0}
            first={"BULLISH":None,"BEARISH":None}
            for i,r in enumerate(stream):
                prev=stream[i-1] if i else None
                for direction in ("BULLISH","BEARISH"):
                    if not candidate(prev,r,direction): continue
                    day_counts[direction]+=1
                    if first[direction] is None: first[direction]=r["candle_time"]
                    ev=dict(r)
                    ev["direction"]=direction
                    ev["occurrence_number"]=day_counts[direction]
                    for n in (1,2,3,4):
                        ev[f"persists_{n}cp"]=persistence(stream,i,direction,n)
                    t=dt(r["timestamp"]); s0=r["spot_close"]
                    for h in HORIZONS:
                        ev[f"directional_move_{h}m_points"]=future_move(sn,c,t,s0,direction,h)
                    events.append(ev)
            sessions.append({
                "block":block,"session_date":ds,"day_class":day_class,
                "bullish_occurrences":day_counts["BULLISH"],
                "bearish_occurrences":day_counts["BEARISH"],
                "first_bullish_candle":first["BULLISH"],
                "first_bearish_candle":first["BEARISH"],
            })

    mixed=sorted(all_dates-known)
    def event_summary(xs):
        return {
            "event_count":len(xs),
            "session_count":len({x["session_date"] for x in xs}),
            "activity_5m":stats([x["activity_5m"] for x in xs]),
            "abs_imbalance_5m":stats([abs(x["imbalance_5m"]) for x in xs]),
            "session_activity":stats([x["session_activity"] for x in xs]),
            "abs_session_imbalance":stats([abs(x["session_imbalance"]) for x in xs]),
            **{f"directional_move_{h}m_points":
               stats([x.get(f"directional_move_{h}m_points") for x in xs]) for h in HORIZONS},
            **{f"persists_{n}cp_pct":
               (sum(bool(x[f"persists_{n}cp"]) for x in xs)/len(xs)*100 if xs else None)
               for n in (1,2,3,4)}
        }

    groups={}
    for dc in ("BULLISH_TREND_DAY","BEARISH_TREND_DAY","MIXED_DAY"):
        groups[dc]={}
        for direction in ("BULLISH","BEARISH"):
            groups[dc][direction]=event_summary(
                [x for x in events if x["day_class"]==dc and x["direction"]==direction]
            )

    result={
        "research_version":VERSION,
        "population":{
            "development_sessions_seen":len(all_dates),
            "bullish_trend_days":len(bull & all_dates),
            "bearish_trend_days":len(bear & all_dates),
            "mixed_days":len(mixed),
        },
        "definitions":{
            "candidate_bullish":
                "prev_5m_imbalance<=0 AND current_5m_imbalance>0 AND current_5m_PCR_change>0 AND session_imbalance_improving",
            "candidate_bearish":
                "prev_5m_imbalance>=0 AND current_5m_imbalance<0 AND current_5m_PCR_change<0 AND session_imbalance_weakening",
            "occurrence":"fresh sign transition only; persistence is not recounted",
            "detection_time":"completed 5-minute candle timestamp",
            "no_quantity_threshold":True,
        },
        "group_summary":groups,
        "session_summary":sessions,
        "events":events,
        "integrity":{
            "historical_only":True,"oos_e_f_g_h_used":False,
            "mixed_control_included":True,"quantity_threshold_fitted":False,
            "strategy_rule_changed":False,"paper_or_live_action":False,
        }
    }
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    if events:
        fields=sorted(set().union(*(x.keys() for x in events)))
        with Path(a.csv_output).open("w",newline="",encoding="utf-8") as h:
            w=csv.DictWriter(h,fieldnames=fields); w.writeheader(); w.writerows(events)
    print(json.dumps({"research_version":VERSION,
                      "population":result["population"],
                      "event_count":len(events),
                      "output":a.output,"csv_output":a.csv_output},indent=2))

if __name__=="__main__":
    main()
