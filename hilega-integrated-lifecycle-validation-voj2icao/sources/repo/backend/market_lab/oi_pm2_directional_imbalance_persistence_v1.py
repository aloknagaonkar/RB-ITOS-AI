from __future__ import annotations

"""
OI_PM2_DIRECTIONAL_IMBALANCE_PERSISTENCE_V1

Research-only study over frozen bullish/bearish trend-day lists.

Inputs:
- frozen bullish dates
- frozen bearish dates
- TRAIN/OOS_A-D historical positioning CSVs

Primary band:
- Moving ATM ±2
- same physical strikes at T and exact T-5m
- exactly 5 common strikes required

Per 5m checkpoint:
- CE/PE OI current
- CE/PE signed OI delta
- CE/PE OI %
- gross activity = abs(CE delta) + abs(PE delta)
- directional imbalance = PE delta - CE delta
- PCR + PCR change
- ATM CE/PE state if available

Persistence:
- 1,2,3,4 consecutive completed checkpoints
- positive imbalance => bullish-side quantity imbalance
- negative imbalance => bearish-side quantity imbalance
- PCR sign agreement is measured separately, not required for inclusion

No thresholds are tuned. No OOS E/F/G/H. No strategy/paper/live changes.
"""

import argparse, csv, json, statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

VERSION = "OI_PM2_DIRECTIONAL_IMBALANCE_PERSISTENCE_V1"
FORBIDDEN = {"OOS_E","OOS_F","OOS_G","OOS_H"}

def f(v):
    if v in ("", None):
        return None
    try:
        return float(v)
    except Exception:
        return None

def dt(v):
    return datetime.fromisoformat(str(v).replace("Z","+00:00"))

def pct(cur, prev):
    if cur is None or prev in (None,0):
        return None
    return (cur-prev)/prev*100.0

def med(xs):
    vals=[x for x in xs if x is not None]
    return statistics.median(vals) if vals else None

def read_dates(path):
    return {x.strip() for x in Path(path).read_text().splitlines() if x.strip()}

def read_csv(path):
    with Path(path).open(newline="",encoding="utf-8-sig") as h:
        return list(csv.DictReader(h))

def detect(rows):
    keys=set().union(*(r.keys() for r in rows))
    def first(*xs): return next((x for x in xs if x in keys),None)
    c={
        "timestamp":first("timestamp"),
        "spot":first("spot"),
        "atm":first("moving_atm"),
        "strike":first("strike"),
        "offset":first("strike_offset"),
        "ce_oi":first("ce_open_interest","ce_oi"),
        "pe_oi":first("pe_open_interest","pe_oi"),
        "ce_state":first("ce_5m_state"),
        "pe_state":first("pe_5m_state"),
    }
    missing=[k for k in ("timestamp","spot","atm","strike","offset","ce_oi","pe_oi") if c[k] is None]
    if missing:
        raise RuntimeError("Missing positioning columns: "+", ".join(missing))
    return c

def snapshots(rows,c):
    out={}
    for r in rows:
        t=dt(r[c["timestamp"]])
        out.setdefault(t,[]).append(r)
    return out

def atm(rows,c):
    for r in rows:
        if f(r[c["offset"]])==0:
            return f(r[c["atm"]])
    return None

def atm_row(rows,c,center):
    for r in rows:
        if f(r[c["strike"]])==center:
            return r
    return None

def aggregate(cur,prev,c,center):
    wanted={center+i*50.0 for i in range(-2,3)}
    cm={f(r[c["strike"]]):r for r in cur}
    pm={f(r[c["strike"]]):r for r in prev}
    common=sorted(wanted & set(cm) & set(pm))
    if len(common)!=5:
        return None
    ce0=sum(f(pm[s][c["ce_oi"]]) or 0 for s in common)
    ce1=sum(f(cm[s][c["ce_oi"]]) or 0 for s in common)
    pe0=sum(f(pm[s][c["pe_oi"]]) or 0 for s in common)
    pe1=sum(f(cm[s][c["pe_oi"]]) or 0 for s in common)
    ced=ce1-ce0
    ped=pe1-pe0
    p0=(pe0/ce0) if ce0 else None
    p1=(pe1/ce1) if ce1 else None
    return {
        "ce_oi":ce1,"pe_oi":pe1,
        "ce_delta":ced,"pe_delta":ped,
        "ce_pct":pct(ce1,ce0),"pe_pct":pct(pe1,pe0),
        "activity":abs(ced)+abs(ped),
        "imbalance":ped-ced,
        "pcr":p1,
        "pcr_change":(p1-p0) if p1 is not None and p0 is not None else None,
        "common_strikes":common,
    }

