"""Read existing updated V2 replay artifacts. No broker, service or strategy changes."""
import argparse,bisect,csv,hashlib,json,math,statistics
from datetime import datetime,timedelta
from pathlib import Path

def write(p,rows):
    keys=list(dict.fromkeys(k for r in rows for k in r)) or ['status']
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)

def features(rows,n):
    if len(rows)<n:return None
    window=rows[-n:]
    if any(datetime.fromisoformat(b['available_at'])-datetime.fromisoformat(a['available_at'])!=timedelta(minutes=5) for a,b in zip(window,window[1:])):return None
    wma=[r['wma21'] for r in window];signs=[1 if r['rsi9']>r['wma21'] else -1 if r['rsi9']<r['wma21'] else 0 for r in window];nonzero=[s for s in signs if s]
    deltas=[b-a for a,b in zip(wma,wma[1:])]
    return dict(window_candles=n,window_start=window[0]['available_at'],available_at=window[-1]['available_at'],wma21=wma[-1],rsi9=window[-1]['rsi9'],wma_in_45_55=all(45<=v<=55 for v in wma),wma_min=min(wma),wma_max=max(wma),wma_range=max(wma)-min(wma),wma_net_change=wma[-1]-wma[0],last_wma_change=deltas[-1],mean_abs_wma_change=statistics.mean(abs(d) for d in deltas),rsi_wma_crossings=sum(a!=b for a,b in zip(nonzero,nonzero[1:])))

def candidates():
    return [dict(id=f'N{n}_R{r}_NET{d}_C{c}',n=n,max_range=r,max_net=d,min_crossings=c) for n in (3,5) for r in (.5,1,2) for d in (.25,.5,1) for c in (0,1,2)]

def sideways(p,f):
    return bool(f and f['wma_in_45_55'] and f['wma_range']<=p['max_range'] and abs(f['wma_net_change'])<=p['max_net'] and f['rsi_wma_crossings']>=p['min_crossings'])

def metrics(tt):
    gain=sum(max(0,t['points']) for t in tt);loss=sum(max(0,-t['points']) for t in tt);equity=peak=dd=0
    for t in sorted(tt,key=lambda t:(t['exit_time'],t['entry_time'])):
        equity+=t['points'];peak=max(peak,equity);dd=max(dd,peak-equity)
    return dict(trades=len(tt),winners=sum(t['points']>0 for t in tt),losers=sum(t['points']<0 for t in tt),gains=round(gain,2),losses=round(loss,2),net=round(gain-loss,2),gain_loss_ratio=gain/loss if loss else None,max_drawdown_points=round(dd,2))

