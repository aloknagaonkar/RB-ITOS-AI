from __future__ import annotations

import argparse, csv, json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

MODEL = "ATM_PLUS_MINUS_5_TRADE_PATH_ANALYSIS_V1"
HORIZONS = (1,2,5,10,15,20,30)

def rows_from_payload(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("rows","data","candles","items"):
            if isinstance(payload.get(k), list):
                return payload[k]
    raise ValueError("No OHLC rows found")

def side_of(r):
    for k in ("side","option_type","type"):
        v = r.get(k)
        if v is not None and str(v).upper() in ("CE","PE"):
            return str(v).upper()
    return None

def f(r,k):
    try:
        return float(r[k])
    except Exception:
        return None

@dataclass(frozen=True)
class Signal:
    signal_time: str
    atm: float
    direction: str
    @property
    def option_type(self):
        return "CE" if self.direction=="BULLISH" else "PE"

def parse_signal(raw, session_date, default_direction):
    parts = raw.split(":")
    if len(parts) not in (3,4):
        raise ValueError("Use HH:MM:ATM[:BULLISH|BEARISH]")
    hh, mm, atm = parts[:3]
    direction = parts[3].upper() if len(parts)==4 else default_direction.upper()
    return Signal(f"{session_date}T{int(hh):02d}:{int(mm):02d}:00+05:30", float(atm), direction)

def load_rows(path, session_date):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    out=[]
    for r in rows_from_payload(payload):
        if not isinstance(r, dict): continue
        ts=r.get("timestamp")
        if not isinstance(ts,str) or not ts.startswith(session_date): continue
        if side_of(r) is None or f(r,"strike") is None: continue
        if any(f(r,k) is None for k in ("open","high","low","close")): continue
        out.append(r)
    return out

def build_index(rows):
    idx={}
    for r in rows:
        key=(r["timestamp"], float(r["strike"]), side_of(r))
        if key in idx: raise ValueError(f"Duplicate row {key}")
        idx[key]=r
    return idx

def pct(x, entry): return (x/entry-1.0)*100.0

def first_hit(path, entry, threshold, up):
    trigger=entry*(1+threshold/100.0 if up else 1-threshold/100.0)
    field="high" if up else "low"
    start=path[0][0]
    for ts,r in path:
        v=float(r[field])
        if (v>=trigger if up else v<=trigger):
            return ts.isoformat(), (ts-start).total_seconds()/60
    return None, None

def analyze_one(idx, sig, strike, offset, horizon):
    sdt=datetime.fromisoformat(sig.signal_time)
    edt=sdt+timedelta(minutes=1)
    key=(edt.isoformat(), strike, sig.option_type)
    erow=idx.get(key)
    base={"model":MODEL,"signal_time":sig.signal_time,"direction":sig.direction,
          "option_type":sig.option_type,"signal_atm":sig.atm,"strike":strike,
          "offset":offset,"entry_time":edt.isoformat()}
    if erow is None:
        return {**base,"status":"REJECT","reason_code":"EXACT_ENTRY_ROW_UNAVAILABLE"}
    entry=float(erow["open"])
    path=[]
    for m in range(horizon+1):
        ts=edt+timedelta(minutes=m)
        r=idx.get((ts.isoformat(), strike, sig.option_type))
        if r is not None: path.append((ts,r))
    if not path or path[0][0]!=edt:
        return {**base,"status":"REJECT","reason_code":"ENTRY_PATH_UNAVAILABLE","entry_price":entry}
    lows=[float(r["low"]) for _,r in path]
    highs=[float(r["high"]) for _,r in path]
    out={**base,"status":"PASS","reason_code":None,"entry_price":entry,
         "path_rows":len(path),"path_end_time":path[-1][0].isoformat(),
         "min_low":min(lows),"max_high":max(highs),
         "mae_pct":pct(min(lows),entry),"mfe_pct":pct(max(highs),entry)}
    for h in HORIZONS:
        if h>horizon: continue
        ts=edt+timedelta(minutes=h-1)
        r=idx.get((ts.isoformat(), strike, sig.option_type))
        out[f"ret_{h}m_pct"]=pct(float(r["close"]),entry) if r else None
    sl5_ts=None
    for th in (5.0,7.5,10.0):
        ts,mins=first_hit(path,entry,th,False)
        tag=str(th).replace(".","_")
        out[f"hit_minus_{tag}"]=ts is not None
        out[f"time_to_minus_{tag}_min"]=mins
        if th==5.0 and ts: sl5_ts=datetime.fromisoformat(ts)
    for th in (5.0,10.0,20.0):
        ts,mins=first_hit(path,entry,th,True)
        tag=str(th).replace(".","_")
        out[f"hit_plus_{tag}"]=ts is not None
        out[f"time_to_plus_{tag}_min"]=mins
    if sl5_ts is None:
        for k in ("recovered_to_entry_after_minus5","recovered_to_plus5_after_minus5",
                  "recovered_to_plus10_after_minus5","recovered_to_plus20_after_minus5",
                  "post_minus5_max_high","post_minus5_mfe_pct"):
            out[k]=None
    else:
        post=[(ts,r) for ts,r in path if ts>=sl5_ts]
        postmax=max(float(r["high"]) for _,r in post)
        out["post_minus5_max_high"]=postmax
        out["post_minus5_mfe_pct"]=pct(postmax,entry)
        out["recovered_to_entry_after_minus5"]=postmax>=entry
        out["recovered_to_plus5_after_minus5"]=postmax>=entry*1.05
        out["recovered_to_plus10_after_minus5"]=postmax>=entry*1.10
        out["recovered_to_plus20_after_minus5"]=postmax>=entry*1.20
    return out

def auto_option_file(session_date):
    matches=sorted(Path("data").glob(f"historical-option-ohlc-cache-*/*NSE_INDEX_Nifty_50__{session_date}__*__w5.json"))
    return matches[0] if len(matches)==1 else None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--session-date",required=True)
    ap.add_argument("--option-file",type=Path)
    ap.add_argument("--direction",choices=("BULLISH","BEARISH"),default="BULLISH")
    ap.add_argument("--signal",action="append",required=True)
    ap.add_argument("--strike-step",type=float,default=50.0)
    ap.add_argument("--horizon-minutes",type=int,default=30)
    ap.add_argument("--csv",type=Path)
    ap.add_argument("--json-output",type=Path)
    a=ap.parse_args()
    opt=a.option_file or auto_option_file(a.session_date)
    if opt is None:
        raise SystemExit("Could not uniquely resolve option OHLC file; pass --option-file")
    sigs=[parse_signal(x,a.session_date,a.direction) for x in a.signal]
    idx=build_index(load_rows(opt,a.session_date))
    rows=[]
    for s in sigs:
        for off in range(-5,6):
            rows.append(analyze_one(idx,s,s.atm+off*a.strike_step,off,a.horizon_minutes))
    report={"status":"PASS","model":MODEL,"session_date":a.session_date,
            "option_file":str(opt),"signals":[asdict(s) for s in sigs],"rows":rows}
    if a.csv:
        a.csv.parent.mkdir(parents=True,exist_ok=True)
        fields=[]
        seen=set()
        for r in rows:
            for k in r:
                if k not in seen:
                    seen.add(k); fields.append(k)
        with a.csv.open("w",newline="",encoding="utf-8") as fh:
            w=csv.DictWriter(fh,fieldnames=fields); w.writeheader(); w.writerows(rows)
    if a.json_output:
        a.json_output.parent.mkdir(parents=True,exist_ok=True)
        a.json_output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))

if __name__=="__main__":
    main()