def window_for(t):
    hm=(t.hour,t.minute)
    if hm < (10,0): return "09:20-10:00"
    if hm < (11,0): return "10:00-11:00"
    if hm < (12,0): return "11:00-12:00"
    if hm < (13,0): return "12:00-13:00"
    if hm < (14,0): return "13:00-14:00"
    return "14:00-CLOSE"

def sign(v):
    return 1 if v>0 else -1 if v<0 else 0

def aligned(day_class, imbalance):
    return (day_class=="BULLISH_TREND_DAY" and imbalance>0) or \
           (day_class=="BEARISH_TREND_DAY" and imbalance<0)

def add_persistence(day_rows):
    day_rows.sort(key=lambda r:r["timestamp"])
    for i,r in enumerate(day_rows):
        for n in (1,2,3,4):
            if i-n+1 < 0:
                r[f"persist_{n}_available"]=False
                r[f"persist_{n}_sign"]=0
                r[f"persist_{n}_aligned"]=None
                r[f"persist_{n}_pcr_agree"]=None
                continue
            xs=day_rows[i-n+1:i+1]
            # exact 5m continuity
            ts=[dt(x["timestamp"]) for x in xs]
            if any((ts[j]-ts[j-1])!=timedelta(minutes=5) for j in range(1,len(ts))):
                r[f"persist_{n}_available"]=False
                r[f"persist_{n}_sign"]=0
                r[f"persist_{n}_aligned"]=None
                r[f"persist_{n}_pcr_agree"]=None
                continue
            ss=[sign(x["imbalance"]) for x in xs]
            same = ss[0] != 0 and all(s==ss[0] for s in ss)
            r[f"persist_{n}_available"]=True
            r[f"persist_{n}_sign"]=ss[0] if same else 0
            r[f"persist_{n}_aligned"]=aligned(r["day_class"], ss[0]) if same else False
            pcrs=[sign(x["pcr_change"]) if x["pcr_change"] is not None else 0 for x in xs]
            r[f"persist_{n}_pcr_agree"]=(same and all(p==ss[0] for p in pcrs))
    return day_rows