def analyze(a):
    root=a.input_root;original=json.loads((root/'report.json').read_text());summary=list(csv.DictReader((root/'summary.csv').open()));out=a.output_root;out.mkdir(parents=True,exist_ok=True)
    sessions={};allrows=[];trades=[];coverage=[];hashes={}
    for path in sorted((root/'baseline-sessions').glob('????-??-??.json')):
        x=json.loads(path.read_text());day=x['session_date'];version=x.get('strategy_version')
        if version!=original['rules']['version']:raise ValueError('BASELINE_RULE_VERSION_MISMATCH:'+day)
        hashes[day]=hashlib.sha256(path.read_bytes()).hexdigest();rows=[];last=''
        for bar in sorted(x.get('audit',[]),key=lambda b:b['checkpoint']):
            if not bar.get('five_minute_label'):continue
            stamp=bar['checkpoint'];ind=bar.get('completed_5m_indicators') or {}
            if not all(ind.get(k) is not None and math.isfinite(float(ind[k])) for k in ('rsi9','wma21')):continue
            if stamp==last:continue
            last=stamp;r=dict(session_date=day,candle_label=bar['five_minute_label'],available_at=stamp,rsi9=float(ind['rsi9']),wma21=float(ind['wma21']));rows.append(r)
            for n in (3,5):
                f=features(rows,n)
                allrows.append(dict(r,window_candles=n,feature_status='AVAILABLE' if f else 'INSUFFICIENT_OR_NONADJACENT_EVIDENCE',**({k:v for k,v in f.items() if k not in r and k!='window_candles'} if f else {})))
        sessions[day]=rows;times=[r['available_at'] for r in rows]
        for t in x['trades']:
            k=bisect.bisect_right(times,t['entry_time'])-1
            ff={n:features(rows[:k+1],n) if k>=0 else None for n in (3,5)}
            trades.append(dict(t,session_date=day,features=ff))
        coverage.append(dict(session_date=day,completed_5m_rows=len(rows),baseline_trades=len(x['trades'])))
    if not sessions:raise ValueError('NO_UPDATED_BASELINE_SESSION_ARTIFACTS')
    ps=candidates();results=[];detail=[]
    for side in ('ALL','BULLISH','BEARISH'):
        for period in ('ONE_MONTH','THREE_MONTHS','EARLIER_TWO_MONTHS'):
            base=next(r for r in summary if r['period']==period and r['direction']==side and r['policy']=='BASELINE')
            selected=[t for t in trades if base['start']<=t['session_date']<=base['end'] and (side=='ALL' or t['direction']==side)]
            bm=metrics(selected)
            if bm['trades']!=int(base['trades']) or not math.isclose(bm['net'],float(base['net']),abs_tol=.011):raise ValueError('BASELINE_RECONCILIATION_FAILED:'+period+':'+side)
            for p in ps:
                blocked=[t for t in selected if sideways(p,t['features'][p['n']])];kept=[t for t in selected if not sideways(p,t['features'][p['n']])];mm=metrics(kept)
                results.append(dict(period=period,start=base['start'],end=base['end'],direction=side,policy=p['id'],**mm,baseline_net=bm['net'],net_delta=round(mm['net']-bm['net'],2),blocked_winners=sum(t['points']>0 for t in blocked),blocked_winner_points=round(sum(max(0,t['points']) for t in blocked),2),avoided_losers=sum(t['points']<0 for t in blocked),avoided_loss_points=round(sum(max(0,-t['points']) for t in blocked),2),unavailable_kept=sum(t['features'][p['n']] is None for t in selected)))
    for t in trades:
        for p in ps:
            f=t['features'][p['n']]
            if sideways(p,f):detail.append({k:t.get(k) for k in ('trade_id','session_date','direction','setup_source','signal_time','entry_time','entry_price','exit_time','exit_price','points')}|dict(policy=p['id'],category='BLOCKED_WINNER' if t['points']>0 else 'AVOIDED_LOSER' if t['points']<0 else 'BLOCKED_BREAKEVEN',**f))
    write(out/'candles.csv',allrows);write(out/'summary.csv',results);write(out/'blocked-trades.csv',detail);write(out/'coverage.csv',coverage)
    picks=[]
    for side in ('BULLISH','BEARISH'):
        earlier=[r for r in results if r['period']=='EARLIER_TWO_MONTHS' and r['direction']==side and r['trades']>=30 and r['avoided_losers']+r['blocked_winners']>=5]
        print('\n'+side+' — candidates ranked on earlier two months; later month shown separately')
        for r in sorted(earlier,key=lambda r:(-r['net'],r['max_drawdown_points']))[:5]:
            later=next(z for z in results if z['period']=='ONE_MONTH' and z['direction']==side and z['policy']==r['policy'])
            print(f"{r['policy']} | earlier delta {r['net_delta']:+.2f} | later net {later['net']:+.2f}, delta {later['net_delta']:+.2f} | later losses avoided {later['avoided_losers']} / winners blocked {later['blocked_winners']} | DD {later['max_drawdown_points']:.2f}")
            picks.append(dict(direction=side,policy=r['policy'],earlier=r,later=later))
        if not earlier:print('Insufficient affected trades for ranking.')
    # Illustrative configuration, fixed before reading outcomes; not a validated threshold.
    illustrative=next(p for p in ps if p['n']==3 and p['max_range']==1 and p['max_net']==.5 and p['min_crossings']==1)
    print('\n'+a.inspect_date+' · diagnostic N3_R1_NET0.5_C1 (research hypothesis)')
    print('Available | WMA21 | Band all 45-55 | Range3 | Net3 | RSI crossings | Sideways candidate')
    dayrows=sessions.get(a.inspect_date,[])
    for i,r in enumerate(dayrows):
        if not '12:00'<=r['available_at'][11:16]<='14:40':continue
        f=features(dayrows[:i+1],3)
        if f:print(f"{r['available_at'][11:16]} | {r['wma21']:.4f} | {f['wma_in_45_55']} | {f['wma_range']:.4f} | {f['wma_net_change']:+.4f} | {f['rsi_wma_crossings']} | {sideways(illustrative,f)}")
    for t in trades:
        if t['session_date']==a.inspect_date:print(f"ENTRY {t['direction']} {t['entry_time'][11:16]} | points {t['points']:+.2f} | illustrative sideways {sideways(illustrative,t['features'][3])}")
    (out/'report.json').write_text(json.dumps(dict(policies=ps,candidates=picks,baseline_rules=original['rules'],source_sha256=hashes,method='Causal completed-five-minute entry selection; all window values must be in 45-55; original entries/exits fixed; missing feature kept and counted.',warning='Not a full filtered lifecycle replay or an unseen validation sample. Thresholds are research hypotheses in RSI units, not Nifty points.',execution_enabled=False),indent=2))
    print('PASS: baseline totals reconciled; output:',out,'; no live changes')

def self_test():
    start=datetime.fromisoformat('2026-10-12T13:00:00+05:30')
    rr=[dict(available_at=(start+timedelta(minutes=i*5)).isoformat(),wma21=w,rsi9=r) for i,(w,r) in enumerate([(49.9,49),(50.1,51),(50,49)])]
    f=features(rr,3);p=dict(n=3,max_range=1,max_net=.5,min_crossings=1)
    assert sideways(p,f) and f['rsi_wma_crossings']==2
    trending=[dict(r,wma21=w) for r,w in zip(rr,[46,49,52])];assert not sideways(p,features(trending,3))
    oscillating=[dict(r,wma21=w) for r,w in zip(rr,[46,54,46])];assert not sideways(p,features(oscillating,3))
    outband=[dict(r,wma21=44) for r in rr];assert not sideways(p,features(outband,3))
    assert features(rr[:2],3) is None
    assert bisect.bisect_right([r['available_at'] for r in rr],'2026-10-12T13:07:00+05:30')-1==1
    print('PASS: flat versus trending/oscillating WMA, 45-55 band, crossings, insufficient history and causal lookup')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input-root',type=Path,default=Path('data/historical-evidence/hilega-ema10-trend-research-v1'));p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-wma21-sideways-research-v1'));p.add_argument('--inspect-date',default='2026-10-12');p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test:self_test()
    else:analyze(a)
