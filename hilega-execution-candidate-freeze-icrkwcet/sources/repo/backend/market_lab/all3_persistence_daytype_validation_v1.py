from __future__ import annotations
import argparse, csv, json, statistics
from pathlib import Path

MODEL="ALL3_PERSISTENCE_DAYTYPE_VALIDATION_V1"
HORIZONS=("5m","10m","15m")

FROZEN_BULLISH={
"2026-05-18","2026-05-20","2026-05-25","2026-06-02","2026-06-12","2026-06-16",
"2026-06-17","2026-06-18","2026-06-24","2026-07-06","2026-07-10","2026-07-13",
"2026-07-17","2026-07-27","2026-07-29","2026-08-03","2026-08-25","2026-09-02"}
FROZEN_BEARISH={
"2026-05-12","2026-05-19","2026-05-29","2026-06-01","2026-06-23","2026-06-29",
"2026-07-07","2026-07-08","2026-07-14","2026-07-16","2026-07-22","2026-08-18",
"2026-08-24","2026-08-26","2026-08-27","2026-09-03","2026-09-07","2026-09-08"}
FROZEN_LABELS={**{d:"BULLISH_DAY" for d in FROZEN_BULLISH},
               **{d:"BEARISH_DAY" for d in FROZEN_BEARISH}}

def load_rows(path):
    with Path(path).open(newline="") as f:
        return list(csv.DictReader(f))

def load_labels(path=None):
    labels=dict(FROZEN_LABELS)
    if not path: return labels
    with Path(path).open(newline="") as f:
        for r in csv.DictReader(f):
            d=r["session_date"].strip()
            label=r["day_type"].strip().upper()
            if label not in {"BULLISH_DAY","BEARISH_DAY","MIXED_REVERSAL_DAY"}:
                raise ValueError(f"Unsupported day_type {label!r} for {d}")
            labels[d]=label
    return labels

def all3_state(hrows):
    states=[hrows.get(h,{}).get("existing_horizon_state") for h in HORIZONS]
    if any(s in (None,"","NA") for s in states): return "INCOMPLETE"
    if all(s=="BULLISH" for s in states): return "BULLISH_ALL_3"
    if all(s=="BEARISH" for s in states): return "BEARISH_ALL_3"
    return "MIXED"

def session_states(rows):
    grouped={}
    for r in rows:
        grouped.setdefault((r["session_date"],r["timestamp"]),{})[r["horizon"]]=r
    out={}
    for (d,ts),hrows in grouped.items():
        out.setdefault(d,[]).append((ts,all3_state(hrows)))
    for d in out: out[d].sort(key=lambda x:x[0])
    return out

def directional_runs(states):
    runs=[]; i=0
    while i<len(states):
        ts,state=states[i]
        if state not in {"BULLISH_ALL_3","BEARISH_ALL_3"}:
            i+=1; continue
        j=i+1
        while j<len(states) and states[j][1]==state: j+=1
        runs.append({"state":state,"start_timestamp":states[i][0],
                     "end_timestamp":states[j-1][0],"length_candles":j-i})
        i=j
    return runs

def mean(v): return None if not v else statistics.mean(v)
def median(v): return None if not v else statistics.median(v)
def vmax(v): return None if not v else max(v)
def ratio(a,b): return None if a is None or b in (None,0) else a/b

def summarize_direction(runs,state):
    x=[r["length_candles"] for r in runs if r["state"]==state]
    return {"run_count":len(x),"total_candles":sum(x),"mean_run_length":mean(x),
            "median_run_length":median(x),"max_run_length":vmax(x),
            "run_length_1_count":sum(n==1 for n in x),
            "run_length_2_count":sum(n==2 for n in x),
            "run_length_3plus_count":sum(n>=3 for n in x)}

