from __future__ import annotations
import argparse,csv,json,statistics
from collections import defaultdict
from datetime import datetime,timedelta
from pathlib import Path
VERSION="VWAP_TREND_DAY_PROFILE_V1"
DATE_ALIASES=("session_date","date"); CLASS_ALIASES=("day_class","class","trend_class","classification")
TS_ALIASES=("timestamp","time","datetime"); VWAP_ALIASES=("futures_vwap","vwap","session_vwap"); VOL_ALIASES=("volume","vol")
def pick(r,ks,required=True):
    for k in ks:
        if k in r and str(r[k]).strip()!="": return r[k]
    if required: raise KeyError(f"Missing {ks}; available={sorted(r)}")
def f(x): return float(str(x).replace(',',''))
def med(xs):
    ys=[x for x in xs if x is not None]; return statistics.median(ys) if ys else None
def pct(n,d): return None if not d else 100*n/d
def load_classification(p):
    with p.open(newline='',encoding='utf-8-sig') as h: rows=list(csv.DictReader(h))
    return {str(pick(r,DATE_ALIASES)):str(pick(r,CLASS_ALIASES)) for r in rows}
def load_futures(p):
    with p.open(newline='',encoding='utf-8-sig') as h: rows=list(csv.DictReader(h))
    out=defaultdict(list)
    for r in rows:
        ts=datetime.fromisoformat(str(pick(r,TS_ALIASES))); d=str(pick(r,DATE_ALIASES,False) or ts.date())
        vv=pick(r,VWAP_ALIASES,False)
        out[d].append(dict(timestamp=ts,open=f(r['open']),high=f(r['high']),low=f(r['low']),close=f(r['close']),volume=f(pick(r,VOL_ALIASES)),source_vwap=f(vv) if vv is not None else None))
    for d in out: out[d].sort(key=lambda x:x['timestamp'])
    return out
def add_vwap(rows):
    pv=vol=0.0
    for r in rows:
        tp=(r['high']+r['low']+r['close'])/3; pv+=tp*r['volume']; vol+=r['volume']; calc=pv/vol if vol else None
        r['vwap']=r['source_vwap'] if r['source_vwap'] is not None else calc
    return rows
