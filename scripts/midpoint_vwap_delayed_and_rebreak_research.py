#!/usr/bin/env python3
from __future__ import annotations
import csv, glob, json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

ROOT=Path('data/historical-evidence')
FRAMEWORK_GLOB=str(ROOT/'opening-candle-midpoint-framework-v1-1-*.json')
FUTURES_CSV=ROOT/'midpoint-v2-nifty-futures-vwap-v1-all180.csv'
UNDERLYING_GLOB=str(ROOT/'underlying-ohlc-*.csv')
OUTDIR=ROOT/'hilega-pcr-oi-support-research-v1'/'midpoint-vwap-delayed-and-rebreak-research-v1'
A_CSV=OUTDIR/'delayed-vwap-confirmation-events-v1.csv'
B_CSV=OUTDIR/'midpoint-retest-rebreak-events-v1.csv'
SUMMARY=OUTDIR/'summary-v1.txt'
VWAP_THRESHOLD=5.0
WINDOWS=(1,2,3,5,10)

def dt(s): return datetime.fromisoformat(s)
def key(x): return x.isoformat()
def fnum(r,*ks):
    for k in ks:
        v=r.get(k)
        if v not in (None,''): return float(v)
    return None

def walk(o):
    if isinstance(o,dict):
        if o.get('session_date') and o.get('setup_type') in {'RED_BREAK','GREEN_BREAK'} and o.get('boundary_break_timestamp'):
            yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o,list):
        for v in o: yield from walk(v)

def load_events():
    files=sorted(glob.glob(FRAMEWORK_GLOB)); out=[]; seen=set()
    if not files: raise FileNotFoundError(FRAMEWORK_GLOB)
    for p in files:
        with open(p) as fh: obj=json.load(fh)
        for e in walk(obj):
            k=(e.get('session_date'),e.get('setup_type'),e.get('boundary_break_timestamp'),e.get('reference_high'),e.get('reference_low'),e.get('reference_midpoint'))
            if k in seen: continue
            seen.add(k); out.append(e)
    out.sort(key=lambda e:(e['session_date'],e['boundary_break_timestamp'],e['setup_type']))
    return files,out

def load_futures():
    out={}
    with FUTURES_CSV.open(newline='') as fh:
        for r in csv.DictReader(fh):
            ts=r.get('timestamp'); c=fnum(r,'close'); v=fnum(r,'session_vwap','vwap')
            if ts and c is not None and v is not None: out[ts]={'close':c,'vwap':v,'diff':c-v}
    return out

def load_underlying():
    files=sorted(glob.glob(UNDERLYING_GLOB)); out={}; conflicts=0
    if not files: raise FileNotFoundError(UNDERLYING_GLOB)
    for p in files:
        with open(p,newline='') as fh:
            for r in csv.DictReader(fh):
                ts=r.get('timestamp') or r.get('datetime') or r.get('time')
                vals=[fnum(r,'open'),fnum(r,'high'),fnum(r,'low'),fnum(r,'close')]
                if not ts or any(v is None for v in vals): continue
                rec=dict(zip(('open','high','low','close'),vals))
                if ts in out and out[ts]!=rec: conflicts+=1; continue
                out[ts]=rec
    return files,out,conflicts

def direction(e): return e.get('direction') or ('BEARISH' if e['setup_type']=='RED_BREAK' else 'BULLISH')

def candidate_a(e,fut):
    t0=dt(e['boundary_break_timestamp']); d=direction(e); cur=fut.get(key(t0))
    if not cur: return None,None,'MISSING_T0_FUTURES'
    prior=[fut[key(t0-timedelta(minutes=i))]['diff'] for i in range(5,-1,-1) if key(t0-timedelta(minutes=i)) in fut]
    if not prior: return None,cur['diff'],'MISSING_PRIOR_FUTURES'
    ok=(cur['diff']<-5 and any(x>=-5 for x in prior)) if d=='BEARISH' else (cur['diff']>5 and any(x<=5 for x in prior))
    return ok,cur['diff'],'AVAILABLE'

def structural_valid(d,c,mid): return c<=mid if d=='BEARISH' else c>=mid
def beyond(d,c,b): return c<b if d=='BEARISH' else c>b
def vwconfirm(d,x): return x<-5 if d=='BEARISH' else x>5