def summarize_session(d,states,label):
    runs=directional_runs(states)
    bull=summarize_direction(runs,"BULLISH_ALL_3")
    bear=summarize_direction(runs,"BEARISH_ALL_3")
    total=bull["total_candles"]+bear["total_candles"]
    if label=="BULLISH_DAY": dom,counter=bull,bear
    elif label=="BEARISH_DAY": dom,counter=bear,bull
    else: dom=counter=None
    return {
      "session_date":d,"day_type":label,"bullish":bull,"bearish":bear,
      "directional_candle_total":total,
      "bullish_directional_share":None if total==0 else bull["total_candles"]/total,
      "bearish_directional_share":None if total==0 else bear["total_candles"]/total,
      "dominant_mean_run_length":None if dom is None else dom["mean_run_length"],
      "counter_mean_run_length":None if counter is None else counter["mean_run_length"],
      "dominant_max_run_length":None if dom is None else dom["max_run_length"],
      "counter_max_run_length":None if counter is None else counter["max_run_length"],
      "dominant_to_counter_mean_ratio":None if dom is None else ratio(dom["mean_run_length"],counter["mean_run_length"]),
      "dominant_mean_exceeds_counter":None if dom is None or dom["mean_run_length"] is None or counter["mean_run_length"] is None else dom["mean_run_length"]>counter["mean_run_length"],
      "dominant_max_exceeds_counter":None if dom is None or dom["max_run_length"] is None or counter["max_run_length"] is None else dom["max_run_length"]>counter["max_run_length"],
    }

def aggregate(sessions,label):
    ss=[s for s in sessions if s["day_type"]==label]
    if not ss: return {"session_count":0,"note":"No frozen sessions supplied for this day type."}
    bm=[s["bullish"]["mean_run_length"] for s in ss if s["bullish"]["mean_run_length"] is not None]
    rm=[s["bearish"]["mean_run_length"] for s in ss if s["bearish"]["mean_run_length"] is not None]
    bx=[s["bullish"]["max_run_length"] for s in ss if s["bullish"]["max_run_length"] is not None]
    rx=[s["bearish"]["max_run_length"] for s in ss if s["bearish"]["max_run_length"] is not None]
    out={"session_count":len(ss),
         "bullish_mean_run_length_across_sessions":mean(bm),
         "bearish_mean_run_length_across_sessions":mean(rm),
         "bullish_median_of_session_mean_run_length":median(bm),
         "bearish_median_of_session_mean_run_length":median(rm),
         "bullish_mean_max_run_length":mean(bx),"bearish_mean_max_run_length":mean(rx),
         "bullish_total_candles":sum(s["bullish"]["total_candles"] for s in ss),
         "bearish_total_candles":sum(s["bearish"]["total_candles"] for s in ss),
         "bullish_1c_runs":sum(s["bullish"]["run_length_1_count"] for s in ss),
         "bearish_1c_runs":sum(s["bearish"]["run_length_1_count"] for s in ss),
         "bullish_2c_runs":sum(s["bullish"]["run_length_2_count"] for s in ss),
         "bearish_2c_runs":sum(s["bearish"]["run_length_2_count"] for s in ss),
         "bullish_3plus_runs":sum(s["bullish"]["run_length_3plus_count"] for s in ss),
         "bearish_3plus_runs":sum(s["bearish"]["run_length_3plus_count"] for s in ss)}
    if label in {"BULLISH_DAY","BEARISH_DAY"}:
        cm=[s for s in ss if s["dominant_mean_exceeds_counter"] is not None]
        cx=[s for s in ss if s["dominant_max_exceeds_counter"] is not None]
        out.update({
          "sessions_dominant_mean_exceeds_counter":sum(bool(s["dominant_mean_exceeds_counter"]) for s in cm),
          "sessions_comparable_for_mean":len(cm),
          "dominant_mean_exceeds_counter_fraction":None if not cm else sum(bool(s["dominant_mean_exceeds_counter"]) for s in cm)/len(cm),
          "sessions_dominant_max_exceeds_counter":sum(bool(s["dominant_max_exceeds_counter"]) for s in cx),
          "sessions_comparable_for_max":len(cx),
          "dominant_max_exceeds_counter_fraction":None if not cx else sum(bool(s["dominant_max_exceeds_counter"]) for s in cx)/len(cx)})
    return out

