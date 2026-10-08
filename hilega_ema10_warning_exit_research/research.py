"""Offline paired exit research; no broker, runtime strategy or audit writes."""
import argparse,csv,hashlib,json,math
from datetime import datetime,timedelta,time,timezone
from pathlib import Path
IST=timezone(timedelta(hours=5,minutes=30))

def stamp(v):return datetime.fromisoformat(v).astimezone(IST)
def gap_band(v):
    if v is None:return 'UNAVAILABLE'
    for lo,hi in ((0,2),(2,5),(5,10),(10,20)):
        if lo<=v<hi:return f'{lo}_TO_{hi}'
    return 'GE_20' if v>=20 else 'NON_POSITIVE'
def expansion_band(v):
    if v is None:return 'UNAVAILABLE'
    for lo,hi in ((0,.1),(.1,.25),(.25,.5),(.5,1),(1,2)):
        if lo<=v<hi:return f'{lo}_TO_{hi}'
    return 'GE_2' if v>=2 else 'NON_POSITIVE'

def load_bars(cache,days):
    bars={};minute_map={};ema=None;seed=[];hashes={}
    for path in sorted(cache.glob('*.json')):
        if path.stem>max(days):continue
        try:datetime.fromisoformat(path.stem)
        except ValueError:continue
        raw=json.loads(path.read_text());candles=raw.get('candles') or []
        if not candles:continue
        mins={}
        for c in candles:
            t=stamp(c['timestamp'])
            if t.date().isoformat()!=path.stem or not time(9,15)<=t.time()<=time(15,29):continue
            if t in mins:raise ValueError(f'Duplicate minute {t}')
            for k in ('open','high','low','close'):
                if not math.isfinite(float(c[k])):raise ValueError('Non-finite candle')
            mins[t]=c
        session=[];start=stamp(path.stem+'T09:15:00+05:30')
        for offset in range(0,375,5):
            label=start+timedelta(minutes=offset);xs=[mins.get(label+timedelta(minutes=i)) for i in range(5)]
            if not all(xs):
                if label.time()<time(14,55):raise ValueError(f'Incomplete strategy/warmup candle {label}')
                # A selected session only needs complete pre-cutoff bars and cutoff open.
                if path.stem not in days:raise ValueError(f'Incomplete warmup candle {label}')
                continue
            close=float(xs[-1]['close'])
            if ema is None:
                seed.append(close)
                if len(seed)==10:ema=sum(seed)/10
            else:ema+=(2/11)*(close-ema)
            session.append(dict(label=label,available=label+timedelta(minutes=5),open=float(xs[0]['open']),close=close,ema10=ema))
        if path.stem in days:
            cutoff=stamp(path.stem+'T14:55:00+05:30')
            if cutoff not in mins:raise ValueError(f'Missing cutoff open {path.stem}')
            bars[path.stem]=session;minute_map[path.stem]=mins
        hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    if set(days)-set(bars):raise ValueError(f'Missing cache dates {sorted(set(days)-set(bars))}')
    return bars,minute_map,hashes

def entry(row,policy):
    prefix='control'
    if policy=='EARLIER_ADJACENT_GAP':prefix='candidate'
    if policy=='BULLISH_EXPANSION_HYBRID' and row['direction']=='BULLISH':
        c=row.get('entry_check') or {};delta=c.get('gap_delta')
        if row.get('candidate_points') is not None and delta is not None and .25<=delta<.5:
            prefix='candidate'
            if row.get('control_points') is not None and row['control_entry_timestamp']<row['candidate_entry_timestamp']:prefix='control'
    if row.get(prefix+'_points') is None:return None
    return prefix,stamp(row[prefix+'_entry_timestamp']),float(row[prefix+'_entry_price'])

class InvalidEntryTiming(ValueError):
    def __init__(self, detail):
        self.detail=detail
        super().__init__(detail["reason"])

