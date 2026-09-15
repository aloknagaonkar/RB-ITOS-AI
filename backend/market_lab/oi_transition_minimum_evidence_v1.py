from __future__ import annotations
import argparse, csv, json, statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

VERSION = "OI_TRANSITION_MINIMUM_EVIDENCE_V1"
FORBIDDEN = {"OOS_E","OOS_F","OOS_G","OOS_H"}
OFFSETS = (-10,-5,0,5,10,15,20)
CLASSES = ("BULLISH_TREND_DAY","BEARISH_TREND_DAY")

def f(v):
    if v in ("", None): return None
    try: return float(v)
    except Exception: return None

def dt(v):
    return datetime.fromisoformat(str(v).replace("Z","+00:00"))

def pct(cur, prev):
    if cur is None or prev in (None,0): return None
    return (cur-prev)/prev*100.0

def quantile(vals,q):
    xs=sorted(v for v in vals if v is not None)
    if not xs: return None
    if len(xs)==1: return xs[0]
    pos=(len(xs)-1)*q
    lo=int(pos); hi=min(lo+1,len(xs)-1); frac=pos-lo
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
    c={"timestamp":first("timestamp"),"spot":first("spot"),"atm":first("moving_atm"),
       "strike":first("strike"),"offset":first("strike_offset"),
       "ce_oi":first("ce_open_interest","ce_oi"),"pe_oi":first("pe_open_interest","pe_oi")}
    missing=[k for k,v in c.items() if v is None]
    if missing: raise RuntimeError("Missing positioning columns: "+", ".join(missing))
    return c

def snapshots(rows,c):
    out={}
    for r in rows:
        out.setdefault(dt(r[c["timestamp"]]),[]).append(r)
    return out

def moving_atm(rows,c):
    for r in rows:
        if f(r[c["offset"]])==0:
            return f(r[c["atm"]])
    return None

def aggregate(rows,c,strikes):
    mp={f(r[c["strike"]]):r for r in rows}
    strikes=list(strikes)
    if not all(s in mp for s in strikes): return None
    return {
        "ce_oi":sum(f(mp[s][c["ce_oi"]]) or 0 for s in strikes),
        "pe_oi":sum(f(mp[s][c["pe_oi"]]) or 0 for s in strikes),
        "strikes":strikes,
    }

def same_strike_5m(cur,prev,c,center):
    strikes=[center+i*50.0 for i in range(-2,3)]
    a0=aggregate(prev,c,strikes); a1=aggregate(cur,c,strikes)
    if not a0 or not a1: return None
    ced=a1["ce_oi"]-a0["ce_oi"]; ped=a1["pe_oi"]-a0["pe_oi"]
    p0=a0["pe_oi"]/a0["ce_oi"] if a0["ce_oi"] else None
    p1=a1["pe_oi"]/a1["ce_oi"] if a1["ce_oi"] else None
    return {
        "ce_previous_oi":a0["ce_oi"],"pe_previous_oi":a0["pe_oi"],
        "ce_current_oi":a1["ce_oi"],"pe_current_oi":a1["pe_oi"],
        "ce_delta_5m":ced,"pe_delta_5m":ped,
        "ce_pct_5m":pct(a1["ce_oi"],a0["ce_oi"]),
        "pe_pct_5m":pct(a1["pe_oi"],a0["pe_oi"]),
        "activity_5m":abs(ced)+abs(ped),"imbalance_5m":ped-ced,
        "pcr_previous":p0,"pcr_current":p1,
        "pcr_change_5m":(p1-p0) if p0 is not None and p1 is not None else None,
        "strikes":strikes,
    }

def fixed_0920_context(sn,c,date_s):
    target=next((t for t in sorted(sn)
                 if t.date().isoformat()==date_s and (t.hour,t.minute)==(9,20)),None)
    if target is None: return None
    atm=moving_atm(sn[target],c)
    if atm is None: return None
    strikes=[atm+i*50.0 for i in range(-2,3)]
    base=aggregate(sn[target],c,strikes)
    if base is None: return None
    return {"timestamp":target,"atm":atm,"strikes":strikes,**base}

