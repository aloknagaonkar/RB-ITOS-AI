"""Isolated full V2 lifecycle research. Live files, configuration and orders untouched."""
import argparse,bisect,calendar,copy,csv,hashlib,json,math,time
from datetime import date,datetime,timedelta
from pathlib import Path
from unittest.mock import patch
from market_lab import hilega_v2_alignment_replay_v1 as engine

MODES=('BASELINE','BULLISH_FILTER','BEARISH_FILTER','COMBINED')
RULES={'BULLISH':{'window':3,'max_range':.5,'max_net':.5},'BEARISH':{'window':5,'max_range':2,'max_net':.5}}
ORIGINAL_FACTORY=engine.ExitFirstCanonical
ORIGINAL_GATE=engine.WmaGapGate

def start_date(end,months):
    n=end.year*12+end.month-1-months;y,m=divmod(n,12);m+=1
    return date(y,m,min(end.day,calendar.monthrange(y,m)[1]))+timedelta(days=1)
def write(p,rows):
    keys=list(dict.fromkeys(k for r in rows for k in r)) or ['status']
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
def metrics(tt):
    gain=sum(max(0,t['points']) for t in tt);loss=sum(max(0,-t['points']) for t in tt);running=peak=dd=0
    for t in sorted(tt,key=lambda t:(t['exit_time'],t['entry_time'])):
        running+=t['points'];peak=max(peak,running);dd=max(dd,peak-running)
    return dict(trades=len(tt),winners=sum(t['points']>0 for t in tt),losers=sum(t['points']<0 for t in tt),gains=round(gain,2),losses=round(loss,2),net=round(gain-loss,2),gain_loss_ratio=gain/loss if loss else None,max_drawdown_points=round(dd,2))

def wma_lookup(baseline):
    rows=[]
    for a in baseline['audit']:
        s=a.get('completed_5m_indicators') or {}
        if a.get('five_minute_label') and s.get('wma21') is not None:rows.append((a['checkpoint'],float(s['wma21'])))
    return sorted(dict(rows).items())
def state_at(rows,at,n):
    k=bisect.bisect_right([r[0] for r in rows],at)-1;selected=rows[max(0,k-n+1):k+1]
    if len(selected)!=n:return None
    if any(datetime.fromisoformat(b[0])-datetime.fromisoformat(a[0])!=timedelta(minutes=5) for a,b in zip(selected,selected[1:])):return None
    values=[r[1] for r in selected]
    return dict(available_at=selected[-1][0],window=n,range=max(values)-min(values),net=values[-1]-values[0],wma21=values[-1])
def blocks(mode,side,state):
    applies=mode=='COMBINED' or mode=='BULLISH_FILTER' and side=='BULLISH' or mode=='BEARISH_FILTER' and side=='BEARISH'
    r=RULES[side]
    return bool(applies and state and state['range']<=r['max_range'] and abs(state['net'])<=r['max_net'])

def gate_factory(mode,lookup,rejections):
    class Gate(ORIGINAL_GATE):
        def evaluate(self,**kw):
            accepted,checks=super().evaluate(**kw);kept=[]
            for event in accepted:
                side=engine.direction(event);at=event.entry_time.isoformat();state=state_at(lookup,at,RULES[side]['window'])
                if blocks(mode,side,state):
                    # Cancel this accepted candidate before it enters the actual lifecycle.
                    # The independent canonical setup engine continues normally.
                    if self.owner!=side or self.active is None:raise AssertionError('FILTER_OWNER_MISMATCH')
                    self.owner='NONE';self.active=None
                    self.pending.pop(side,None)
                    for check in checks:
                        if check['direction']==side and check['status']=='ENTRY':
                            check['status']='FILTER_REJECTED';check['reasons'].append('FLAT_WMA_ENTRY_FILTER')
                            check['flat_wma_filter']=state
                    rejections.append(dict(direction=side,decision_time=at,signal_time=event.details['wma_gap']['signal_available_at'],entry_candidate_price=event.price,**state))
                else:kept.append(event)
            return kept,checks
    return Gate