def exit_trade(row,bars,mins,entered):
    prefix,entry_time,price=entered;sign=1 if row['direction']=='BULLISH' else -1
    warning_label=stamp(row['exit_timestamp']);cutoff=stamp(row['session_date']+'T14:55:00+05:30')
    cutoff_price=float(mins[cutoff]['open']);is_cutoff='CUTOFF' in str(row.get('exit_event') or '')
    warning_bar=next((b for b in bars if b['label']==warning_label),None)
    if is_cutoff:
        warning_time=cutoff
        if not math.isclose(float(row['exit_price']),cutoff_price,abs_tol=1e-6):raise ValueError(f'Cutoff price mismatch {row["trade_id"]}')
    else:
        if warning_bar is None:raise ValueError(f'Missing warning candle {row["trade_id"]}')
        if not math.isclose(float(row['exit_price']),warning_bar['close'],abs_tol=1e-6):raise ValueError(f'Warning close parity mismatch {row["trade_id"]}')
        warning_time=warning_bar['available']
    reason = ('ENTRY_AT_OR_AFTER_SESSION_CUTOFF' if entry_time>=cutoff else
              'ENTRY_AFTER_CANONICAL_WARNING' if entry_time>warning_time else None)
    if reason:
        raise InvalidEntryTiming(dict(reason=reason,entry_path=prefix,
            entry_timestamp=entry_time.isoformat(),entry_price=price,
            warning_candle_label=warning_label.isoformat(),warning_decision_time=warning_time.isoformat(),
            cutoff_timestamp=cutoff.isoformat(),source_points=float(row[prefix+'_points'])))
    chosen=None;audit=[]
    if not is_cutoff:
        for b in bars:
            if b['available']<warning_time or b['available']>=cutoff:continue
            if b['ema10'] is None:raise ValueError('Insufficient EMA10 warmup')
            passes=b['close']<b['ema10'] if sign==1 else b['close']>b['ema10']
            audit.append(dict(candle_label=b['label'].isoformat(),decision_time=b['available'].isoformat(),close=b['close'],ema10=b['ema10'],exit_pass=passes))
            if passes:chosen=b;break
    exit_time=chosen['available'] if chosen else cutoff;exit_price=chosen['close'] if chosen else cutoff_price
    points=sign*(exit_price-price);current=sign*(float(row['exit_price'])-price)
    expected=float(row[prefix+'_points'])
    if not math.isclose(current,expected,abs_tol=1e-6):raise ValueError('Current points do not reconcile')
    def excursion(end):
        xs=[c for t,c in mins.items() if entry_time<=t<end]
        favorable=max([0]+[sign*((float(c['high']) if sign==1 else float(c['low']))-price) for c in xs])
        adverse=min([0]+[sign*((float(c['low']) if sign==1 else float(c['high']))-price) for c in xs])
        return favorable,adverse
    mfe,mae=excursion(exit_time);old_mfe,_=excursion(warning_time)
    c=row.get('entry_check') if prefix=='candidate' else None
    return dict(entry_path=prefix,entry_timestamp=entry_time.isoformat(),entry_price=price,
        warning_candle_label=warning_label.isoformat(),warning_decision_time=warning_time.isoformat(),warning_price=float(row['exit_price']),warning_event=row.get('exit_event'),
        current_points=current,ema10_exit_timestamp=exit_time.isoformat(),ema10_exit_price=exit_price,ema10_points=points,delta_points=points-current,
        ema10_exit_reason='WARNING_AND_EMA10_CONFIRMED' if chosen else 'SESSION_CUTOFF_14_55_OPEN',
        hold_after_warning_minutes=(exit_time-warning_time).total_seconds()/60,
        current_mfe=old_mfe,current_giveback=old_mfe-current,ema10_mfe=mfe,ema10_mae=mae,ema10_giveback=mfe-points,
        current_gap=c.get('current_gap') if c else None,gap_delta=c.get('gap_delta') if c else None,
        gap_source='ACTUAL_EARLIER_ENTRY' if c else 'UNAVAILABLE_FOR_WAITING_ENTRY',audit=audit)

def metrics(rows,field):
    values=[r[field] for r in rows];g=sum(v for v in values if v>0);loss=-sum(v for v in values if v<0)
    equity=peak=drawdown=0
    sort_field='ema10_exit_timestamp' if field=='ema10_points' else 'warning_decision_time'
    for r in sorted(rows,key=lambda r:(r[sort_field],r['trade_id'])):
        equity+=r[field];peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
    return dict(max_drawdown=round(drawdown,2),entries=len(values),winners=sum(v>0 for v in values),losers=sum(v<0 for v in values),gains=round(g,2),losses=round(loss,2),net=round(g-loss,2),gain_loss_ratio=g/loss if loss else None)

