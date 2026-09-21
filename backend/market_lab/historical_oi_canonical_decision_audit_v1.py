from __future__ import annotations
import argparse, csv, json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

MODEL="CANONICAL_90_DECISION_AUDIT_V1"
H=(5,10,15)
DIR={"BULLISH_ALL_3":"BULLISH","BEARISH_ALL_3":"BEARISH"}
BULL={"LONG_BUILDUP","SHORT_COVERING"}
BEAR={"SHORT_BUILDUP","LONG_UNWINDING"}

def n(v):
    try: return None if v in (None,"") else float(v)
    except: return None

def ts(row, date=None):
    for k in ("timestamp","checkpoint_timestamp","exchange_timestamp","candle_timestamp","datetime"):
        if row.get(k):
            try: return datetime.fromisoformat(str(row[k]).replace("Z","+00:00"))
            except: pass
    if date and row.get("time"):
        return datetime.fromisoformat(f"{date}T{row['time']}")
    return None

def hdata(row,h):
    mh=row.get("moving_horizons") or {}
    # Real enriched schema stores keys as '5m'/'10m'/'15m'.
    # Keep compatibility with older synthetic/tests using '5' or integer keys.
    x=mh.get(f"{h}m", mh.get(str(h), mh.get(h)))
    return x if isinstance(x,dict) else None

def hclass(row,h):
    x=hdata(row,h)
    if not x: return {"state":"INCOMPLETE","imbalance":None,"pcr_change":None}
    im=n(x.get("imbalance")); pc=n(x.get("pcr_change"))
    if im is None or pc is None: st="INCOMPLETE"
    elif im>0 and pc>0: st="BULLISH"
    elif im<0 and pc<0: st="BEARISH"
    else: st="MIXED"
    return {"state":st,"imbalance":im,"pcr_change":pc,
            "ce_delta":n(x.get("ce_delta")),"pe_delta":n(x.get("pe_delta")),
            "prior_pcr":n(x.get("prior_pcr")),"current_pcr":n(x.get("current_pcr"))}

def all3(row):
    hs={str(h):hclass(row,h) for h in H}; states=[hs[str(h)]["state"] for h in H]
    if "INCOMPLETE" in states: a="INCOMPLETE"
    elif all(x=="BULLISH" for x in states): a="BULLISH_ALL_3"
    elif all(x=="BEARISH" for x in states): a="BEARISH_ALL_3"
    else: a="MIXED"
    return {"all3":a,"direction":DIR.get(a),"horizons":hs}

def norm_state(v):
    if v is None:return None
    s=str(v).upper().strip().replace(" ","_").replace("-","_")
    aliases={"LONGBUILDUP":"LONG_BUILDUP","SHORTBUILDUP":"SHORT_BUILDUP",
             "SHORTCOVERING":"SHORT_COVERING","LONGUNWINDING":"LONG_UNWINDING"}
    return aliases.get(s.replace("_",""),s)