def study_a(events,fut,u):
    rows=[]
    for e in events:
        d=direction(e); mid=float(e['reference_midpoint']); b=float(e['reference_low'] if d=='BEARISH' else e['reference_high']); t0=dt(e['boundary_break_timestamp'])
        ca,t0diff,status=candidate_a(e,fut)
        r={'session_date':e['session_date'],'direction':d,'setup_type':e['setup_type'],'reference_high':e.get('reference_high'),'reference_low':e.get('reference_low'),'reference_midpoint':mid,'boundary_break_timestamp':e['boundary_break_timestamp'],'primary_outcome':e.get('primary_outcome'),'candidate_a_status':status,'candidate_a_at_t0':ca,'t0_vwap_distance':t0diff,'delayed_eligible':ca is False,'first_delayed_confirmation_timestamp':None,'delay_minutes':None,'confirmation_vwap_distance':None,'confirmation_underlying_close':None,'stop_reason':None}
        if ca is not False:
            r['stop_reason']='ALREADY_CANDIDATE_A' if ca else status; rows.append(r); continue
        for m in range(1,11):
            ts=t0+timedelta(minutes=m); k=key(ts); uu=u.get(k); ff=fut.get(k)
            if not uu: r['stop_reason']=f'MISSING_UNDERLYING_TPLUS_{m}'; break
            if not structural_valid(d,uu['close'],mid): r['stop_reason']=f'MIDPOINT_INVALIDATION_TPLUS_{m}'; break
            if not beyond(d,uu['close'],b): continue
            if ff and vwconfirm(d,ff['diff']):
                r.update(first_delayed_confirmation_timestamp=k,delay_minutes=m,confirmation_vwap_distance=ff['diff'],confirmation_underlying_close=uu['close'],stop_reason='CONFIRMED'); break
        if r['stop_reason'] is None: r['stop_reason']='NO_CONFIRMATION_WITHIN_10M'
        rows.append(r)
    return rows

def touch(c,mid): return c['low']<=mid<=c['high']
def cross_against(d,c,mid): return c>mid if d=='BEARISH' else c<mid
def original_side(d,c,mid): return c<mid if d=='BEARISH' else c>mid
def inside_boundary(d,c,b): return c>=b if d=='BEARISH' else c<=b
def fresh_break(d,c,b): return c<b if d=='BEARISH' else c>b

def study_b(events,fut,u):
    rows=[]
    for e in events:
        d=direction(e); mid=float(e['reference_midpoint']); b=float(e['reference_low'] if d=='BEARISH' else e['reference_high']); t0=dt(e['boundary_break_timestamp'])
        r={'session_date':e['session_date'],'direction':d,'setup_type':e['setup_type'],'reference_high':e.get('reference_high'),'reference_low':e.get('reference_low'),'reference_midpoint':mid,'boundary_break_timestamp':e['boundary_break_timestamp'],'primary_outcome':e.get('primary_outcome'),'midpoint_retest_timestamp':None,'temporary_reclaim_timestamp':None,'failed_reclaim_timestamp':None,'boundary_reset_timestamp':None,'rebreak_timestamp':None,'pattern_type':None,'vwap_at_retest':None,'vwap_at_temporary_reclaim':None,'vwap_at_failed_reclaim':None,'vwap_at_rebreak':None}
        retest=temp=failed=reset=None
        for m in range(1,361):
            ts=t0+timedelta(minutes=m)
            if ts.date()!=t0.date() or ts.hour>15 or (ts.hour==15 and ts.minute>30): break
            k=key(ts); uu=u.get(k)
            if not uu: continue
            if retest is None:
                if touch(uu,mid):
                    retest=ts; r['midpoint_retest_timestamp']=k
                    if k in fut: r['vwap_at_retest']=fut[k]['diff']
                    if cross_against(d,uu['close'],mid):
                        temp=ts; r['temporary_reclaim_timestamp']=k
                        if k in fut: r['vwap_at_temporary_reclaim']=fut[k]['diff']
                continue
            if temp is None and cross_against(d,uu['close'],mid):
                temp=ts; r['temporary_reclaim_timestamp']=k
                if k in fut: r['vwap_at_temporary_reclaim']=fut[k]['diff']
            if failed is None and original_side(d,uu['close'],mid):
                failed=ts; r['failed_reclaim_timestamp']=k
                if k in fut: r['vwap_at_failed_reclaim']=fut[k]['diff']
            if reset is None and inside_boundary(d,uu['close'],b):
                reset=ts; r['boundary_reset_timestamp']=k
            if failed and reset and ts>max(failed,reset) and fresh_break(d,uu['close'],b):
                r['rebreak_timestamp']=k; r['pattern_type']='TEMPORARY_RECLAIM_FAILED' if temp else 'TOUCH_REJECTION'
                if k in fut: r['vwap_at_rebreak']=fut[k]['diff']
                break
        rows.append(r)
    return rows