def session_context(cur,c,fixed):
    now=aggregate(cur,c,fixed["strikes"])
    if now is None: return None
    ce0,pe0=fixed["ce_oi"],fixed["pe_oi"]
    ce1,pe1=now["ce_oi"],now["pe_oi"]
    ced,ped=ce1-ce0,pe1-pe0
    p0=pe0/ce0 if ce0 else None; p1=pe1/ce1 if ce1 else None
    return {
        "fixed_0920_atm":fixed["atm"],"fixed_strikes":fixed["strikes"],
        "ce_0920_oi":ce0,"pe_0920_oi":pe0,
        "ce_current_oi_fixed":ce1,"pe_current_oi_fixed":pe1,
        "ce_session_delta":ced,"pe_session_delta":ped,
        "ce_session_pct":pct(ce1,ce0),"pe_session_pct":pct(pe1,pe0),
        "session_activity":abs(ced)+abs(ped),"session_imbalance":ped-ced,
        "pcr_0920":p0,"pcr_current_fixed":p1,
        "pcr_session_change":(p1-p0) if p0 is not None and p1 is not None else None,
    }

def persistence_at(rows,idx,n,expected_sign):
    if idx-n+1 < 0: return False
    xs=rows[idx-n+1:idx+1]
    ts=[dt(r["timestamp"]) for r in xs]
    if any(ts[j]-ts[j-1] != timedelta(minutes=5) for j in range(1,len(ts))):
        return False
    signs=[1 if r["imbalance_5m"]>0 else -1 if r["imbalance_5m"]<0 else 0 for r in xs]
    return all(s==expected_sign for s in signs)