def load_futures(path):
    # Build causal completed 5-minute futures OI states from the existing
    # 1-minute futures/VWAP CSV. Index by bar-end / decision-available time.
    p=Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    one_min=[]
    with p.open(newline="",encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            d=ts(r,r.get("session_date"))
            if d:
                one_min.append((d,r))
    one_min.sort(key=lambda z:z[0])

    by_session={}
    for d,r in one_min:
        by_session.setdefault(d.date().isoformat(),[]).append((d,r))

    out={}
    for session_date, rows in by_session.items():
        buckets={}
        for d,r in rows:
            minute=(d.minute//5)*5
            bstart=d.replace(minute=minute,second=0,microsecond=0)
            buckets.setdefault(bstart,[]).append((d,r))

        bars=[]
        for bstart, items in sorted(buckets.items()):
            items=sorted(items,key=lambda z:z[0])
            expected=[bstart+timedelta(minutes=i) for i in range(5)]
            actual=[d.replace(second=0,microsecond=0) for d,_ in items]
            if actual != expected:
                continue

            last=items[-1][1]
            close=n(last.get("close"))
            oi=n(last.get("open_interest"))
            if close is None or oi is None:
                continue

            bars.append({
                "bar_start":bstart,
                "available_at":bstart+timedelta(minutes=5),
                "close":close,
                "oi":oi,
                "instrument_key":last.get("instrument_key"),
                "expiry":last.get("expiry"),
                "contract_source":last.get("contract_source"),
            })

        for i,bar in enumerate(bars):
            state="UNAVAILABLE"
            oi_delta=None
            price_delta=None

            if i>0:
                prev=bars[i-1]
                if (
                    bar["bar_start"]-prev["bar_start"]==timedelta(minutes=5)
                    and bar.get("instrument_key")==prev.get("instrument_key")
                ):
                    price_delta=bar["close"]-prev["close"]
                    oi_delta=bar["oi"]-prev["oi"]

                    if price_delta>0 and oi_delta>0:
                        state="LONG_BUILDUP"
                    elif price_delta<0 and oi_delta>0:
                        state="SHORT_BUILDUP"
                    elif price_delta>0 and oi_delta<0:
                        state="SHORT_COVERING"
                    elif price_delta<0 and oi_delta<0:
                        state="LONG_UNWINDING"
                    else:
                        state="NEUTRAL"

            key=bar["available_at"].replace(second=0,microsecond=0).isoformat()
            out[key]={
                "state":state,
                "close":bar["close"],
                "oi":bar["oi"],
                "oi_change_5m":oi_delta,
                "price_change_5m":price_delta,
                "bar_start":bar["bar_start"].isoformat(),
                "available_at":key,
                "instrument_key":bar.get("instrument_key"),
                "expiry":bar.get("expiry"),
                "contract_source":bar.get("contract_source"),
            }

    return out

def check(cid,stage,required,expected,actual,result,reason,timestamp,evidence=None):
    return dict(check_id=cid,stage=stage,required=required,expected=expected,actual=actual,
                result=result,reason=reason,timestamp=timestamp,evidence=evidence or {})

def load_enriched(path,date):
    x=json.loads(Path(path).read_text()); out=[]
    for r in x.get("rows",[]):
        d=ts(r,date)
        if d:
            rr=dict(r); rr["_dt"]=d; out.append(rr)
    return sorted(out,key=lambda r:r["_dt"])

def audit_session(date,rows,fidx):
    by={r["_dt"].replace(second=0,microsecond=0).isoformat():r for r in rows}
    prev=None; events=[]; cps=[]
    for r in rows:
        d=r["_dt"]; t=d.replace(second=0,microsecond=0).isoformat(); c=all3(r); direction=c["direction"]
        new=direction is not None and direction!=prev
        cps.append({"timestamp":t,"time":r.get("time") or d.strftime("%H:%M"),"spot":n(r.get("spot")),
                    "moving_atm":n(r.get("moving_atm")),"all3":c["all3"],"direction":direction,
                    "is_new_directional_detection":new,"horizons":c["horizons"]})
        oldprev=prev
        if direction is not None: prev=direction
        if not new: continue
        cs=[]
        for h in H:
            x=c["horizons"][str(h)]
            cs.append(check(f"HORIZON_{h}M","C1_ALL3",True,direction,x["state"],
                "PASS" if x["state"]==direction else "FAIL","imbalance + PCR sign classification",t,x))
        cs.append(check("C1_NEW_DIRECTION","C1_ALL3",True,f"new {direction}",c["all3"],"PASS",
                        "directional ALL_3 differs from previous directional regime",t,{"previous_directional":oldprev}))
        c2d=d+timedelta(minutes=5); c2t=c2d.replace(second=0,microsecond=0).isoformat(); c2=by.get(c2t)
        c2a=None; fs=None
        if c2 is None:
            cs.append(check("C2_TIMING","C2_CONFIRMATION",True,c2t,None,"INCOMPLETE","exact +5m checkpoint missing",c2t))
            final="INCOMPLETE"
        else:
            cs.append(check("C2_TIMING","C2_CONFIRMATION",True,c2t,c2t,"PASS","exact +5m checkpoint found",c2t))
            cc=all3(c2); c2a=cc["all3"]; expected=f"{direction}_ALL_3"; ok=c2a==expected
            cs.append(check("C2_PERSISTENCE","C2_CONFIRMATION",True,expected,c2a,"PASS" if ok else "FAIL",
                            "same directional ALL_3 survived" if ok else "ALL_3 did not survive C2",c2t,{"horizons":cc["horizons"]}))
            if not ok: final="TRADE_NOT_TAKEN"
            else:
                f=fidx.get(c2t)
                if not f:
                    cs.append(check("FUTURES_DATA","FUTURES_CONFIRMATION",True,c2t,None,"INCOMPLETE","exact futures checkpoint missing",c2t))
                    final="INCOMPLETE"
                else:
                    fs=f.get("state")
                    cs.append(check("FUTURES_DATA","FUTURES_CONFIRMATION",True,c2t,c2t,"PASS","exact futures checkpoint found",c2t,f))
                    allowed=BULL if direction=="BULLISH" else BEAR; aligned=fs in allowed
                    cs.append(check("FUTURES_ALIGNMENT","FUTURES_CONFIRMATION",True,sorted(allowed),fs,
                                    "PASS" if aligned else ("INCOMPLETE" if fs is None else "FAIL"),
                                    "futures supports direction" if aligned else "futures does not support direction",c2t))
                    final="TRADE_ELIGIBLE" if aligned else ("INCOMPLETE" if fs is None else "TRADE_NOT_TAKEN")
        events.append({"event_id":f"{date}-{d.strftime('%H%M')}-{direction}","session_date":date,"direction":direction,
                       "c1_timestamp":t,"c2_expected_timestamp":c2t,"c1_all3":c["all3"],"c2_all3":c2a,
                       "futures_state":fs,"final_decision":final,
                       "failed_check_ids":[x["check_id"] for x in cs if x["required"] and x["result"]=="FAIL"],
                       "incomplete_check_ids":[x["check_id"] for x in cs if x["required"] and x["result"]=="INCOMPLETE"],
                       "checks":cs})
    return {"model":MODEL,"session_date":date,"checkpoint_count":len(cps),"event_count":len(events),
            "decision_counts":dict(Counter(e["final_decision"] for e in events)),"checkpoints":cps,"events":events}

def load_canonical_dates(path):
    p=Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Canonical session source not found: {p}")
    dates=set()
    with p.open(newline="",encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            d=str(r.get("session_date") or "").strip()
            if d: dates.add(d)
    if not dates:
        raise ValueError(f"No canonical session_date values in {p}")
    return dates

def run_population(enrichment_root,futures_csv,output_root,only_dates=None,
                   canonical_csv="data/historical-evidence/oi-pattern-library-90d-historical-only-v1.csv"):
    er=Path(enrichment_root); out=Path(output_root); out.mkdir(parents=True,exist_ok=True); fidx=load_futures(futures_csv)
    canonical_dates=load_canonical_dates(canonical_csv)
    ds=[d for d in sorted(er.iterdir()) if d.is_dir() and (d/"enriched.json").exists() and d.name in canonical_dates]
    if only_dates: ds=[d for d in ds if d.name in only_dates]
    all_events=[]; sessions=[]; cp=0
    for d in ds:
        rep=audit_session(d.name,load_enriched(d/"enriched.json",d.name),fidx)
        (out/f"{d.name}.json").write_text(json.dumps(rep,indent=2,default=str))
        cp+=rep["checkpoint_count"]; all_events+=rep["events"]
        sessions.append({"session_date":d.name,"checkpoints":rep["checkpoint_count"],"events":rep["event_count"],
                         "decision_counts":rep["decision_counts"]})
    fields=["event_id","session_date","direction","c1_timestamp","c2_expected_timestamp","c1_all3","c2_all3",
            "futures_state","final_decision","failed_check_ids","incomplete_check_ids"]
    with (out/"all-events.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for e in all_events:w.writerow({k:(",".join(e[k]) if isinstance(e.get(k),list) else e.get(k)) for k in fields})
    summary={"model":MODEL,"sessions":len(ds),"checkpoints":cp,"events":len(all_events),
             "c1_detections":len(all_events),
             "c2_confirmed":sum(e.get("c2_all3")==f"{e['direction']}_ALL_3" for e in all_events),
             "c2_failed":sum("C2_PERSISTENCE" in e["failed_check_ids"] for e in all_events),
             "futures_confirmed":sum(e["final_decision"]=="TRADE_ELIGIBLE" for e in all_events),
             "futures_rejected":sum("FUTURES_ALIGNMENT" in e["failed_check_ids"] for e in all_events),
             "futures_missing":sum("FUTURES_DATA" in e["incomplete_check_ids"] for e in all_events),
             "decision_counts":dict(Counter(e["final_decision"] for e in all_events)),
             "event_direction_counts":dict(Counter(e["direction"] for e in all_events)),
             "sessions_detail":sessions,"futures_source":str(futures_csv),"enrichment_root":str(enrichment_root)}
    (out/"summary.json").write_text(json.dumps(summary,indent=2))
    return summary

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--enrichment-root",default="data/historical-evidence/historical-oi-enrichment")
    p.add_argument("--futures-csv",default="data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv")
    p.add_argument("--output-root",default="data/historical-evidence/canonical-decision-audit-v1")
    p.add_argument("--canonical-csv",default="data/historical-evidence/oi-pattern-library-90d-historical-only-v1.csv")
    p.add_argument("--date",action="append")
    a=p.parse_args()
    print(json.dumps(run_population(a.enrichment_root,a.futures_csv,a.output_root,set(a.date) if a.date else None,a.canonical_csv),indent=2))
if __name__=="__main__":main()
