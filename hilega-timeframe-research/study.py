"""Offline 1m/3m/5m comparison, using frozen source hashes and recorded 5m parity."""
import argparse
from datetime import datetime,date,time,timedelta
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import zipfile
import core

HERE=Path(__file__).resolve().parent
MODULES=tuple(json.loads((HERE/'source-hashes.json').read_text()))
PACKAGE_VERSION='1.1.0-session-filter'
EXPECTED_VERSION='bullish-gap2-full-wma2-2.0.0-wma40-reversal'
CACHE_ROOTS=(Path('data/historical-evidence/hilega-milega-underlying-cache-v1'),
    Path('data/recovery/october-2026/replay-input/replay-warmup'),
    Path('data/recovery/october-2026/nifty-cache'))


def verify_sources():
    import market_lab
    installed=Path(market_lab.__file__).parent
    expected=json.loads((HERE/'source-hashes.json').read_text())
    for name,digest in expected.items():
        if hashlib.sha256((installed/(name+'.py')).read_bytes()).hexdigest()!=digest:
            raise ValueError('SOURCE_CHANGED:'+name+'; supply current file, do not bypass')
    if core.policy5.VERSION!=EXPECTED_VERSION:raise ValueError('STRATEGY_VERSION_CHANGED')
    return installed,expected


def convert(name, source, interval):
    if interval not in (1,3):raise ValueError('RESEARCH_INTERVAL_MUST_BE_1_OR_3')
    # The installed boundary policy uses a one-minute sentinel before each
    # decision timestamp. Keep those 1m offsets; change bar spacing only.
    source=source.replace('timedelta(minutes=5)',f'timedelta(minutes={interval})')
    if name=='hilega_combined_policy_v1':
        replacements={
            'at.minute%5':f'at.minute%{interval}',
            'at.minute//5*5':f'at.minute//{interval}*{interval}',
            '.total_seconds()%300':f'.total_seconds()%{60*interval}',
            'confirmation_interval_minutes=5':f'confirmation_interval_minutes={interval}',
        }
        for a,b in replacements.items():source=source.replace(a,b)
        for forbidden in ('timedelta(minutes=5)','at.minute%5','at.minute//5','%300'):
            if forbidden in source:raise ValueError('UNCONVERTED_CADENCE:'+forbidden)
    if name in ('hilega_milega_strategy_v1','hilega_milega_bearish_strategy_v1'):
        for old,new in [('09:20',f'09:{15+interval:02d}'),('09:25',f'09:{15+2*interval:02d}')]:
            source=source.replace('t == "'+old+'"','t == "'+new+'"')
    if name=='hilega_opening_reference_v1':
        source=source.replace('time(9, 20)',f'time(9, {15+interval})')
    if name=='hilega_v2_alignment_replay_v1':
        # Only its canonical coordinator/gate/dual_exit helpers are used.
        # Remove the unrelated old minute-replay CLI and cache writer entirely.
        source=source[:source.index('\ndef replay(')]
        source=source.replace('time(14,50)',f'time(14,{55-interval})')
    word='ONE' if interval==1 else 'THREE'
    source=source.replace('FIVE_MINUTE',word+'_MINUTE').replace('5M',str(interval)+'M').replace('5m',str(interval)+'m')
    # Keep the installed helper's name for its unused import, never call it.
    source=source.replace(f'aggregate_exact_{interval}m','aggregate_exact_5m')
    return source


def isolated(root,installed,interval):
    name=f'hilega_timeframe_research_{interval}m'
    if name in sys.modules:raise ValueError('RESEARCH_NAMESPACE_ALREADY_LOADED')
    root.mkdir()
    for module in MODULES:
        source=convert(module,(installed/(module+'.py')).read_text(),interval)
        (root/(module+'.py')).write_text(source)
    namespace=types.ModuleType(name);namespace.__path__=[str(root),str(installed)]
    sys.modules[name]=namespace
    try:
        return (importlib.import_module(name+'.hilega_combined_policy_v1'),
                importlib.import_module(name+'.hilega_v2_alignment_replay_v1'))
    except Exception:
        cleanup(interval);raise