def bucket5(ts): return ts.replace(minute=(ts.minute//5)*5,second=0,microsecond=0)
def aggregate(rows):
    g=defaultdict(list)
    for r in rows:
        hm=(r['timestamp'].hour,r['timestamp'].minute)
        if (9,20)<=hm<=(15,29): g[bucket5(r['timestamp'])].append(r)
    bars=[]
    for st in sorted(g):
        xs=g[st]
        if len(xs)!=5: continue
        last=xs[-1]; dist=last['close']-last['vwap']; side='ABOVE' if dist>0 else ('BELOW' if dist<0 else 'AT')
        bars.append(dict(candle_start=st.isoformat(),candle_label=st.strftime('%H:%M'),candle_close_time=(st+timedelta(minutes=5)).strftime('%H:%M'),decision_available_at=(st+timedelta(minutes=5)).isoformat(),open=xs[0]['open'],high=max(x['high'] for x in xs),low=min(x['low'] for x in xs),close=last['close'],volume=sum(x['volume'] for x in xs),vwap=last['vwap'],distance_points=dist,side=side))
    for i,b in enumerate(bars):
        prev=bars[i-1] if i else None; ch=None if prev is None else b['vwap']-prev['vwap']; b['vwap_change_5m']=ch
        b['vwap_slope']='RISING' if ch is not None and ch>0 else ('FALLING' if ch is not None and ch<0 else 'FLAT_OR_FIRST')
        b['cross']='NONE'
        if prev and prev['side']!='ABOVE' and b['side']=='ABOVE': b['cross']='CROSS_ABOVE'
        elif prev and prev['side']!='BELOW' and b['side']=='BELOW': b['cross']='CROSS_BELOW'
    for i,b in enumerate(bars):
        for n in (2,3,4):
            seq=bars[i:i+n]; b[f'accept_{n}cp']=len(seq)==n and b['side'] in ('ABOVE','BELOW') and all(x['side']==b['side'] for x in seq)
    return bars
def sess_summary(cls,bars):
    n=len(bars); aligned='ABOVE' if cls=='BULLISH_TREND_DAY' else ('BELOW' if cls=='BEARISH_TREND_DAY' else None)
    first=next((b for b in bars if aligned and b['side']==aligned and b['accept_3cp']),None)
    return dict(bar_count=n,above_pct=pct(sum(b['side']=='ABOVE' for b in bars),n),below_pct=pct(sum(b['side']=='BELOW' for b in bars),n),cross_count=sum(b['cross']!='NONE' for b in bars),first_3cp_aligned_candle_label=first['candle_label'] if first else None,first_3cp_aligned_decision_available_at=first['decision_available_at'] if first else None,median_abs_distance_points=med([abs(b['distance_points']) for b in bars]),rising_vwap_pct=pct(sum(b['vwap_slope']=='RISING' for b in bars),n),falling_vwap_pct=pct(sum(b['vwap_slope']=='FALLING' for b in bars),n))
def agg(sessions):
    ss=[s['summary'] for s in sessions]
    return dict(session_count=len(ss),median_above_pct=med([x['above_pct'] for x in ss]),median_below_pct=med([x['below_pct'] for x in ss]),median_cross_count=med([x['cross_count'] for x in ss]),median_abs_distance_points=med([x['median_abs_distance_points'] for x in ss]),median_rising_vwap_pct=med([x['rising_vwap_pct'] for x in ss]),median_falling_vwap_pct=med([x['falling_vwap_pct'] for x in ss]),sessions_with_3cp_aligned_acceptance=sum(x['first_3cp_aligned_candle_label'] is not None for x in ss))
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--classification',required=True); ap.add_argument('--futures-vwap',required=True); ap.add_argument('--output',required=True); ap.add_argument('--csv-output',required=True); a=ap.parse_args()
    classes=load_classification(Path(a.classification)); counts={c:list(classes.values()).count(c) for c in sorted(set(classes.values()))}; expected={'BULLISH_TREND_DAY':18,'BEARISH_TREND_DAY':18,'MIXED_DAY':54}
    if len(classes)!=90 or counts!=expected: raise RuntimeError(f'Canonical 90-day population mismatch: n={len(classes)} counts={counts}')
    fut=load_futures(Path(a.futures_vwap)); sessions=[]; missing=[]
    for d,cls in sorted(classes.items()):
        if d not in fut: missing.append(d); continue
        bars=aggregate(add_vwap(fut[d])); sessions.append({'session_date':d,'day_class':cls,'summary':sess_summary(cls,bars),'candles':bars})
    result={'research_version':VERSION,'scope':{'classified_session_count':len(classes),'class_counts':counts,'loaded_session_count':len(sessions),'missing_futures_sessions':missing},'methodology':{'instrument':'NIFTY FUTURES','analysis_window':'09:20-15:29','analysis_granularity':'5-minute','vwap':'existing prospective cumulative session VWAP when present; otherwise cumulative ((H+L+C)/3)*volume / cumulative volume','chart_timestamp_semantics':'candle_label is interval START; decision_available_at is 5 minutes later after candle completion','above':'completed 5m futures close > VWAP','below':'completed 5m futures close < VWAP','acceptance':'2/3/4 consecutive completed 5m closes on same VWAP side','research_only':True,'strategy_rule_changed':False},'class_summary':{c:agg([s for s in sessions if s['day_class']==c]) for c in expected},'sessions':sessions}
    Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    fields=['session_date','day_class','candle_label','candle_close_time','decision_available_at','open','high','low','close','vwap','distance_points','side','cross','vwap_change_5m','vwap_slope','accept_2cp','accept_3cp','accept_4cp']
    with Path(a.csv_output).open('w',newline='',encoding='utf-8') as h:
        w=csv.DictWriter(h,fieldnames=fields); w.writeheader()
        for s in sessions:
            for b in s['candles']: w.writerow({'session_date':s['session_date'],'day_class':s['day_class'],**{k:b.get(k) for k in fields if k not in ('session_date','day_class')}})
    print(json.dumps({'research_version':VERSION,'class_counts':counts,'loaded_sessions':len(sessions),'missing_sessions':missing,'class_summary':result['class_summary'],'output':a.output,'csv_output':a.csv_output},indent=2))
if __name__=='__main__': main()