def analyze(report,bars,minutes):
    details=[];excluded=[];dates=sorted({r['session_date'] for r in report['trades']})
    for row in report['trades']:
        for policy in ('WAITING_ENTRY','EARLIER_ADJACENT_GAP','BULLISH_EXPANSION_HYBRID'):
            entered=entry(row,policy)
            if entered is None:continue
            identity=dict(trade_id=row['trade_id'],session_date=row['session_date'],direction=row['direction'],entry_policy=policy)
            try:
                evaluated=exit_trade(row,bars[row['session_date']],minutes[row['session_date']],entered)
            except InvalidEntryTiming as exc:
                excluded.append(dict(**identity,**exc.detail))
                continue
            details.append(dict(**identity,**evaluated))
    # Extended exits can overlap later fixed entries; this paired study never claims portfolio feasibility.
    for policy in ('WAITING_ENTRY','EARLIER_ADJACENT_GAP','BULLISH_EXPANSION_HYBRID'):
        selected=sorted([r for r in details if r['entry_policy']==policy],key=lambda r:r['entry_timestamp'])
        latest=None
        for r in selected:
            r['overlaps_previous_extended_trade']=latest is not None and r['entry_timestamp']<latest
            latest=max(latest or r['ema10_exit_timestamp'],r['ema10_exit_timestamp'])
    cohorts=[('ALL_AVAILABLE_DEVELOPMENT',set(dates))]
    if len(dates)==490:
        cohorts += [(f'DEVELOPMENT_BLOCK_{i+1}',set(dates[i*160:(i+1)*160])) for i in range(3)]
        cohorts += [('PREVIOUSLY_OBSERVED_10',set(dates[480:]))]
    summaries=[];bands=[]
    for cohort,days in cohorts:
        for direction in ('ALL','BULLISH','BEARISH'):
            for policy in ('WAITING_ENTRY','EARLIER_ADJACENT_GAP','BULLISH_EXPANSION_HYBRID'):
                rs=[r for r in details if r['session_date'] in days and r['entry_policy']==policy and (direction=='ALL' or r['direction']==direction)]
                invalid=[r for r in excluded if r['session_date'] in days and r['entry_policy']==policy and (direction=='ALL' or r['direction']==direction)]
                summaries.append(dict(excluded_timing_entries=len(invalid),excluded_source_points=round(sum(r['source_points'] for r in invalid),2),cohort=cohort,direction=direction,entry_policy=policy,current=metrics(rs,'current_points'),ema10=metrics(rs,'ema10_points'),
                    delta_points=round(sum(r['delta_points'] for r in rs),2),improved=sum(r['delta_points']>0 for r in rs),worsened=sum(r['delta_points']<0 for r in rs),
                    winner_to_loser=sum(r['current_points']>0 and r['ema10_points']<0 for r in rs),loser_to_winner=sum(r['current_points']<0 and r['ema10_points']>0 for r in rs),
                    overlapping_extended_entries=sum(r.get('overlaps_previous_extended_trade',False) for r in rs),
                    current_giveback=round(sum(r['current_giveback'] for r in rs),2),ema10_giveback=round(sum(r['ema10_giveback'] for r in rs),2)))
                for dimension,fn in (('current_gap',gap_band),('gap_delta',expansion_band)):
                    for label in sorted({fn(r[dimension]) for r in rs}):
                        subset=[r for r in rs if fn(r[dimension])==label]
                        bands.append(dict(cohort=cohort,direction=direction,entry_policy=policy,dimension=dimension,band=label,current=metrics(subset,'current_points'),ema10=metrics(subset,'ema10_points')))
    return dict(model='HILEGA_CURRENT_WARNING_EMA10_EXIT_V1',sessions=len(dates),excluded_entries=excluded,excluded_entry_count=len(excluded),summary=summaries,gap_bands=bands,trades=details,execution_enabled=False,
        warning='Entries after the canonical warning or at/after session cutoff are excluded from BOTH paired exit metrics and listed separately; totals describe the eligible subset, not the full source strategy. Paired trade research, not full sequential portfolio replay: extended exits may overlap later original entries. Current exit warning is latched; EMA10 before warning is ignored, equality does not confirm, same warning candle may confirm. Cutoff takes precedence at 14:55 open. EMA10 is SMA-seeded from first 10 five-minute PRICE closes and carries across sessions. Current canonical exit labels are candle OPEN labels; structural warnings become available five minutes later. Entry price/timestamps retained from source research. Minute high/low excursions exclude exit decision minute. Waiting-entry gap is not inferred from a different earlier timestamp. No fee or option fill model; no production changes.')

