"""Causal EMA10 entry-filter research; baseline exits stay fixed. No live changes."""
import argparse,bisect,calendar,csv,hashlib,json,statistics,time
from datetime import date,timedelta
from pathlib import Path
import slope_data

def start_date(end,months):
    n=end.year*12+end.month-1-months;y,m=divmod(n,12);m+=1
    return date(y,m,min(end.day,calendar.monthrange(y,m)[1]))+timedelta(days=1)

def write(path,rows):
    keys=list(dict.fromkeys(k for r in rows for k in r)) or ['status']
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)

def metrics(rows):
    gain=sum(max(0,r['points']) for r in rows);loss=sum(max(0,-r['points']) for r in rows)
    running=peak=dd=0
    for r in sorted(rows,key=lambda r:(r['exit_time'],r['entry_time'])):
        running+=r['points'];peak=max(peak,running);dd=max(dd,peak-running)
    return dict(trades=len(rows),winners=sum(r['points']>0 for r in rows),losers=sum(r['points']<0 for r in rows),gains=round(gain,2),losses=round(loss,2),net=round(gain-loss,2),gain_loss_ratio=gain/loss if loss else None,max_drawdown_points=round(dd,2))

def features(slopes,close,ema,available):
    last=slopes[-1];recent=slopes[-3:];six=slopes[-6:]
    def streak(sign):
        n=0
        for s in reversed(slopes):
            if sign*s<=0:break
            n+=1
        return n
    return dict(available_at=available,slope=last,mean3=statistics.mean(recent) if len(recent)==3 else None,mean_abs3=statistics.mean(abs(v) for v in recent) if len(recent)==3 else None,sign_changes6=sum(a*b<0 for a,b in zip(six,six[1:])),falling_streak=streak(-1),rising_streak=streak(1),close=close,ema10=ema,last3=recent)

def policies():
    out=[dict(id='BASELINE',threshold=None,persistence=0,flat=None,price_gate=False)]
    for threshold in (0,.5,1,2,3,5):
        for persistence in (1,2,3):
            for flat in (None,.5,1):
                out.append(dict(id=f'S{threshold}_P{persistence}_FLAT{flat}',threshold=threshold,persistence=persistence,flat=flat,price_gate=False))
    return out

def accepts(p,side,f):
    if p['id']=='BASELINE':return True
    if not f:return False
    sign=1 if side=='BULLISH' else -1
    vals=f['last3'][-p['persistence']:]
    if len(vals)<p['persistence'] or not all(sign*s>0 and sign*s>=p['threshold'] for s in vals):return False
    if p['flat'] is not None and f['mean3'] is not None and abs(f['mean3'])<=p['flat']:return False
    return True

