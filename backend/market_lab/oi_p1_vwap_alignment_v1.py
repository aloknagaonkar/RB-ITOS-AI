
from __future__ import annotations
import argparse, csv, json, statistics
from datetime import datetime
from pathlib import Path

VERSION="OI_P1_VWAP_ALIGNMENT_V1"

def walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)

def first(d,*keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None

def parse_dt(v, session_date=None):
    if v is None: return None
    s=str(v)
    if "T" in s:
        return datetime.fromisoformat(s)
    if session_date and len(s)>=5 and ":" in s:
        return datetime.fromisoformat(f"{session_date}T{s[:5]}:00+05:30")
    return None

def num(v):
    if v is None: return None
    try: return float(v)
    except: return None

def boolish(v):
    if isinstance(v,bool): return v
    if v is None: return False
    return str(v).strip().upper() in {"Y","YES","TRUE","1"}

def extract_events(obj):
    rows=[]
    seen=set()
    for d in walk(obj):
        direction=str(first(d,"direction","signal_direction") or "").upper()
        date=str(first(d,"session_date","date") or "")
        ts=first(d,"signal_timestamp","timestamp","time","checkpoint_timestamp")
        if direction not in {"BULLISH","BEARISH"} or not date or ts is None:
            continue
        dt=parse_dt(ts,date)
        if not dt: continue
        imbalance=num(first(d,"imbalance","oi_imbalance","five_minute_imbalance","five_min_imbalance","imbalance_5m"))
        activity=num(first(d,"activity","oi_activity","five_minute_activity","five_min_activity","activity_5m"))
        # Keep only real transition-like rows. Outcome/persistence fields help avoid unrelated dicts.
        p2=first(d,"p2","p2_persistence","persistence_2")
        p3=first(d,"p3","p3_persistence","persistence_3")
        p4=first(d,"p4","p4_persistence","persistence_4")
        out20=first(d,"outcome_20m","outcome20","classification_20m")
        plus10=num(first(d,"directional_10m","return_10m_points","points_10m","plus_10m"))
        plus20=num(first(d,"directional_20m","return_20m_points","points_20m","plus_20m"))
        if imbalance is None and activity is None and p2 is None and p3 is None and p4 is None and out20 is None:
            continue
        key=(date,dt.isoformat(),direction)
        if key in seen: continue
        seen.add(key)
        rows.append({
            "session_date":date,
            "event_dt":dt,
            "event_time":dt.strftime("%H:%M"),
            "direction":direction,
            "day_class":first(d,"day_class"),
            "spot":num(first(d,"spot","spot_price")),
            "atm":num(first(d,"moving_atm","atm","atm_strike")),
            "ce_5m_delta":num(first(d,"ce_5m_delta","ce_delta","ce5m_delta")),
            "pe_5m_delta":num(first(d,"pe_5m_delta","pe_delta","pe5m_delta")),
            "imbalance":imbalance,
            "activity":activity,
            "pcr_ratio":num(first(d,"pcr","pcr_ratio","current_pcr")),
            "pcr_5m_change":num(first(d,"pcr_change","pcr_5m_change","pcr_delta")),
            "session_imbalance":num(first(d,"session_imbalance","sess_imbalance")),
            "p2":boolish(p2),
            "p3":boolish(p3),
            "p4":boolish(p4),
            "outcome_20m":out20,
            "plus_10m":plus10,
            "plus_20m":plus20,
        })
    rows.sort(key=lambda r:(r["session_date"],r["event_dt"],r["direction"]))
    return rows

def load_vwap(path):
    obj=json.loads(Path(path).read_text())
    out={}
    for s in obj.get("sessions",[]):
        bars=[]
        for b in s.get("candles",[]):
            bb=dict(b)
            bb["_start"]=datetime.fromisoformat(bb["candle_start"])
            bb["_avail"]=datetime.fromisoformat(bb["decision_available_at"])
            bars.append(bb)
        out[s["session_date"]]={"day_class":s["day_class"],"bars":bars}
    return out

def causal_bar(bars,event_dt):
    xs=[b for b in bars if b["_avail"] <= event_dt]
    return xs[-1] if xs else None

def same_label_bar(bars,event_dt):
    label=event_dt.strftime("%H:%M")
    for b in bars:
        if b["candle_label"]==label:
            return b
    return None

def aligned(direction,side):
    return (direction=="BULLISH" and side=="ABOVE") or (direction=="BEARISH" and side=="BELOW")

def median(xs):
    xs=[x for x in xs if x is not None]
    return statistics.median(xs) if xs else None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--transitions",required=True)
    ap.add_argument("--vwap-profile",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--csv-output",required=True)
    ap.add_argument("--trend-days-only",action="store_true")
    args=ap.parse_args()

    trans=json.loads(Path(args.transitions).read_text())
    events=extract_events(trans)
    if not events:
        raise RuntimeError("No transition events detected. Inspect transition JSON field names; no silent fallback.")
    vw=load_vwap(args.vwap_profile)

    rows=[]
    missing=0
    for e in events:
        s=vw.get(e["session_date"])
        if not s:
            continue
        day_class=e["day_class"] or s["day_class"]
        if args.trend_days_only and day_class not in {"BULLISH_TREND_DAY","BEARISH_TREND_DAY"}:
            continue
        cb=causal_bar(s["bars"],e["event_dt"])
        sb=same_label_bar(s["bars"],e["event_dt"])
        if cb is None:
            missing += 1
            continue

        row={k:v for k,v in e.items() if k!="event_dt"}
        row["day_class"]=day_class
        row.update({
            # Causal VWAP information actually known when P1 is detected.
            "causal_vwap_candle":cb["candle_label"],
            "causal_vwap_available":cb["decision_available_at"][11:16],
            "causal_fut_open":cb["open"],
            "causal_fut_high":cb["high"],
            "causal_fut_low":cb["low"],
            "causal_fut_close":cb["close"],
            "causal_vwap":cb["vwap"],
            "causal_vwap_distance":cb["distance_points"],
            "causal_vwap_side":cb["side"],
            "causal_vwap_cross":cb["cross"],
            "causal_vwap_slope":cb["vwap_slope"],
            "vwap_aligned_at_p1":aligned(e["direction"],cb["side"]),
            # Same chart-label candle is shown only for visual validation;
            # its close is FUTURE relative to a P1 known at the label time.
            "same_label_candle": sb["candle_label"] if sb else None,
            "same_label_close_available": sb["decision_available_at"][11:16] if sb else None,
            "same_label_fut_close": sb["close"] if sb else None,
            "same_label_vwap": sb["vwap"] if sb else None,
            "same_label_distance": sb["distance_points"] if sb else None,
            "same_label_side": sb["side"] if sb else None,
            "same_label_is_post_p1": bool(sb and sb["_avail"] > e["event_dt"]),
        })
        rows.append(row)

    groups={}
    for direction in ("BULLISH","BEARISH"):
        xs=[r for r in rows if r["direction"]==direction]
        if not xs: continue
        aligned_x=[r for r in xs if r["vwap_aligned_at_p1"]]
        groups[direction]={
            "events":len(xs),
            "vwap_aligned_count":len(aligned_x),
            "vwap_aligned_pct":100*len(aligned_x)/len(xs),
            "median_abs_imbalance_aligned":median([abs(r["imbalance"]) for r in aligned_x if r["imbalance"] is not None]),
            "median_plus10_aligned":median([r["plus_10m"] for r in aligned_x]),
            "median_plus20_aligned":median([r["plus_20m"] for r in aligned_x]),
        }

    result={
        "research_version":VERSION,
        "methodology":{
            "p1":"existing OI transition event; no transition rule changed",
            "causal_vwap_join":"latest completed 5m futures VWAP candle with decision_available_at <= P1 timestamp",
            "same_label_candle":"reported for chart validation only; not used as information available at P1",
            "bullish_alignment":"causal completed futures close ABOVE VWAP",
            "bearish_alignment":"causal completed futures close BELOW VWAP",
            "research_only":True,
        },
        "event_count":len(rows),
        "missing_causal_vwap_count":missing,
        "summary":groups,
        "events":rows,
    }
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    fields=list(rows[0].keys())
    with Path(args.csv_output).open("w",newline="",encoding="utf-8") as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader(); w.writerows(rows)

    print(json.dumps({
        "research_version":VERSION,
        "event_count":len(rows),
        "missing_causal_vwap_count":missing,
        "summary":groups,
        "output":args.output,
        "csv_output":args.csv_output,
    },indent=2,allow_nan=False))

if __name__=="__main__":
    main()
