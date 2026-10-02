#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,os,sys,urllib.parse,urllib.request,urllib.error
from dataclasses import dataclass
from datetime import date,datetime,timedelta
from pathlib import Path
from statistics import mean,median
from zoneinfo import ZoneInfo

IST=ZoneInfo('Asia/Kolkata'); UNDERLYING='NSE_INDEX|Nifty 50'

@dataclass
class Bar:
    ts:datetime; open:float; high:float; low:float; close:float
    volume:int|None=None; oi:int|None=None
    rsi:float|None=None; ema:float|None=None; wma:float|None=None

def fetch_1m(token,sd):
    enc=urllib.parse.quote(UNDERLYING,safe=''); ds=sd.isoformat()
    url=f'https://api.upstox.com/v3/historical-candle/{enc}/minutes/1/{ds}/{ds}'
    req=urllib.request.Request(url,headers={'Accept':'application/json','Authorization':f'Bearer {token}'})
    try:
        with urllib.request.urlopen(req,timeout=30) as r: p=json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'HTTP {e.code} {ds}: '+e.read().decode('utf-8','replace'))
    rows=(((p or {}).get('data') or {}).get('candles') or [])
    out=[]
    for x in rows:
        ts=datetime.fromisoformat(str(x[0])).astimezone(IST)
        if ts.date()!=sd: continue
        out.append(Bar(ts,float(x[1]),float(x[2]),float(x[3]),float(x[4]),None if len(x)<6 or x[5] is None else int(x[5]),None if len(x)<7 or x[6] is None else int(x[6])))
    return sorted(out,key=lambda b:b.ts)

def to5(rows):
    d={}
    for b in rows:
        t=b.ts.astimezone(IST)
        if (t.hour,t.minute)<(9,15) or (t.hour,t.minute)>(15,29): continue
        k=t.replace(minute=t.minute-t.minute%5,second=0,microsecond=0); d.setdefault(k,[]).append(b)
    out=[]
    for ts,g in sorted(d.items()):
        g=sorted(g,key=lambda b:b.ts)
        if len(g)!=5: continue
        if [x.ts.replace(second=0,microsecond=0) for x in g] != [ts+timedelta(minutes=i) for i in range(5)]: continue
        out.append(Bar(ts,g[0].open,max(x.high for x in g),min(x.low for x in g),g[-1].close,sum(x.volume or 0 for x in g),g[-1].oi))
    return out

def rsi_wilder(c,n=9):
    o=[None]*len(c)
    if len(c)<=n:return o
    gains=[0.0]*len(c); losses=[0.0]*len(c)
    for i in range(1,len(c)):
        z=c[i]-c[i-1]; gains[i]=max(z,0); losses[i]=max(-z,0)
    ag=sum(gains[1:n+1])/n; al=sum(losses[1:n+1])/n
    def calc(g,l):
        if l==0:return 100.0 if g>0 else 50.0
        rs=g/l; return 100-100/(1+rs)
    o[n]=calc(ag,al)
    for i in range(n+1,len(c)):
        ag=((n-1)*ag+gains[i])/n; al=((n-1)*al+losses[i])/n; o[i]=calc(ag,al)
    return o

def ema(v,n=3):
    o=[None]*len(v); a=2/(n+1); s=None
    for i,x in enumerate(v):
        if x is None: continue
        s=x if s is None else a*x+(1-a)*s; o[i]=s
    return o

def wma(v,n=21):
    o=[None]*len(v); den=n*(n+1)/2
    for i in range(n-1,len(v)):
        w=v[i-n+1:i+1]
        if any(x is None for x in w):continue
        o[i]=sum((j+1)*float(x) for j,x in enumerate(w))/den
    return o

def cup(a0,b0,a1,b1):return None not in (a0,b0,a1,b1) and a0<=b0 and a1>b1
def cdown(a0,b0,a1,b1):return None not in (a0,b0,a1,b1) and a0>=b0 and a1<b1
def full(b):return None not in (b.rsi,b.ema,b.wma) and b.rsi>50 and b.ema>50 and b.wma>50 and b.rsi>b.ema>b.wma
def f2(x):return '' if x is None else f'{x:.2f}'