def summarize(rows):
    fields=["ce_current_oi","pe_current_oi","ce_delta_5m","pe_delta_5m",
            "ce_pct_5m","pe_pct_5m","activity_5m","imbalance_5m",
            "pcr_current","pcr_change_5m","ce_0920_oi","pe_0920_oi",
            "ce_current_oi_fixed","pe_current_oi_fixed","ce_session_delta",
            "pe_session_delta","ce_session_pct","pe_session_pct",
            "session_activity","session_imbalance","pcr_0920",
            "pcr_current_fixed","pcr_session_change"]
    return {"day_count":len({r["session_date"] for r in rows}),
            **{k:stats([r.get(k) for r in rows]) for k in fields}}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--bullish-dates",required=True)
    ap.add_argument("--bearish-dates",required=True)
    ap.add_argument("--move-replay",required=True)
    ap.add_argument("--positioning",action="append",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--csv-output",required=True)
    a=ap.parse_args()

    bull=read_dates(a.bullish_dates); bear=read_dates(a.bearish_dates)
    if bull & bear: raise RuntimeError("Frozen bullish/bearish date overlap")
    labels={d:"BULLISH_TREND_DAY" for d in bull}
    labels.update({d:"BEARISH_TREND_DAY" for d in bear})

    replay=json.loads(Path(a.move_replay).read_text())
    if replay.get("research_version")!="TREND_DAY_MOVE_START_OI_REPLAY_V1":
        raise RuntimeError("Unexpected move replay research_version")
    anchors={d["session_date"]:d for d in replay.get("day_summaries",[])
             if d.get("status")=="AVAILABLE" and d.get("session_date") in labels}

    out=[]; streams={}
    for spec in a.positioning:
        block,path=spec.split("|",1)
        if block in FORBIDDEN: raise RuntimeError(f"Forbidden block: {block}")
        rows=read_csv(path); c=detect(rows); sn=snapshots(rows,c)
        dates_here={t.date().isoformat() for t in sn}
        for ds in sorted(set(labels)&set(anchors)&dates_here):
            fixed=fixed_0920_context(sn,c,ds)
            if fixed is None: continue
            anchor_t=dt(anchors[ds]["move_start_timestamp"])
            stream=[]
            for t in sorted(sn):
                if t.date().isoformat()!=ds: continue
                if (t.hour,t.minute)<(9,20) or (t.hour,t.minute)>(15,25) or t.minute%5!=0: continue
                prev=sn.get(t-timedelta(minutes=5))
                if prev is None: continue
                cur=sn[t]; ma=moving_atm(cur,c)
                if ma is None: continue
                short=same_strike_5m(cur,prev,c,ma); sess=session_context(cur,c,fixed)
                if short is None or sess is None: continue
                stream.append({"block":block,"session_date":ds,"day_class":labels[ds],
                               "timestamp":t.isoformat(),"time":t.strftime("%H:%M"),
                               "moving_atm":ma,**short,**sess})
            streams[ds]=stream
            for off in OFFSETS:
                target=anchor_t+timedelta(minutes=off)
                r=next((x for x in stream if dt(x["timestamp"])==target),None)
                if r:
                    rr=dict(r); rr["move_start_time"]=anchors[ds]["move_start_time"]; rr["offset_minutes"]=off
                    out.append(rr)

    by_class_offset={dc:{str(off):summarize([r for r in out if r["day_class"]==dc and r["offset_minutes"]==off])
                         for off in OFFSETS} for dc in CLASSES}

    persistence={}
    for dc in CLASSES:
        expected=1 if dc=="BULLISH_TREND_DAY" else -1
        persistence[dc]={}
        for n in (1,2,3,4):
            hits=[]; avail=0
            for ds,stream in streams.items():
                if labels[ds]!=dc: continue
                for idx,r in enumerate(stream):
                    if idx-n+1<0: continue
                    avail+=1
                    if persistence_at(stream,idx,n,expected): hits.append(r)
            persistence[dc][str(n)]={
                "available_endpoint_count":avail,
                "matching_endpoint_count":len(hits),
                "matching_endpoint_pct":len(hits)/avail*100 if avail else None,
                "current_total_oi":stats([r["ce_current_oi"]+r["pe_current_oi"] for r in hits]),
                "activity_5m":stats([r["activity_5m"] for r in hits]),
                "abs_imbalance_5m":stats([abs(r["imbalance_5m"]) for r in hits]),
                "session_activity":stats([r["session_activity"] for r in hits]),
                "abs_session_imbalance":stats([abs(r["session_imbalance"]) for r in hits]),
            }

    result={"research_version":VERSION,
            "population":{"bullish_days":len(bull),"bearish_days":len(bear)},
            "definitions":{
                "short_term_primary":"MOVING_ATM_PM2_SAME_PHYSICAL_STRIKES_T_VS_T_MINUS_5",
                "session_context_primary":"FIXED_0920_ATM_PM2_SAME_FIVE_PHYSICAL_STRIKES_ALL_DAY",
                "threshold_selected":False},
            "by_class_offset":by_class_offset,
            "persistence_evidence":persistence,
            "rows":out,
            "integrity":{"historical_only":True,"oos_e_f_g_h_used":False,
                         "absolute_oi_preserved":True,"session_to_date_oi_preserved":True,
                         "five_minute_oi_preserved":True,"threshold_selected":False,
                         "strategy_rule_changed":False,"paper_or_live_action":False}}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    Path(a.csv_output).parent.mkdir(parents=True,exist_ok=True)
    if out:
        fields=sorted(set().union(*(r.keys() for r in out)))
        with Path(a.csv_output).open("w",newline="",encoding="utf-8") as h:
            w=csv.DictWriter(h,fieldnames=fields); w.writeheader(); w.writerows(out)
    print(json.dumps({"research_version":VERSION,"row_count":len(out),
                      "population":result["population"],"output":a.output,
                      "csv_output":a.csv_output},indent=2))

if __name__=="__main__":
    main()