def summarize(rows, n):
    xs=[r for r in rows if r.get(f"persist_{n}_available")]
    same=[r for r in xs if r.get(f"persist_{n}_sign") in (-1,1)]
    aligned_rows=[r for r in same if r.get(f"persist_{n}_aligned")]
    pcr_agree=[r for r in same if r.get(f"persist_{n}_pcr_agree")]
    return {
        "available_count":len(xs),
        "same_sign_persistence_count":len(same),
        "same_sign_persistence_pct": (len(same)/len(xs)*100.0) if xs else None,
        "class_aligned_count":len(aligned_rows),
        "class_aligned_pct_of_same_sign": (len(aligned_rows)/len(same)*100.0) if same else None,
        "pcr_same_sign_agreement_count":len(pcr_agree),
        "pcr_same_sign_agreement_pct_of_same_sign": (len(pcr_agree)/len(same)*100.0) if same else None,
        "median_abs_imbalance":med([abs(r["imbalance"]) for r in same]),
        "median_activity":med([r["activity"] for r in same]),
        "positive_persistence_count":sum(r[f"persist_{n}_sign"]==1 for r in same),
        "negative_persistence_count":sum(r[f"persist_{n}_sign"]==-1 for r in same),
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--bullish-dates",required=True)
    ap.add_argument("--bearish-dates",required=True)
    ap.add_argument("--positioning",action="append",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--csv-output")
    a=ap.parse_args()

    bullish=read_dates(a.bullish_dates)
    bearish=read_dates(a.bearish_dates)
    overlap=sorted(bullish & bearish)
    if overlap:
        raise RuntimeError(f"Frozen date overlap: {overlap}")

    class_map={d:"BULLISH_TREND_DAY" for d in bullish}
    class_map.update({d:"BEARISH_TREND_DAY" for d in bearish})

    rows_out=[]
    skipped=0
    for spec in a.positioning:
        block,path=spec.split("|",1)
        if block in FORBIDDEN:
            raise RuntimeError(f"Forbidden block: {block}")
        rows=read_csv(path)
        c=detect(rows)
        sn=snapshots(rows,c)
        for t in sorted(sn):
            ds=t.date().isoformat()
            if ds not in class_map:
                continue
            if (t.hour,t.minute)<(9,20) or (t.hour,t.minute)>(15,29) or t.minute%5!=0:
                continue
            prev=sn.get(t-timedelta(minutes=5))
            if not prev:
                continue
            cur=sn[t]
            center=atm(cur,c)
            if center is None:
                continue
            agg=aggregate(cur,prev,c,center)
            if not agg:
                skipped+=1
                continue
            ar=atm_row(cur,c,center)
            rows_out.append({
                "block":block,
                "session_date":ds,
                "day_class":class_map[ds],
                "timestamp":t.isoformat(),
                "time":t.strftime("%H:%M"),
                "window":window_for(t),
                "spot":f(cur[0][c["spot"]]),
                "moving_atm":center,
                **agg,
                "ce_state":ar.get(c["ce_state"]) if ar and c["ce_state"] else "UNAVAILABLE",
                "pe_state":ar.get(c["pe_state"]) if ar and c["pe_state"] else "UNAVAILABLE",
            })

    by_day=defaultdict(list)
    for r in rows_out:
        by_day[r["session_date"]].append(r)

    rows_out=[]
    for ds in sorted(by_day):
        rows_out.extend(add_persistence(by_day[ds]))

    overall={}
    by_window={}
    windows=("09:20-10:00","10:00-11:00","11:00-12:00","12:00-13:00","13:00-14:00","14:00-CLOSE")
    for dc in ("BULLISH_TREND_DAY","BEARISH_TREND_DAY"):
        xs=[r for r in rows_out if r["day_class"]==dc]
        overall[dc]={str(n):summarize(xs,n) for n in (1,2,3,4)}
        by_window[dc]={}
        for w in windows:
            wx=[r for r in xs if r["window"]==w]
            by_window[dc][w]={str(n):summarize(wx,n) for n in (1,2,3,4)}

    result={
        "research_version":VERSION,
        "frozen_inputs":{
            "bullish_file":a.bullish_dates,
            "bearish_file":a.bearish_dates,
            "bullish_count":len(bullish),
            "bearish_count":len(bearish),
        },
        "feature_definition":{
            "primary_band":"MOVING_ATM_PM2",
            "directional_imbalance":"PE_DELTA_MINUS_CE_DELTA",
            "positive_interpretation":"BULLISH_SIDE_QUANTITY_IMBALANCE",
            "negative_interpretation":"BEARISH_SIDE_QUANTITY_IMBALANCE",
            "activity":"ABS(CE_DELTA)+ABS(PE_DELTA)",
            "quantity_and_percentage_both_retained":True,
            "persistence_lengths_checkpoints":[1,2,3,4],
            "persistence_minutes":[5,10,15,20],
            "threshold_tuning_performed":False,
        },
        "checkpoint_count":len(rows_out),
        "skipped_incomplete_pm2_count":skipped,
        "overall":overall,
        "by_time_window":by_window,
        "rows":rows_out,
        "integrity":{
            "frozen_day_lists_used":True,
            "day_classes_not_recomputed":True,
            "historical_only":True,
            "oos_e_f_g_h_used":False,
            "strategy_rule_changed":False,
            "paper_or_live_action":False,
        }
    }

    p=Path(a.output); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    if a.csv_output and rows_out:
        cp=Path(a.csv_output); cp.parent.mkdir(parents=True,exist_ok=True)
        fields=list(rows_out[0].keys())
        with cp.open("w",newline="",encoding="utf-8") as h:
            w=csv.DictWriter(h,fieldnames=fields)
            w.writeheader(); w.writerows(rows_out)

    print(json.dumps({
        "research_version":VERSION,
        "frozen_bullish_count":len(bullish),
        "frozen_bearish_count":len(bearish),
        "checkpoint_count":len(rows_out),
        "skipped_incomplete_pm2_count":skipped,
        "overall":overall,
        "output":a.output,
        "csv_output":a.csv_output,
    },indent=2))

if __name__=="__main__":
    main()