def replay(bs):
    events=[]; regs=[]; active=False; weak=False; armed=False; at=''; reg=None; oc=False; oh=False
    for i,b in enumerate(bs):
        if None in (b.rsi,b.ema,b.wma):continue
        p=bs[i-1] if i else None; t=b.ts.strftime('%H:%M')
        rup=bool(p and p.rsi is not None and b.rsi>p.rsi); eup=bool(p and p.ema is not None and b.ema>p.ema)
        cre=bool(p and cup(p.rsi,p.ema,b.rsi,b.ema)); crw=bool(p and cup(p.rsi,p.wma,b.rsi,b.wma)); cew=bool(p and cup(p.ema,p.wma,b.ema,b.wma)); crd=bool(p and cdown(p.rsi,p.wma,b.rsi,b.wma))
        if t=='09:15' and full(b):oc=True; events.append((t,'OPENING_ALIGNMENT'))
        elif t=='09:20' and oc:
            if b.rsi>b.wma:oh=True; events.append((t,'OPENING_HOLDING'))
            else:oc=False; events.append((t,'OPENING_REJECTED_0920'))
        elif t=='09:25' and oc and oh:
            if b.rsi>b.wma and not active:
                active=True; reg={'source':'OPENING_PATH','armed_time':'','si':i,'start_time':t,'start_close':b.close,'weakening_count':0,'continuation_count':0}; events.append((t,'OPENING_BULLISH_CONFIRMED'))
            else:events.append((t,'OPENING_REJECTED_0925'))
            oc=oh=False
        if active:
            if weak:
                if b.rsi<b.wma:
                    reg.update(end_time=t,end_close=b.close,points_to_end=b.close-reg['start_close'],duration_minutes=int((b.ts-bs[reg['si']].ts).total_seconds()/60))
                    w=bs[reg['si']:i+1]; reg['mfe_points']=max(x.high for x in w)-reg['start_close']; reg['mae_points']=min(x.low for x in w)-reg['start_close']; regs.append(reg); events.append((t,'BULLISH_END_CONFIRMED')); active=weak=False; reg=None; continue
                weak=False; reg['continuation_count']+=1; events.append((t,'WEAKENING_RECOVERY_CONTINUATION'))
            if active and not weak and crd:
                weak=True; reg['weakening_count']+=1; events.append((t,'WEAKENING'))
            continue
        if cre: armed=True; at=t; events.append((t,'PATH1_ARMED'))
        p1=armed and b.rsi>50 and b.rsi>b.wma and b.ema>b.wma and rup and eup
        p2=crw and cew and rup and eup
        if p1 or p2:
            src='PATH_1_AND_PATH_2' if p1 and p2 else ('PATH_1_RSI_EMA_ARMED' if p1 else 'PATH_2_DUAL_WMA_CROSS')
            active=True; weak=False; reg={'source':src,'armed_time':at,'si':i,'start_time':t,'start_close':b.close,'weakening_count':0,'continuation_count':0}; events.append((t,'BULLISH_START:'+src)); armed=False; at=''
    if active and reg:
        w=bs[reg['si']:]; reg.update(end_time='',end_close=None,points_to_end=None,duration_minutes=int((bs[-1].ts-bs[reg['si']].ts).total_seconds()/60),mfe_points=max(x.high for x in w)-reg['start_close'],mae_points=min(x.low for x in w)-reg['start_close']); regs.append(reg)
    return events,regs