def replay_primed(day,raw,seed,last_warm,mode='BASELINE',lookup=None):
    rejected=[]
    factory=ORIGINAL_GATE if mode=='BASELINE' else gate_factory(mode,lookup or [],rejected)
    # Seed already contains every prior session except last_warm. The original
    # replay warms that last real session, then performs its usual daily reset.
    with patch.object(engine,'ExitFirstCanonical',lambda:copy.deepcopy(seed)),patch.object(engine,'WmaGapGate',factory):
        result=engine.replay(day,raw,[last_warm])
    result['research_mode']=mode;result['filter_rules']=RULES;result['filter_rejections']=rejected
    result['warning']='Isolated full lifecycle research; thresholds selected using previously examined development data. Nifty points exclude option fills and costs.'
    return result

def signature(prefix,mode):
    return hashlib.sha256(json.dumps(dict(input_prefix=prefix,mode=mode,rules=engine.RULES,filters=RULES,engine=hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),research=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),sort_keys=True).encode()).hexdigest()
def cached(path,fingerprint,calculate):
    if path.is_file():
        x=json.loads(path.read_text())
        if x.get('full_replay_signature')==fingerprint:return x
    x=calculate();x['full_replay_signature']=fingerprint
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(x));temp.replace(path);return x

def run(a):
    end=date.fromisoformat(a.end_date);begin=start_date(end,3);lastmonth=start_date(end,1);idx=engine.cache_index(a.cache_root or list(engine.CACHE_ROOTS));out=a.output_root;out.mkdir(parents=True,exist_ok=True)
    if engine.RULES.get('setup_interval_minutes')!=5:raise ValueError('UPDATED_FIVE_MINUTE_V2_REQUIRED')
    coordinator=ORIGINAL_FACTORY();seed_before_last=None;last_warm=None;results=[];coverage=[];hashes={};started=time.monotonic();prefix=hashlib.sha256();failed_history=False
    targets=[d for d in sorted(idx) if begin.isoformat()<=d<=end.isoformat()];count=0
    for d,p in sorted(idx.items()):
        if d>end.isoformat():break
        raw=json.loads(p.read_text()).get('candles') or [];sha=hashlib.sha256(p.read_bytes()).hexdigest();hashes[d]=sha;prefix.update((d+sha).encode())
        target=d>=begin.isoformat()
        if not raw:
            if target:coverage.append(dict(session_date=d,status='EMPTY_CACHE',issue='Not verified as exchange holiday'))
            continue
        if failed_history:
            if target:coverage.append(dict(session_date=d,status='WARMUP_HISTORY_INVALID',issue='Recover earlier incomplete cache before rerun'))
            continue
        if target:
            count+=1;print(f'[{count}/{len(targets)}] {d} · full lifecycle variants · elapsed {time.monotonic()-started:.1f}s',flush=True)
            if seed_before_last is None or last_warm is None:raise ValueError('WARMUP_REQUIRED')
            try:
                session=[]
                base=cached(out/'sessions'/f'{d}-BASELINE.json',signature(prefix.hexdigest(),'BASELINE'),lambda:replay_primed(d,raw,seed_before_last,last_warm))
                lookup=wma_lookup(base);session.append(base)
                for mode in MODES[1:]:session.append(cached(out/'sessions'/f'{d}-{mode}.json',signature(prefix.hexdigest(),mode),lambda mode=mode:replay_primed(d,raw,seed_before_last,last_warm,mode,lookup)))
                # Same market replay must remain numerically consistent.
                for x in session:
                    for t in x['trades']:
                        expected=(t['exit_price']-t['entry_price'])*(1 if t['direction']=='BULLISH' else -1)
                        if not math.isclose(expected,t['points'],abs_tol=1e-8):raise ValueError('TRADE_POINTS_MISMATCH')
                results.extend(session);coverage.append(dict(session_date=d,status='EVALUATED',issue=''))
                for x in session:print(f"  {x['research_mode']}: {len(x['trades'])} trades · net {sum(t['points'] for t in x['trades']):+.2f} · rejected confirmations {len(x['filter_rejections'])}",flush=True)
            except (ValueError,FileNotFoundError) as e:coverage.append(dict(session_date=d,status='FAILED',issue=str(e)));print('  FAILED:',e,flush=True)
            write(out/'coverage.csv',coverage)
        # Carry exact full-session indicator history forward once, never a filtered
        # ownership state. No need to warm beyond the final requested date.
        if d<end.isoformat():
            try:
                bb=engine.aggregate_exact_5m(engine.candles(raw),date.fromisoformat(d))
                seed_before_last=copy.deepcopy(coordinator)
                for bar in bb:coordinator.on_bar(bar)
                last_warm=(d,raw)
            except ValueError as e:
                coverage.append(dict(session_date=d,status='INCOMPLETE_WARMUP',issue=str(e)));failed_history=True;print('WARMUP INVALID:',d,e,flush=True)
    day=begin;present={r['session_date'] for r in coverage}
    while day<=end:
        if day.isoformat() not in present:coverage.append(dict(session_date=day.isoformat(),status='CACHE_MISSING',issue='Not assumed a holiday'))
        day+=timedelta(days=1)
    trades=[];rejects=[];daily=[]
    for x in results:
        d=x['session_date'];mode=x['research_mode'];baseline=next(y for y in results if y['session_date']==d and y['research_mode']=='BASELINE');base_entries={(t['direction'],t['entry_time']) for t in baseline['trades']}
        for t in x['trades']:trades.append(dict(t,session_date=d,mode=mode,entry_membership='BASELINE_ENTRY' if (t['direction'],t['entry_time']) in base_entries else 'NEW_ENTRY'))
        rejects.extend(dict(z,session_date=d,mode=mode) for z in x['filter_rejections'])
        for side in ('ALL','BULLISH','BEARISH'):daily.append(dict(session_date=d,mode=mode,direction=side,**metrics([t for t in x['trades'] if side=='ALL' or t['direction']==side])))
    summaries=[]
    for period,first,last in [('ONE_MONTH',lastmonth,end),('THREE_MONTHS',begin,end),('EARLIER_TWO_MONTHS',begin,lastmonth-timedelta(days=1))]:
        for side in ('ALL','BULLISH','BEARISH'):
            base=metrics([t for t in trades if t['mode']=='BASELINE' and first.isoformat()<=t['session_date']<=last.isoformat() and (side=='ALL' or t['direction']==side)])
            for mode in MODES:
                tt=[t for t in trades if t['mode']==mode and first.isoformat()<=t['session_date']<=last.isoformat() and (side=='ALL' or t['direction']==side)];mm=metrics(tt)
                cov=[r for r in coverage if first.isoformat()<=r['session_date']<=last.isoformat()]
                summaries.append(dict(period=period,start=first.isoformat(),end=last.isoformat(),mode=mode,direction=side,evaluated_sessions=sum(r['status']=='EVALUATED' for r in cov),failed_sessions=sum(r['status'] in ('FAILED','INCOMPLETE_WARMUP','WARMUP_HISTORY_INVALID') for r in cov),empty_cache_dates=sum(r['status']=='EMPTY_CACHE' for r in cov),missing_calendar_dates=sum(r['status']=='CACHE_MISSING' for r in cov),**mm,baseline_net=base['net'],net_delta=round(mm['net']-base['net'],2),new_entries=sum(t['entry_membership']=='NEW_ENTRY' for t in tt)))
    # CSV excludes nested gate evidence; complete records remain in cached JSON.
    write(out/'trades.csv',[{k:v for k,v in t.items() if not isinstance(v,(dict,list))} for t in trades]);write(out/'rejected-confirmations.csv',rejects);write(out/'daily.csv',daily);write(out/'summary.csv',summaries);write(out/'coverage.csv',coverage)
    (out/'report.json').write_text(json.dumps(dict(baseline_rules=engine.RULES,filter_rules=RULES,summary=summaries,coverage=coverage,input_sha256=hashes,execution_enabled=False,scope='Full V2 actual-position lifecycle rerun; confirmed flat-WMA entry candidates canceled; future signals continue under installed setup policy. No new thresholds fitted. No live changes.'),indent=2))
    print('\nPeriod | Mode | Trades | Net | Delta | Drawdown | New entries')
    for r in summaries:
        if r['direction']=='ALL':print(f"{r['period']} | {r['mode']} | {r['trades']} | {r['net']:+.2f} | {r['net_delta']:+.2f} | {r['max_drawdown_points']:.2f} | {r['new_entries']}")
    failures=[r for r in coverage if r['status'] in ('FAILED','INCOMPLETE_WARMUP','WARMUP_HISTORY_INVALID')]
    print('Coverage:',sum(r['status']=='EVALUATED' for r in coverage),'evaluated sessions;',len(failures),'failed/incomplete records. Missing/empty calendar dates are not verified holidays.')
    if failures:print('PARTIAL RESULTS: inspect coverage.csv before interpreting performance.')
    print('Output:',out,'; no broker, live strategy, arm or service changes',flush=True)

