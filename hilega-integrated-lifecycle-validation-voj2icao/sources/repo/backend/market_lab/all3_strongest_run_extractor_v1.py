from __future__ import annotations
import argparse, csv, json
from pathlib import Path

HORIZONS=("5m","10m","15m")

BULLISH_DATES={
"2026-05-18","2026-05-20","2026-05-25","2026-06-02","2026-06-12","2026-06-16",
"2026-06-17","2026-06-18","2026-06-24","2026-07-06","2026-07-10","2026-07-13",
"2026-07-17","2026-07-27","2026-07-29","2026-08-03","2026-08-25","2026-09-02"}
BEARISH_DATES={
"2026-05-12","2026-05-19","2026-05-29","2026-06-01","2026-06-23","2026-06-29",
"2026-07-07","2026-07-08","2026-07-14","2026-07-16","2026-07-22","2026-08-18",
"2026-08-24","2026-08-26","2026-08-27","2026-09-03","2026-09-07","2026-09-08"}

def load_rows(path):
    with Path(path).open(newline="") as f:
        return list(csv.DictReader(f))

def all3_state(hrows):
    s=[hrows.get(h,{}).get("existing_horizon_state") for h in HORIZONS]
    if any(x in (None,"","NA") for x in s): return "INCOMPLETE"
    if all(x=="BULLISH" for x in s): return "BULLISH_ALL_3"
    if all(x=="BEARISH" for x in s): return "BEARISH_ALL_3"
    return "MIXED"

def build_states(rows):
    grouped={}
    for r in rows:
        grouped.setdefault((r["session_date"],r["timestamp"]),{})[r["horizon"]]=r
    by={}
    for (d,ts),hrows in grouped.items():
        by.setdefault(d,[]).append((ts,all3_state(hrows)))
    for d in by: by[d].sort(key=lambda x:x[0])
    return by

def runs(states):
    out=[]; i=0
    while i<len(states):
        ts,state=states[i]
        if state not in {"BULLISH_ALL_3","BEARISH_ALL_3"}:
            i+=1; continue
        j=i+1
        while j<len(states) and states[j][1]==state: j+=1
        out.append({
            "state":state,
            "start_timestamp":states[i][0],
            "end_timestamp":states[j-1][0],
            "candles":j-i,
            "duration_minutes":(j-i)*5,
        })
        i=j
    return out

def session_stats(rs, expected_state):
    relevant=[r for r in rs if r["state"]==expected_state]
    counter_state="BEARISH_ALL_3" if expected_state=="BULLISH_ALL_3" else "BULLISH_ALL_3"
    counter=[r for r in rs if r["state"]==counter_state]
    best=max(relevant,key=lambda r:(r["candles"],r["start_timestamp"])) if relevant else None
    return {
        "best":best,
        "mean_expected_run": None if not relevant else sum(r["candles"] for r in relevant)/len(relevant),
        "mean_counter_run": None if not counter else sum(r["candles"] for r in counter)/len(counter),
        "expected_total_candles":sum(r["candles"] for r in relevant),
        "counter_total_candles":sum(r["candles"] for r in counter),
        "expected_run_count":len(relevant),
        "counter_run_count":len(counter),
    }

def select(by, dates, expected_state, n):
    rows=[]
    for d in sorted(dates):
        if d not in by: continue
        rs=runs(by[d]); s=session_stats(rs,expected_state)
        if not s["best"]: continue
        b=s["best"]
        rows.append({
            "session_date":d,
            "day_type":"BULLISH_DAY" if expected_state=="BULLISH_ALL_3" else "BEARISH_DAY",
            "direction":"BULLISH" if expected_state=="BULLISH_ALL_3" else "BEARISH",
            "all3_state":expected_state,
            "start_timestamp":b["start_timestamp"],
            "end_timestamp":b["end_timestamp"],
            "candles":b["candles"],
            "duration_minutes":b["duration_minutes"],
            "mean_expected_run":s["mean_expected_run"],
            "mean_counter_run":s["mean_counter_run"],
            "expected_total_candles":s["expected_total_candles"],
            "counter_total_candles":s["counter_total_candles"],
        })
    rows.sort(key=lambda r:(r["candles"], r["mean_expected_run"], r["expected_total_candles"]), reverse=True)
    return rows[:n]

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--rows-csv",required=True)
    p.add_argument("--top",type=int,default=5)
    p.add_argument("--csv-output",required=True)
    p.add_argument("--json-output",required=True)
    a=p.parse_args(argv)
    by=build_states(load_rows(a.rows_csv))
    bull=select(by,BULLISH_DATES,"BULLISH_ALL_3",a.top)
    bear=select(by,BEARISH_DATES,"BEARISH_ALL_3",a.top)
    combined=bull+bear

    cp=Path(a.csv_output); cp.parent.mkdir(parents=True,exist_ok=True)
    with cp.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(combined[0].keys()))
        w.writeheader(); w.writerows(combined)

    payload={"model":"ALL3_STRONGEST_RUN_EXTRACTOR_V1","bullish":bull,"bearish":bear}
    jp=Path(a.json_output); jp.parent.mkdir(parents=True,exist_ok=True)
    jp.write_text(json.dumps(payload,indent=2)+"\n")
    print(json.dumps(payload,indent=2))

if __name__=="__main__": main()