def mixed_balance(sessions):
    ss=[s for s in sessions if s["day_type"]=="MIXED_REVERSAL_DAY"]
    if not ss:
        return {"session_count":0,"note":"No MIXED_REVERSAL_DAY dates were pre-frozen; none are invented. Use --labels-csv for pre-frozen mixed/reversal dates."}
    diffs=[]
    for s in ss:
        a=s["bullish"]["mean_run_length"]; b=s["bearish"]["mean_run_length"]
        if a is not None and b is not None: diffs.append(abs(a-b))
    return {"session_count":len(ss),
            "mean_absolute_bull_bear_mean_run_difference":mean(diffs),
            "median_absolute_bull_bear_mean_run_difference":median(diffs)}

def flat(s):
    b=s["bullish"]; r=s["bearish"]
    return {"session_date":s["session_date"],"day_type":s["day_type"],
      "bull_run_count":b["run_count"],"bull_total_candles":b["total_candles"],
      "bull_mean_run":b["mean_run_length"],"bull_median_run":b["median_run_length"],"bull_max_run":b["max_run_length"],
      "bull_1c_runs":b["run_length_1_count"],"bull_2c_runs":b["run_length_2_count"],"bull_3plus_runs":b["run_length_3plus_count"],
      "bear_run_count":r["run_count"],"bear_total_candles":r["total_candles"],
      "bear_mean_run":r["mean_run_length"],"bear_median_run":r["median_run_length"],"bear_max_run":r["max_run_length"],
      "bear_1c_runs":r["run_length_1_count"],"bear_2c_runs":r["run_length_2_count"],"bear_3plus_runs":r["run_length_3plus_count"],
      "dominant_mean_run":s["dominant_mean_run_length"],"counter_mean_run":s["counter_mean_run_length"],
      "dominant_max_run":s["dominant_max_run_length"],"counter_max_run":s["counter_max_run_length"],
      "dominant_to_counter_mean_ratio":s["dominant_to_counter_mean_ratio"],
      "dominant_mean_exceeds_counter":s["dominant_mean_exceeds_counter"]}

def write_csv(rows,path):
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    if not rows: p.write_text(""); return
    with p.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

def build_report(rows,labels):
    by=session_states(rows); expected=set(labels); present=set(by)
    ss=[summarize_session(d,by[d],labels[d]) for d in sorted(expected & present)]
    return {"status":"PASS","model":MODEL,
      "hypothesis":{"bullish_days":"longer BULLISH_ALL_3 persistence and shorter bearish counter-runs",
                    "bearish_days":"longer BEARISH_ALL_3 persistence and shorter bullish counter-runs",
                    "mixed_reversal_days":"more balanced persistence"},
      "role":"DESCRIPTIVE_RESEARCH_ONLY","day_labels_role":"EVALUATION_ONLY",
      "state_definition_changed":False,"strategy_logic_changed":False,"threshold_optimization":False,
      "expected_session_count":len(expected),"present_labeled_session_count":len(expected & present),
      "missing_labeled_sessions":sorted(expected-present),"unlabeled_sessions_ignored":sorted(present-expected),
      "day_type_aggregates":{"BULLISH_DAY":aggregate(ss,"BULLISH_DAY"),
                             "BEARISH_DAY":aggregate(ss,"BEARISH_DAY"),
                             "MIXED_REVERSAL_DAY":mixed_balance(ss)},
      "sessions":ss}

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--rows-csv",required=True)
    p.add_argument("--labels-csv")
    p.add_argument("--sessions-csv",required=True)
    p.add_argument("--summary-json",required=True)
    a=p.parse_args(argv)
    report=build_report(load_rows(a.rows_csv),load_labels(a.labels_csv))
    write_csv([flat(s) for s in report["sessions"]],a.sessions_csv)
    out=Path(a.summary_json); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ("status","model","expected_session_count","present_labeled_session_count","missing_labeled_sessions","day_type_aggregates")},indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