def self_test():
    day='2026-01-01';t=lambda hh:stamp(day+'T'+hh+':00+05:30')
    bars=[dict(label=t('10:00'),available=t('10:05'),close=105,ema10=104),dict(label=t('10:05'),available=t('10:10'),close=103,ema10=104)]
    mins={t('10:00'):dict(open=104,high=106,low=104,close=105),t('10:05'):dict(open=105,high=105,low=103,close=103),t('14:55'):dict(open=102,high=999,low=0,close=999)}
    row=dict(trade_id='t',session_date=day,direction='BULLISH',exit_timestamp=t('10:00').isoformat(),exit_price=105,exit_event='STRUCTURAL_EXIT',candidate_points=5)
    result=exit_trade(row,bars,mins,('candidate',t('10:00'),100))
    assert result['ema10_points']==3 and result['hold_after_warning_minutes']==5
    bars[0]['ema10']=106
    assert exit_trade(row,bars,mins,('candidate',t('10:00'),100))['hold_after_warning_minutes']==0
    bars[0]['ema10']=105;bars[1]['ema10']=103
    assert exit_trade(row,bars,mins,('candidate',t('10:00'),100))['ema10_exit_reason']=='SESSION_CUTOFF_14_55_OPEN'
    row.update(direction='BEARISH',candidate_points=-5);bars[0]['ema10']=104
    assert exit_trade(row,bars,mins,('candidate',t('10:00'),100))['hold_after_warning_minutes']==0
    assert gap_band(10)=='10_TO_20' and expansion_band(.25)=='0.25_TO_0.5'
    row.update(direction='BULLISH',candidate_points=5)
    report={'trades':[dict(row,candidate_entry_timestamp=t('10:06').isoformat(),candidate_entry_price=100,control_points=None)]}
    analyzed=analyze(report,{day:bars},{day:mins})
    assert not analyzed['trades'] and analyzed['excluded_entry_count']==1
    assert analyzed['excluded_entries'][0]['reason']=='ENTRY_AFTER_CANONICAL_WARNING'
    row['candidate_points']=5
    assert exit_trade(row,bars,mins,('candidate',t('10:05'),100))['entry_timestamp']==t('10:05').isoformat()
    try:exit_trade(row,bars,mins,('candidate',t('14:55'),100))
    except InvalidEntryTiming as exc:assert exc.detail['reason']=='ENTRY_AT_OR_AFTER_SESSION_CUTOFF'
    else:raise AssertionError('Cutoff entry must be excluded')
    print('PASS: timing exclusions, zero eligible entries, warning latch, bullish/bearish signs, same-candle exit, equality wait, cutoff and bands')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--report',type=Path,default=Path('data/historical-evidence/hilega-adjacent-gap-reconciled-490-v1/report.json'));p.add_argument('--cache-root',type=Path,default=Path('data/historical-evidence/hilega-milega-underlying-cache-v1'));p.add_argument('--expected-sessions',type=int,default=490);p.add_argument('--output-root',type=Path,default=Path('data/historical-evidence/hilega-warning-ema10-exit-v1'));a=p.parse_args()
    if a.self_test:self_test();raise SystemExit(0)
    if a.output_root.exists():raise SystemExit('STOP: output exists; choose another output root')
    report=json.loads(a.report.read_text());days={r['session_date'] for r in report['trades']}
    if len(days)!=a.expected_sessions:raise ValueError('Unexpected session count')
    bars,mins,hashes=load_bars(a.cache_root,days);result=analyze(report,bars,mins);result['source_sha256']=hashlib.sha256(a.report.read_bytes()).hexdigest();result['cache_sha256']=hashes
    a.output_root.mkdir(parents=True);(a.output_root/'report.json').write_text(json.dumps(result,indent=2))
    flat=[{k:v for k,v in r.items() if k!='audit'} for r in result['trades']]
    with (a.output_root/'trade-exits.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(flat[0]) if flat else ['trade_id','session_date','entry_policy']);w.writeheader();w.writerows(flat)
    excluded=result['excluded_entries']
    with (a.output_root/'excluded-entries.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(excluded[0]) if excluded else ['trade_id','session_date','entry_policy','reason']);w.writeheader();w.writerows(excluded)
    print('Excluded timing entries (policy-specific):',len(excluded))
    for name in ('summary','gap_bands'):
        flattened=[]
        for r in result[name]:
            item={k:v for k,v in r.items() if k not in ('current','ema10')}
            for method in ('current','ema10'):
                item.update({method+'_'+k:v for k,v in r[method].items()})
            flattened.append(item)
        with (a.output_root/(name+'.csv')).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(flattened[0]) if flattened else ['cohort','direction','entry_policy']);w.writeheader();w.writerows(flattened)
    for r in result['summary']:
        if r['direction']!='ALL':print(json.dumps(r))
    print('Output:',a.output_root/'report.json');print('No strategy, audit, broker or source-cache changes.')