def write_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True); fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with path.open('w',newline='') as fh:
        w=csv.DictWriter(fh,fieldnames=fields); w.writeheader(); w.writerows(rows)

def pct(n,d): return 0 if not d else 100*n/d
def np(n,d): return f'{n:4d} ({pct(n,d):6.2f}%)'

def summary_a(rows):
    lines=['STUDY A — DELAYED VWAP CONFIRMATION','='*100]; elig=[r for r in rows if r['delayed_eligible']]
    for d in ('BEARISH','BULLISH','COMBINED'):
        s=elig if d=='COMBINED' else [r for r in elig if r['direction']==d]; c=[r for r in s if r['delay_minutes'] is not None]
        lines += [f'\n{d}',f'  NOT-A eligible events         : {len(s)}',f'  confirmed within 10m         : {np(len(c),len(s))}']
        for w in WINDOWS: lines.append(f'  cumulative confirmed <= {w:2d}m : {np(sum(1 for r in c if int(r["delay_minutes"])<=w),len(s))}')
        if c: lines.append(f'  median confirmation delay    : {median(int(r["delay_minutes"]) for r in c):.2f}m')
        lines.append(f'  stop reasons                 : {dict(Counter(r["stop_reason"] for r in s))}')
    return lines

def summary_b(rows):
    lines=['\n\nSTUDY B — MIDPOINT RETEST / FAILED RECLAIM / REBREAK','='*100]
    for d in ('BEARISH','BULLISH','COMBINED'):
        s=rows if d=='COMBINED' else [r for r in rows if r['direction']==d]
        ret=[r for r in s if r['midpoint_retest_timestamp']]; tmp=[r for r in s if r['temporary_reclaim_timestamp']]; fail=[r for r in s if r['failed_reclaim_timestamp']]; reb=[r for r in s if r['rebreak_timestamp']]
        lines += [f'\n{d}',f'  structural events            : {len(s)}',f'  midpoint retest              : {np(len(ret),len(s))}',f'  temporary reclaim close      : {np(len(tmp),len(s))}',f'  return to original side      : {np(len(fail),len(s))}',f'  fresh boundary rebreak       : {np(len(reb),len(s))}',f'  rebreak pattern types        : {dict(Counter(r["pattern_type"] for r in reb))}']
    return lines

def main():
    ff,events=load_events(); fut=load_futures(); uf,u,conflicts=load_underlying()
    a=study_a(events,fut,u); b=study_b(events,fut,u); write_csv(A_CSV,a); write_csv(B_CSV,b)
    lines=['MIDPOINT + VWAP DELAYED / REBREAK RESEARCH V1','='*100,'RESEARCH ONLY — Candidate A unchanged; no runtime/execution changes.','',f'framework files              = {len(ff)}',f'framework structural events  = {len(events)}',f'underlying files             = {len(uf)}',f'underlying duplicate conflict= {conflicts}',f'futures minute rows          = {len(fut)}',f'underlying minute rows       = {len(u)}','']
    lines += summary_a(a)+summary_b(b)+['','INTERPRETATION GUARD','Descriptive research only. Do not promote delayed windows or rebreak patterns into production rules without separate validation / forward observation.','',f'STUDY A CSV = {A_CSV}',f'STUDY B CSV = {B_CSV}',f'SUMMARY     = {SUMMARY}']
    OUTDIR.mkdir(parents=True,exist_ok=True); SUMMARY.write_text('\n'.join(lines)+'\n'); print('\n'.join(lines))
    print('\n'+'='*100+'\n2026-08-25 MANUAL CHECK\n'+'='*100)
    for r in a:
        if r['session_date']=='2026-08-25': print('A',r['direction'],'T0=',r['boundary_break_timestamp'],'candA=',r['candidate_a_at_t0'],'t0_vwap=',r['t0_vwap_distance'],'delayed=',r['first_delayed_confirmation_timestamp'],'delay=',r['delay_minutes'],'confirm_vwap=',r['confirmation_vwap_distance'],'stop=',r['stop_reason'])
    for r in b:
        if r['session_date']=='2026-08-25': print('B',r['direction'],'T0=',r['boundary_break_timestamp'],'retest=',r['midpoint_retest_timestamp'],'temp_reclaim=',r['temporary_reclaim_timestamp'],'failed_reclaim=',r['failed_reclaim_timestamp'],'boundary_reset=',r['boundary_reset_timestamp'],'rebreak=',r['rebreak_timestamp'],'pattern=',r['pattern_type'])

if __name__=='__main__': main()