def run(a):
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    end=date.fromisoformat(a.end_date);begin=start_date(end,3);validation=start_date(end,1)
    roots=a.cache_root or list(engine.CACHE_ROOTS);idx=engine.cache_index(roots)
    out=a.output_root;out.mkdir(parents=True,exist_ok=True)
    ema=None;slopes=[];warm=0;day_features={};coverage=[];all_candles=[];hashes={};history_valid=True
    for d,p in sorted(idx.items()):
        if d>end.isoformat():continue
        raw=json.loads(p.read_text()).get('candles') or []
        if not raw:continue
        hashes[d]=hashlib.sha256(p.read_bytes()).hexdigest()
        # A full session is needed before carrying indicator state to the next date.
        bars,missing=slope_data.bars(p,d,'14:54' if d==end.isoformat() else '15:29')
        target=d>=begin.isoformat()
        if missing:
            coverage.append(dict(session_date=d,status='EMA_INCOMPLETE',issue='Missing exact 5m bars; subsequent EMA state cannot be certified'))
            history_valid=False;continue
        if not history_valid:
            if target:coverage.append(dict(session_date=d,status='EMA_HISTORY_INVALID',issue='Earlier incomplete nonempty session; recover it and rerun'))
            continue
        fs=[]
        for b in bars:
            prev=ema;ema=slope_data.ema_update(ema,b['close']);warm+=1
            if prev is None:continue
            slopes.append(ema-prev);available=(b['time']+timedelta(minutes=5)).isoformat()
            f=features(slopes,b['close'],ema,available);fs.append(f)
            if target:all_candles.append({k:v for k,v in f.items() if k!='last3'}|dict(session_date=d,candle_label=b['time'].isoformat()))
        if target:
            if warm<150:coverage.append(dict(session_date=d,status='WARMUP_INSUFFICIENT',issue='Need 150 completed warmup bars'))
            else:day_features[d]=fs
    trades=[];started=time.monotonic();dates=sorted(day_features)
    for i,d in enumerate(dates,1):
        print(f'[{i}/{len(dates)}] {d}: baseline replay/cache; elapsed {time.monotonic()-started:.1f}s',flush=True)
        try:
            x=engine.load_session(d,out/'baseline-sessions',roots)
            fs=day_features[d];times=[f['available_at'] for f in fs]
            for t in x['trades']:
                k=bisect.bisect_right(times,t['entry_time'])-1
                if k<0:raise ValueError('NO_COMPLETED_EMA_AT_ENTRY:'+t['trade_id'])
                trades.append(dict(t,session_date=d,ema_features=fs[k]))
            coverage.append(dict(session_date=d,status='EVALUATED',issue=''))
        except (ValueError,FileNotFoundError,engine.ReplayBusyError) as e:coverage.append(dict(session_date=d,status='REPLAY_FAILED',issue=str(e)))
        write(out/'coverage.csv',coverage)
    ps=policies();summary=[];details=[]
    for period,first,last in [('ONE_MONTH',validation,end),('THREE_MONTHS',begin,end),('EARLIER_TWO_MONTHS',begin,validation-timedelta(days=1))]:
        for side in ('ALL','BULLISH','BEARISH'):
            baseline=[t for t in trades if first.isoformat()<=t['session_date']<=last.isoformat() and (side=='ALL' or t['direction']==side)]
            bm=metrics(baseline)
            for p in ps:
                selected=[t for t in baseline if accepts(p,t['direction'],t['ema_features'])];blocked=[t for t in baseline if not accepts(p,t['direction'],t['ema_features'])];mm=metrics(selected)
                summary.append(dict(period=period,start=first.isoformat(),end=last.isoformat(),direction=side,policy=p['id'],**mm,baseline_net=bm['net'],net_delta=round(mm['net']-bm['net'],2),blocked_winners=sum(t['points']>0 for t in blocked),blocked_winner_points=round(sum(max(0,t['points']) for t in blocked),2),avoided_losers=sum(t['points']<0 for t in blocked),avoided_loss_points=round(sum(max(0,-t['points']) for t in blocked),2)))
    for t in trades:
        f=t['ema_features'];row={k:t.get(k) for k in ('trade_id','session_date','direction','setup_source','signal_time','entry_time','entry_price','exit_time','exit_price','points')};row.update({k:v for k,v in f.items() if k!='last3'});row['accepted_policy_count']=sum(accepts(p,t['direction'],f) for p in ps[1:]);details.append(row)
    daily=[]
    for d in dates:
        tt=[t for t in trades if t['session_date']==d]
        for p in ps:daily.append(dict(session_date=d,policy=p['id'],**metrics([t for t in tt if accepts(p,t['direction'],t['ema_features'])])))
    write(out/'summary.csv',summary);write(out/'trades.csv',details);write(out/'candles.csv',all_candles);write(out/'daily.csv',daily)
    cov={r['session_date']:r for r in coverage};dt=begin
    while dt<=end:
        stamp=dt.isoformat()
        if stamp not in cov:
            status='EMPTY_CACHE' if stamp in idx else 'CACHE_MISSING';coverage.append(dict(session_date=stamp,status=status,issue='Not independently verified as an exchange holiday'))
        dt+=timedelta(days=1)
    write(out/'coverage.csv',coverage)
    picks=[]
    for side in ('BULLISH','BEARISH'):
        candidates=[r for r in summary if r['period']=='EARLIER_TWO_MONTHS' and r['direction']==side and r['policy']!='BASELINE' and r['trades']>=30]
        top=sorted(candidates,key=lambda r:(-r['net'],r['max_drawdown_points']))[:5]
        print('\n'+side+' — top earlier-two-month candidates (>=30 retained trades); NOT live recommendations',flush=True)
        for r in top:
            later=next(z for z in summary if z['period']=='ONE_MONTH' and z['direction']==side and z['policy']==r['policy'])
            print(f"{r['policy']} | earlier net {r['net']:+.2f} | later net {later['net']:+.2f} vs baseline {later['baseline_net']:+.2f} | later winners blocked {later['blocked_winners']} | later losers avoided {later['avoided_losers']} | later DD {later['max_drawdown_points']:.2f}",flush=True)
            picks.append(dict(direction=side,policy=r['policy'],earlier=r,later=later))
        if not top:print('Insufficient retained trades for ranking; inspect coverage.',flush=True)
    for row in summary:
        if row['policy']=='BASELINE':print(f"BASELINE {row['period']} {row['direction']} | trades {row['trades']} | gains {row['gains']:.2f} | losses {row['losses']:.2f} | net {row['net']:+.2f} | DD {row['max_drawdown_points']:.2f}",flush=True)
    (out/'report.json').write_text(json.dumps(dict(end=end.isoformat(),rules=engine.RULES,policies=ps,candidates=picks,coverage=coverage,input_sha256=hashes,engine_sha256=hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),method='Causal filtering of existing V2 trades with baseline entry/exit prices fixed. Not a full rerun of filtered strategy ownership/reentries.',validation='Chronological later-month comparison; this month has already been examined and is not pristine unseen evidence.',execution_enabled=False),indent=2))
    print('Output:',out,'; no live configuration, service or order changes',flush=True)

def self_test():
    assert start_date(date(2026,10,12),1)==date(2026,9,13)
    f=features([-5,-4,-3],100,110,'12:15');assert f['falling_streak']==3 and f['mean3']==-4
    p=dict(id='TEST',threshold=2,persistence=3,flat=1)
    assert accepts(p,'BEARISH',f) and not accepts(p,'BULLISH',f)
    mixed=features([-5,5,-.1],100,110,'12:15');assert mixed['sign_changes6']==2 and not accepts(p,'BEARISH',mixed)
    assert metrics([dict(points=10,entry_time='a',exit_time='b'),dict(points=-4,entry_time='b',exit_time='c')])['net']==6
    times=['12:15','12:20'];assert bisect.bisect_right(times,'12:17')-1==0
    print('PASS: calendar windows, slope/persistence, sideways cancellation, metrics and no-lookahead entry lookup')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--end-date',default='2026-10-12');parser.add_argument('--cache-root',type=Path,action='append');parser.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-ema10-trend-research-v1'));parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
    if args.self_test:self_test()
    else:run(args)