def self_test():
    from market_lab.hilega_milega_strategy_v1 import IndicatorSnapshot,StrategyEvent
    from market_lab.domain import IST
    at=datetime(2026,10,12,10,0,tzinfo=IST)
    lookup=[((at-timedelta(minutes=15-5*i)).isoformat(),40+.1*(i%2)) for i in range(5)]
    assert blocks('BULLISH_FILTER','BULLISH',state_at(lookup,at.isoformat(),3))
    assert not blocks('BULLISH_FILTER','BEARISH',state_at(lookup,at.isoformat(),5))
    assert state_at(lookup,lookup[0][0],3) is None
    future=lookup+[((at+timedelta(minutes=5)).isoformat(),99)];assert state_at(future,at.isoformat(),3)==state_at(lookup,at.isoformat(),3)
    rej=[];gate=gate_factory('BULLISH_FILTER',lookup,rej)();minute=at-timedelta(minutes=1)
    gate.previous=dict(minute=minute-timedelta(minutes=1),snapshot=IndicatorSnapshot(50,46,41),wma_change=1)
    gate.signal(StrategyEvent('ENTRY_PATH1_ROUTE_B_STRUCTURAL',at-timedelta(minutes=5),None,'IDLE','ARMED'),at-timedelta(minutes=5));gate.pending['BULLISH']['armed_at']=minute-timedelta(minutes=2)
    entries,checks=gate.evaluate(minute=minute,current=IndicatorSnapshot(51,47,41.1),reference=IndicatorSnapshot(40,40,40),price=100)
    assert not entries and gate.owner=='NONE' and gate.active is None and not gate.pending and rej
    assert checks[0]['status']=='FILTER_REJECTED'
    later=at+timedelta(minutes=5);minute=later-timedelta(minutes=1)
    gate.previous=dict(minute=minute-timedelta(minutes=1),snapshot=IndicatorSnapshot(32,36,39.1),wma_change=-.9)
    gate.signal(StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',later-timedelta(minutes=3),None,'IDLE','ARMED'),later-timedelta(minutes=3))
    gate.pending['BEARISH']['armed_at']=minute-timedelta(minutes=2)
    entries,checks=gate.evaluate(minute=minute,current=IndicatorSnapshot(30,35,39),reference=IndicatorSnapshot(40,40,40),price=99)
    assert len(entries)==1 and gate.owner=='BEARISH' # Rejected bullish entry cannot steal later ownership.
    assert engine.WmaGapGate is ORIGINAL_GATE
    def synthetic(day):
        start=datetime.fromisoformat(day+'T09:15:00+05:30');rows=[]
        for i in range(375):
            value=22000+60*math.sin(i/19)+20*math.sin(i/4)+i*.04
            rows.append(dict(timestamp=(start+timedelta(minutes=i)).isoformat(),open=value-1,high=value+2,low=value-2,close=value,volume=0))
        return rows
    warm=('2026-07-10',synthetic('2026-07-10'));raw=synthetic('2026-07-13')
    original=engine.replay('2026-07-13',raw,[warm])
    primed=replay_primed('2026-07-13',raw,ORIGINAL_FACTORY(),warm)
    assert original['trades']==primed['trades'] and original['checks']==primed['checks'] and original['setup_attempts']==primed['setup_attempts']
    print('PASS: causal windows, rejection releases ownership, later entry, and exact ordinary/primed replay parity')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--end-date',default='2026-10-12');p.add_argument('--cache-root',type=Path,action='append');p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-flat-wma-full-replay-v1'));p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test:self_test()
    else:run(a)
