"""Read-only EMA10-of-price slope inspection. No service or order operations."""
import argparse,csv,json,statistics,sys
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
IST=ZoneInfo('Asia/Kolkata')
WINDOWS=[('MORNING_BEARISH','09:25','12:05'),('MIDDAY_SIDEWAYS','12:15','14:05'),('AFTERNOON_BEARISH','14:10','14:40')]
ROOTS=[Path('data/historical-evidence/hilega-milega-underlying-cache-v1'),Path('data/recovery/october-2026/replay-input/replay-warmup'),Path('data/recovery/october-2026/replay-input'),Path('data/recovery/october-2026/nifty-cache')]
def index(roots):
    result={}
    for root in roots:
        for p in sorted(root.glob('????-??-??.json')):result[p.stem]=p
    return result

def bars(path,day,limit='15:29'):
    x=json.loads(path.read_text());raw=x.get('candles') or [];by={}
    for r in raw:
        t=datetime.fromisoformat(r['timestamp']).astimezone(IST)
        if t.date().isoformat()!=day or not '09:15'<=t.strftime('%H:%M')<=limit:continue
        if t in by and by[t]!=r:raise ValueError('CONFLICTING_DUPLICATE:'+t.isoformat())
        by[t]=r
    out=[];missing=[];first=datetime.fromisoformat(day+'T09:15:00+05:30')
    h,m=map(int,limit.split(':'));count=((h*60+m)-(9*60+15)+1)//5
    for i in range(count):
        t=first+timedelta(minutes=5*i);bucket=[by.get(t+timedelta(minutes=j)) for j in range(5)]
        if not all(bucket):missing.append(t.isoformat());continue
        out.append({'time':t,'close':float(bucket[-1]['close'])})
    return out,missing

def ema_update(previous,close):return close if previous is None else previous+(2/11)*(close-previous)

def run(args):
    files=index(args.cache_root or ROOTS);day=args.date
    if day not in files:raise ValueError('TARGET_CACHE_MISSING:'+day)
    prior=[(d,p) for d,p in sorted(files.items()) if d<day][-30:]
    ema=None;warm_bars=0;warm_days=[];warm_missing=[]
    for d,p in prior:
        bb,missing=bars(p,d)
        if not bb:continue
        if missing: # do not silently omit gaps in indicator history
            warm_missing.append({'date':d,'missing_5m':missing});continue
        for bar in bb:ema=ema_update(ema,bar['close']);warm_bars+=1
        warm_days.append(d)
    if warm_bars<150:raise ValueError('INSUFFICIENT_COMPLETE_WARMUP: need >=150 five-minute bars')
    if warm_missing:raise ValueError('INCOMPLETE_WARMUP_CACHES:'+json.dumps(warm_missing))
    bb,missing=bars(files[day],day,'14:44')
    if missing:raise ValueError('INCOMPLETE_TARGET_WINDOW:'+','.join(missing))
    observations=[];history=[ema]
    for b in bb:
        previous=ema;ema=ema_update(ema,b['close']);delta=ema-previous
        time=b['time'];tag=next((name for name,start,end in WINDOWS if start<=time.strftime('%H:%M')<=end),'OTHER')
        history.append(ema)
        observations.append(dict(session_date=day,candle_label=time.strftime('%H:%M'),available_at=(time+timedelta(minutes=5)).strftime('%H:%M'),window=tag,nifty_close=round(b['close'],4),previous_ema10=round(previous,6),ema10=round(ema,6),slope_points_5m=round(delta,6),slope_pct_5m=round(100*delta/previous,8),direction='RISING' if delta>1e-9 else 'FALLING' if delta<-1e-9 else 'FLAT',price_vs_ema='ABOVE' if b['close']>ema else 'BELOW' if b['close']<ema else 'EQUAL',slope_points_per_bar_15m=round((history[-1]-history[-4])/3,6) if len(history)>=4 else None))
    summaries=[]
    for name,start,end in WINDOWS:
        rows=[r for r in observations if r['window']==name];slopes=[r['slope_points_5m'] for r in rows]
        summary=dict(window=name,start=start,end=end,candles=len(rows),falling=sum(r['direction']=='FALLING' for r in rows),rising=sum(r['direction']=='RISING' for r in rows),flat=sum(r['direction']=='FLAT' for r in rows),mean_slope_points_5m=round(statistics.mean(slopes),4),median_abs_slope_points_5m=round(statistics.median(abs(v) for v in slopes),4),min_slope=round(min(slopes),4),max_slope=round(max(slopes),4),ema_first=rows[0]['ema10'],ema_last=rows[-1]['ema10'],ema_change_first_to_last=round(rows[-1]['ema10']-rows[0]['ema10'],4),price_below_ema=sum(r['price_vs_ema']=='BELOW' for r in rows),sign_changes=sum(a*b<0 for a,b in zip(slopes,slopes[1:])))
        summaries.append(summary)
    root=args.output_root;root.mkdir(parents=True,exist_ok=True)
    for name,rows in [('candles.csv',observations),('window-summary.csv',summaries)]:
        with (root/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print('EMA10: Nifty CLOSE · completed 5m candles · warmup',warm_bars,'bars')
    print('Windows use chart CANDLE LABELS; a 12:15 candle is available at 12:20 IST.')
    print('Window | Candles | Falling | Rising | Mean slope/5m | Median absolute slope | Below EMA | Sign changes')
    for s in summaries:print(f"{s['start']}-{s['end']} | {s['candles']} | {s['falling']} | {s['rising']} | {s['mean_slope_points_5m']:+.4f} | {s['median_abs_slope_points_5m']:.4f} | {s['price_below_ema']} | {s['sign_changes']}")
    print('\nCandle | Available | Close | EMA10 | Slope/5m | Direction | Price vs EMA')
    for r in observations:
        if r['window']!='OTHER':print(f"{r['candle_label']} | {r['available_at']} | {r['nifty_close']:.2f} | {r['ema10']:.4f} | {r['slope_points_5m']:+.4f} | {r['direction']} | {r['price_vs_ema']}")
    print('Output:',root,'; no strategy, service, order or original cache changes')

def self_test():
    assert abs(ema_update(100,111)-102)<1e-12
    assert ema_update(100,89)<100 and ema_update(100,100)==100
    assert (datetime(2026,10,12,12,15,tzinfo=IST)+timedelta(minutes=5)).strftime('%H:%M')=='12:20'
    assert len([i for i in range(75) if '09:25'<=(datetime(2026,10,12,9,15)+timedelta(minutes=i*5)).strftime('%H:%M')<='12:05'])==33
    print('PASS: EMA recursion, slope signs, candle availability and window boundaries')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--date',default='2026-10-12');p.add_argument('--cache-root',type=Path,action='append');p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-ema10-slope-oct12-v1'));p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test:self_test()
    else:run(a)