def main():
    a=argparse.ArgumentParser(); a.add_argument('--end-date',default='2026-09-21'); a.add_argument('--trading-sessions',type=int,default=30); a.add_argument('--calendar-lookback-days',type=int,default=70); a.add_argument('--output-dir',default='data/historical-evidence/branch-c-v2-7-daywise'); a.add_argument('--token-env',default='UPSTOX_ACCESS_TOKEN'); z=a.parse_args()
    tok=os.getenv(z.token_env)
    if not tok:raise SystemExit(f'Missing {z.token_env}; load .env first')
    end=date.fromisoformat(z.end_date); start=end-timedelta(days=z.calendar_lookback_days); m={}; d=start
    while d<=end:
        try:
            x=fetch_1m(tok,d); print(f'fetch {d}: candles={len(x)}');
            if x:m[d]=x
        except Exception as e:print(f'fetch {d}: ERROR {e}',file=sys.stderr)
        d+=timedelta(days=1)
    ds=sorted(m)
    if len(ds)<z.trading_sessions:raise SystemExit('Not enough sessions; increase --calendar-lookback-days')
    target=ds[-z.trading_sessions:]; warm=[x for x in ds if x<target[0]][-10:]; all5=[]
    for sd in warm+target:all5+=to5(m[sd])
    all5.sort(key=lambda b:b.ts); rs=rsi_wilder([b.close for b in all5]); es=ema(rs); ws=wma(rs)
    for b,r,e,w in zip(all5,rs,es,ws):b.rsi,b.ema,b.wma=r,e,w
    by={}
    for b in all5:
        if b.ts.date() in target:by.setdefault(b.ts.date(),[]).append(b)
    out=Path(z.output_dir); out.mkdir(parents=True,exist_ok=True); rr=[]; er=[]; dr=[]
    for sd in target:
        ev,rg=replay(by.get(sd,[])); er += [{'session_date':sd.isoformat(),'time':t,'event':e} for t,e in ev]
        done=[x for x in rg if x.get('points_to_end') is not None]; pts=[x['points_to_end'] for x in done]
        for x in rg:rr.append({'session_date':sd.isoformat(),'source':x['source'],'armed_time':x.get('armed_time',''),'bullish_start_time':x['start_time'],'bullish_start_close':f2(x['start_close']),'bullish_end_time':x.get('end_time',''),'bullish_end_close':f2(x.get('end_close')),'nifty_points_to_end':f2(x.get('points_to_end')),'duration_minutes':x.get('duration_minutes',''),'mfe_points':f2(x.get('mfe_points')),'mae_points':f2(x.get('mae_points')),'weakening_count':x.get('weakening_count',0),'continuation_count':x.get('continuation_count',0),'result':'SESSION_CENSORED' if x.get('points_to_end') is None else ('POSITIVE' if x['points_to_end']>0 else 'NEGATIVE' if x['points_to_end']<0 else 'FLAT')})
        dr.append({'session_date':sd.isoformat(),'regimes':len(rg),'completed':len(done),'session_censored':len(rg)-len(done),'positive':sum(x>0 for x in pts),'negative':sum(x<0 for x in pts),'day_net_nifty_points':f2(sum(pts)) if pts else '','avg_points':f2(mean(pts)) if pts else '','best_points':f2(max(pts)) if pts else '','worst_points':f2(min(pts)) if pts else ''})
    def wc(p,rows):
        if not rows:return
        with p.open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
    wc(out/'branch-c-v2-7-regimes-daywise.csv',rr); wc(out/'branch-c-v2-7-day-summary.csv',dr); wc(out/'branch-c-v2-7-events.csv',er)
    cp=[float(x['nifty_points_to_end']) for x in rr if x['nifty_points_to_end']!='']; pos=sum(x>0 for x in cp)
    s={'model':'BRANCH_C_HILEGA_MILEGA_V2_7_CANDIDATE','sessions':len(target),'first_session':target[0].isoformat(),'last_session':target[-1].isoformat(),'bullish_regimes':len(rr),'completed_regimes':len(cp),'session_censored':len(rr)-len(cp),'positive_regimes':pos,'negative_regimes':sum(x<0 for x in cp),'positive_rate_pct':pos/len(cp)*100 if cp else None,'total_nifty_points':sum(cp) if cp else None,'average_nifty_points':mean(cp) if cp else None,'median_nifty_points':median(cp) if cp else None,'best_nifty_points':max(cp) if cp else None,'worst_nifty_points':min(cp) if cp else None}
    (out/'branch-c-v2-7-summary.json').write_text(json.dumps(s,indent=2),encoding='utf-8')
    print('\n=== DAY-WISE VALIDATION ==='); print(f"{'DATE':10} {'REG':>3} {'DONE':>4} {'CENS':>4} {'POS':>3} {'NEG':>3} {'NET PTS':>10} {'AVG':>9} {'BEST':>9} {'WORST':>9}"); print('-'*82)
    for r in dr:print(f"{r['session_date']:10} {r['regimes']:>3} {r['completed']:>4} {r['session_censored']:>4} {r['positive']:>3} {r['negative']:>3} {r['day_net_nifty_points']:>10} {r['avg_points']:>9} {r['best_points']:>9} {r['worst_points']:>9}")
    print('\n=== REGIME DETAIL ===');
    for r in rr:print(r)
    print('\n=== SUMMARY ==='); print(json.dumps(s,indent=2)); print('\nOutputs in',out)
if __name__=='__main__':main()