def cleanup(interval):
    prefix=f'hilega_timeframe_research_{interval}m'
    for name in list(sys.modules):
        if name==prefix or name.startswith(prefix+'.'):del sys.modules[name]


def regular_warmup(rows,day):
    # Providers can retain post-close prints. Validate their schema first, then
    # exclude them only from historical warmup, matching regular-bar aggregation.
    core.validate_rows(rows,day,allow_outside=True)
    regular=[];excluded=[]
    for row in rows:
        at=datetime.fromisoformat(row['timestamp']).astimezone(core.IST)
        if time(9,15)<=at.time()<time(15,30):regular.append(row)
        else:excluded.append(row['timestamp'])
    return regular,excluded


def load_inputs(archive,session,roots):
    data=json.loads(session.read_text());day=data['session_date']
    if data.get('underlying')!='NSE_INDEX|Nifty 50':raise ValueError('UNEXPECTED_UNDERLYING')
    core.validate_rows(data['candles'],day)
    if len(data['candles'])!=375:raise ValueError('TARGET_REQUIRES_375_REGULAR_MINUTES')
    # Exact coverage check, validation only, before running a policy.
    core.aggregate(data['candles'],day,1,datetime.combine(date.fromisoformat(day),time(15,30),core.IST))
    warm,records=core.read_inputs(archive)
    by_day={};provenance=[]
    for d,rows in warm:
        if d>=day:continue
        if d in by_day:raise ValueError('DUPLICATE_WARMUP_DATE:'+d)
        by_day[d]=rows
    latest=max(by_day) if by_day else ''
    # The carry-forward archive is immutable. Add newer saved sessions only.
    # Root precedence matches the installed historical replay cache index.
    index={}
    for root in roots:
        for path in sorted(root.glob('????-??-??.json')):
            date.fromisoformat(path.stem)
            if latest<path.stem<day:index[path.stem]=path
    for d,path in sorted(index.items()):
        item=json.loads(path.read_text())
        if item.get('session_date') not in (None,d):raise ValueError('CACHE_DATE_MISMATCH:'+d)
        if item.get('underlying') not in (None,'NSE_INDEX|Nifty 50'):raise ValueError('CACHE_UNDERLYING_MISMATCH:'+d)
        if not item.get('candles'):continue
        by_day[d]=item['candles']
        provenance.append(dict(session_date=d,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    for d,rows in sorted(by_day.items()):
        regular,excluded=regular_warmup(rows,d)
        if excluded:
            provenance.append(dict(session_date=d,action='EXCLUDE_OUTSIDE_REGULAR_WARMUP',count=len(excluded),timestamps=excluded))
        by_day[d]=regular
        core.aggregate(regular,d,1,datetime.combine(date.fromisoformat(d),time(15,30),core.IST))
    # Known missing sessions in the supplied Oct26 export, not a holiday calendar.
    if day=='2026-10-26':
        missing=[d for d in ('2026-10-22','2026-10-23') if d not in by_day]
        if missing:raise ValueError('MISSING_RECENT_WARMUP:'+','.join(missing)+'; supply --cache-root containing full session JSON files')
    records=[r for r in records if str((r.get('payload') or {}).get('decision_timestamp') or r.get('event_time','')).startswith(day)]
    return data,sorted(by_day.items()),records,provenance


def alerts(result,stage):
    rows=[];seen=set()
    for a in result['audit']:
        if stage=='ENTRY':events=a['entries']
        elif stage=='SETUP':events=a['setups']
        else:raise ValueError('UNKNOWN_ALERT_STAGE')
        for e in events:
            key=(a['time'],e['direction'])
            if key in seen:continue
            seen.add(key)
            rows.append(dict(time=a['time'],direction=e['direction'],price=a['frame']['close'],stage=stage))
    return sorted(rows,key=lambda r:(r['time'],r['direction']))


def agreement(one,three):
    """Onset of simultaneous active owners, using only states available by now."""
    by_time={};out=[];state={1:'NONE',3:'NONE'};prior='NONE'
    for interval,result in ((1,one),(3,three)):
        for a in result['audit']:by_time.setdefault(a['time'],{})[interval]=a
    for stamp,updates in sorted(by_time.items()):
        for interval,a in updates.items():state[interval]=a['owner']
        same=state[1] if state[1]==state[3] else 'NONE'
        if same!='NONE' and same!=prior:
            # At least one completed frame updates at this timestamp.
            price=next(iter(updates.values()))['frame']['close']
            out.append(dict(time=stamp,direction=same,price=price,stage='ACTIVE_AGREEMENT'))
        prior=same
    return out


def match_alerts(stream,five,raw):
    """Descriptive matching, not proof two timeframes identified the same setup.
    Primary window is the next 5m boundary; opposite alert/exit invalidates.
    An alert exactly at a 5m boundary is simultaneous evidence, not an early alert.
    """
    target=[]
    for a in five['audit']:target.extend(a['entries'])
    target=sorted(target,key=lambda r:r['time']);used=set();out=[]
    cutoff=datetime.combine(datetime.fromisoformat(five['audit'][0]['time']).date(),time(14,55),core.IST)
    for n,alert in enumerate(stream):
        at=datetime.fromisoformat(alert['time']);seconds=at.hour*3600+at.minute*60
        boundary=at.replace(second=0,microsecond=0)+timedelta(minutes=5-at.minute%5)
        on_boundary=seconds%300==0
        expiry=min(boundary,cutoff)
        # Entries/agreement include an explicit valid_until on exit/change.
        invalid=datetime.fromisoformat(alert['valid_until']) if alert.get('valid_until') else cutoff
        opposite=next((datetime.fromisoformat(r['time']) for r in stream[n+1:] if r['direction']!=alert['direction']),cutoff)
        invalid=min(invalid,opposite)
        candidates=[(i,e) for i,e in enumerate(target) if i not in used and at<datetime.fromisoformat(e['time'])<=expiry]
        match=next(((i,e) for i,e in candidates if e['direction']==alert['direction'] and datetime.fromisoformat(e['time'])<invalid),None)
        row=dict(alert,next_5m_boundary=expiry.isoformat(),off_5m_boundary=not on_boundary,matched_5m_entry=None,lead_minutes=None,price_advantage_points=None)
        if on_boundary:
            row['classification']='ON_5M_BOUNDARY_EXCLUDED_FROM_EARLY_RATE'
        elif match:
            i,e=match;used.add(i);row.update(classification='CONFIRMED_NEXT_5M_BOUNDARY',matched_5m_entry=e['time'],lead_minutes=(datetime.fromisoformat(e['time'])-at).total_seconds()/60,
                price_advantage_points=(e['price']-alert['price'])*(1 if alert['direction']=='BULLISH' else -1))
        elif invalid<=expiry:row['classification']='INVALIDATED_BEFORE_5M_CONFIRMATION'
        elif any(e['direction']!=alert['direction'] for _,e in candidates):row['classification']='OPPOSITE_5M_ENTRY'
        else:row['classification']='NO_UNUSED_5M_ENTRY_BY_NEXT_BOUNDARY'
        out.append(row)
    return out


def with_lifetime(stream,result):
    for row in stream:
        related=next((t for t in result['trades'] if t['direction']==row['direction'] and
            ((row['stage']=='ENTRY' and t['entry_time']==row['time']) or
             (row['stage']=='SETUP' and t['setup']==row['time']))),None)
        if related is not None:
            row['valid_until']=related['exit_time']
        elif row['stage']=='SETUP':
            # A raw setup can be rejected or superseded on its own boundary.
            # Do not keep it alive after the policy has discarded its identity.
            for a in result['audit']:
                if a['time']>=row['time'] and a['pending'].get(row['direction'])!=row['time']:
                    row['valid_until']=a['time'];break
        else:raise ValueError('ENTRY_TRADE_NOT_FOUND')
    return stream


def agreement_lifetimes(stream,one,three):
    for row in stream:
        ends=[]
        for result in (one,three):
            for a in result['audit']:
                if a['time']>row['time'] and a['owner']!=row['direction']:
                    ends.append(a['time']);break
        if ends:row['valid_until']=min(ends)
    return stream


def stats(result):
    trades=result['trades'];net=peak=dd=0
    for t in trades:
        net+=t['points'];peak=max(peak,net);dd=max(dd,peak-net)
    return dict(trades=len(trades),winners=sum(t['points']>0 for t in trades),losers=sum(t['points']<0 for t in trades),
        breakeven=sum(t['points']==0 for t in trades),net_points=net,closed_trade_drawdown=dd)


def report(output,day,results,matches,proof,manifest):
    lines=['# 1m / 3m / 5m research — '+day,'','Recorded 5m parity: PASS.',
        'Same RSI9/EMA3/WMA21/priceEMA10 periods and numeric thresholds; elapsed-time lookbacks differ. Full strategy timing changes with candle interval.',
        'Gross NIFTY completed-candle close marks; cutoff uses exact 14:55 open. No option fills, fees, slippage or execution latency. Closed-trade drawdown excludes intratrade excursions.',
        'Same current WMA40/reversal policy; only complete bars from 09:15. The final completed 3m bar before cutoff ends 14:54; no partial bar at 14:55.',
        'No live changes. This one-session study does not establish general predictive performance.','',
        '| Policy | Trades | Winners | Losers | Net points | Closed-trade drawdown |','|---|---:|---:|---:|---:|---:|']
    for name,result in results.items():
        s=stats(result);lines.append(f"| {name} | {s['trades']} | {s['winners']} | {s['losers']} | {s['net_points']:+.2f} | {s['closed_trade_drawdown']:.2f} |")
    lines+=['','## Early-direction evidence','',
        'SETUP is an unconfirmed pending candidate, not an entry. ENTRY is fully confirmed on that timeframe. AGREEMENT starts only when both independent lower-timeframe strategies have the same active direction.',
        'Each stream is matched independently. An off-boundary alert must receive a same-direction 5m entry by the next 5m boundary while still valid. Opposite alerts or a lower-timeframe trade exit invalidate it; equality at exit is excluded. Each 5m entry can match at most one alert per stream. Earliest valid alert wins.',
        'On-boundary alerts are excluded from early rates. Unmatched alerts are not necessarily losing trades. These are temporal direction matches, not identical setup identities. Future 5m entries label alerts after generation; they never generate an alert.',
        '', '| Stream | Off-boundary alerts | Matched | Rate | Mean lead (min) | Unmatched 5m entries |','|---|---:|---:|---:|---:|---:|']
    baseline_entries=sum(len(a['entries']) for a in results['DEPLOYED_5M']['audit'])
    for name,rows in matches.items():
        early=[r for r in rows if r['off_5m_boundary']];hit=[r for r in early if r['matched_5m_entry']]
        rate=f'{100*len(hit)/len(early):.1f}%' if early else 'N/A'
        lead=f"{sum(r['lead_minutes'] for r in hit)/len(hit):.2f}" if hit else 'N/A'
        lines.append(f'| {name} | {len(early)} | {len(hit)} | {rate} | {lead} | {baseline_entries-len(hit)} |')
    detail=['# Alert-by-alert comparison','', '| Stream | Stage | Direction | Alert IST | Next boundary | Result | 5m entry | Lead min | Price advantage points |','|---|---|---|---|---|---|---|---:|---:|']
    for name,rows in matches.items():
        for a in rows:
            detail.append('| '+' | '.join([name,a['stage'],a['direction'],a['time'][11:16],a['next_5m_boundary'][11:16],a['classification'],(a['matched_5m_entry'] or '')[11:16],str(a['lead_minutes'] if a['lead_minutes'] is not None else '—'),f"{a['price_advantage_points']:+.2f}" if a['price_advantage_points'] is not None else '—'])+' |')
    trades=['# Every executed hypothetical trade','', '| Policy | Direction | Setup IST | Qualified IST | Entry IST | Exit IST | Entry mark | Exit mark | Points | Exit reason |','|---|---|---|---|---|---|---:|---:|---:|---|']
    hm=lambda v:v[11:16] if v else '—'
    audit=['# All completed-boundary decisions','']
    for name,r in results.items():
        for t in r['trades']:
            trades.append(f"| {name} | {t['direction']} | {hm(t.get('setup'))} | {hm(t.get('qualified'))} | {hm(t['entry_time'])} | {hm(t['exit_time'])} | {t['entry_price']:.2f} | {t['exit_price']:.2f} | {t['points']:+.2f} | {t['exit_reason']} |")
        audit+=['## '+name,'','```json',json.dumps(r['audit'],indent=2),'```','']
    for name,content in [('comparison.md',lines),('early-direction.md',detail),('trades.md',trades),('decision-audit.md',audit)]:
        (output/name).write_text('\n'.join(content)+'\n')
    (output/'report.json').write_text(json.dumps(dict(session_date=day,baseline_parity=proof,manifest=manifest,policies=results,early_direction=matches,statistics={k:stats(v) for k,v in results.items()},orders_sent=False),indent=2))
    with zipfile.ZipFile(output/'results.zip','x',zipfile.ZIP_DEFLATED) as z:
        for name in ('comparison.md','early-direction.md','trades.md','decision-audit.md','report.json','parity.json','manifest.json'):z.write(output/name,name)
    print('\n'.join(lines),flush=True)
    print('UPLOAD:',output/'results.zip',flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-zip',type=Path,required=True)
    ap.add_argument('--session-input',type=Path,required=True)
    ap.add_argument('--cache-root',type=Path,action='append',help='Additional local cache directory; later roots override earlier ones')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists():raise ValueError('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    args.output.mkdir(parents=True)
    try:
        installed,hashes=verify_sources()
        data,warm,records,added=load_inputs(args.input_zip,args.session_input,list(CACHE_ROOTS)+(args.cache_root or []))
        day=data['session_date'];until=datetime.combine(date.fromisoformat(day),time(14,55),core.IST)
        manifest=dict(package_version=PACKAGE_VERSION,session_date=day,source_sha256=hashes,source_version=EXPECTED_VERSION,
            input_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.input_zip,args.session_input)},
            warmup_sessions=len(warm),warmup_last=warm[-1][0],warmup_input_actions=added,
            research_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')},
            interval_anchor='09:15 IST',orders_sent=False)
        (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2))
        print('Running installed 5m control; warmup sessions:',len(warm),'last:',warm[-1][0],flush=True)
        five=core.run(core.policy5,core.legacy5,warm,data['candles'],day,5,until)
        proof=core.parity(five,records,until)
        (args.output/'parity.json').write_text(json.dumps(proof,indent=2))
        if proof['status']!='PASS':
            print(json.dumps(proof,indent=2),flush=True)
            raise ValueError('STOP_5M_RECORDED_PARITY_FAILED; no lower-timeframe comparison generated')
        print('5m parity PASS',flush=True)
        results={'DEPLOYED_5M':five}
        with tempfile.TemporaryDirectory(prefix='hilega-offline-timeframes-') as directory:
            for interval in (1,3):
                print(f'Running isolated {interval}m strategy and full prior-session warmup...',flush=True)
                try:
                    p,l=isolated(Path(directory)/str(interval),installed,interval)
                    results[f'RESEARCH_{interval}M']=core.run(p,l,warm,data['candles'],day,interval,until)
                finally:cleanup(interval)
        matches={}
        for interval in (1,3):
            r=results[f'RESEARCH_{interval}M']
            for stage in ('SETUP','ENTRY'):
                matches[f'{interval}m_{stage}']=match_alerts(with_lifetime(alerts(r,stage),r),five,data['candles'])
        common=agreement_lifetimes(agreement(results['RESEARCH_1M'],results['RESEARCH_3M']),results['RESEARCH_1M'],results['RESEARCH_3M'])
        matches['1m_3m_ACTIVE_AGREEMENT']=match_alerts(common,five,data['candles'])
        report(args.output,day,results,matches,proof,manifest)
    except Exception as e:
        (args.output/'failure.json').write_text(json.dumps(dict(status='BLOCKED',error=str(e),orders_sent=False),indent=2))
        print('BLOCKED:',str(e),flush=True);raise SystemExit(2)

if __name__=='__main__':main()
