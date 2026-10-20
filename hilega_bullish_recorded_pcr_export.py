"""Read-only export of recorded PCR/bias for actual combined bullish trades.

Reads saved research sessions and GETs the existing localhost PCR context API.
No orders, replay changes, API writes or historical data fetching.
"""
import argparse
from datetime import datetime,timedelta
import json
import math
from pathlib import Path
from urllib.parse import urlencode,urlparse
from urllib.request import urlopen

POLICY='BULLISH_GAP2_FULL_WMA2'

def timestamp(s):
    d=datetime.fromisoformat(s.replace('Z','+00:00'))
    if d.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    return d

def validate(data,at,max_age):
    if data.get('status')!='AVAILABLE':return data
    if timestamp(data['decision_time'])!=at:raise ValueError('DECISION_TIME_MISMATCH')
    age=(at-timestamp(data['available_at'])).total_seconds()
    if age<0 or age>max_age:raise ValueError('FUTURE_OR_STALE_OBSERVATION')
    if abs(age-float(data['age_seconds']))>.01:raise ValueError('AGE_MISMATCH')
    return data

def number(x,digits=4):
    return f'{x:.{digits}f}' if isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) else 'UNKNOWN'

def panel(data,mode):
    if data.get('status')!='AVAILABLE':return None
    matches=[p for p in data.get('panels',[]) if p.get('mode')==mode]
    return matches[0] if len(matches)==1 else None

def panel_text(data,mode):
    p=panel(data,mode)
    if p is None:return 'UNKNOWN: '+data.get('reason','PANEL_MISSING')
    return f"ATM {number(p.get('atm'),0)}; PCR {number(p.get('pcr'))}; {p.get('combined_bias','UNKNOWN')}"

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--research-root',type=Path,action='append')
    ap.add_argument('--start-date',default='2026-10-01')
    ap.add_argument('--end-date',default='2026-10-20')
    ap.add_argument('--date')
    ap.add_argument('--api',default='http://127.0.0.1:8123')
    ap.add_argument('--max-age',type=int,default=120)
    ap.add_argument('--horizon',type=int,choices=(300,900,1800),default=300)
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-bullish-recorded-pcr-october'))
    args=ap.parse_args()
    if urlparse(args.api).hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('LOCAL_READ_ONLY_API_REQUIRED')
    if not 1<=args.max_age<=300:raise ValueError('INVALID_MAX_AGE')
    roots=args.research_root or [Path('data/research/hilega-bearish-ema30-oct-through16'),Path('data/research/hilega-bearish-ema30-oct19')]
    trades=[];days=set();proof={}
    for root in roots:
        report=json.loads((root/'report.json').read_text())
        if report.get('status')!='COMPLETE':raise ValueError('COMPLETE_RESEARCH_REQUIRED:'+str(root))
        for day in report['session_dates']:
            if args.date and day!=args.date:continue
            if not args.date and not args.start_date<=day<=args.end_date:continue
            if day in days:raise ValueError('DUPLICATE_SESSION:'+day)
            variants=json.loads((root/'sessions'/(day+'.json')).read_text())
            value=variants[POLICY];days.add(day);proof[day]=report['provenance'][day]
            for t in value['trades']:
                if t['direction']!='BULLISH':continue
                events=[e for e in value.get('policy_events',[]) if e.get('event')=='FOLLOWUP_CANDLE_CHECK'
                    and e.get('direction')=='BULLISH' and e.get('passed') is True
                    and e.get('time')==t['entry_time'] and e.get('setup_available')==t['signal_time']]
                signals={e.get('signal_time') for e in events}
                if len(signals)!=1 or None in signals:raise ValueError('EXACT_QUALIFIED_SIGNAL_REQUIRED:'+day)
                signal=timestamp(next(iter(signals)));entry=timestamp(t['entry_time'])
                if signal>=entry:raise ValueError('SIGNAL_ENTRY_ORDER_INVALID')
                checkpoints=[];at=signal-timedelta(minutes=5)
                while at<=entry:
                    stage='PREVIOUS' if at<signal else 'SIGNAL' if at==signal else 'ENTRY' if at==entry else 'WAITING'
                    checkpoints.append(dict(stage=stage,at=at.isoformat()));at+=timedelta(minutes=5)
                if checkpoints[-1]['at']!=entry.isoformat():raise ValueError('ENTRY_NOT_ON_COMPLETED_5M')
                trades.append(dict(date=day,setup=t['signal_time'],signal=signal.isoformat(),entry=t['entry_time'],
                    exit=t['exit_time'],points=t['points'],checkpoints=checkpoints))
                audits={r.get('checkpoint'):r.get('completed_5m_indicators',{}) for r in value.get('audit',[]) if r.get('five_minute_changes')}
                trades[-1]['signal_indicators']=audits.get(signal.isoformat(),{})
                trades[-1]['entry_indicators']=audits.get(t['entry_time'],{})
    if not days:raise ValueError('NO_MATCHING_SESSIONS')
    args.output.mkdir(parents=True,exist_ok=True)
    cache={};requests=sorted({c['at'] for t in trades for c in t['checkpoints']})
    for i,at in enumerate(requests,1):
        query=urlencode(dict(at=at,horizon=args.horizon,max_age=args.max_age))
        try:
            with urlopen(args.api.rstrip('/')+'/api/live-shadow/hilega-pcr/context?'+query,timeout=30) as response:
                data=json.load(response)
            data=validate(data,timestamp(at),args.max_age)
        except Exception as exc:
            data=dict(status='UNKNOWN',decision_time=at,reason=type(exc).__name__+': '+str(exc))
        cache[at]=data
        print(f"[{i}/{len(requests)}] {at} {data.get('status')} {data.get('reason','')}",flush=True)
        # Checkpoint export preserves progress if interrupted, without changing the API.
        (args.output/'recorded-contexts.json').write_text(json.dumps(cache,indent=2))
    header=['| Date | Setup | Signal | Entry–exit | NIFTY points | RSI9: signal → entry | EMA3 of RSI: signal → entry | WMA21: signal → entry | Fixed PCR / bias: signal → entry | Moving PCR / bias: signal → entry | Evidence status |',
        '|---|---|---|---|---:|---|---|---|---|---|---|']
    winners=['# Winning bullish trades','']+header
    losers=['# Losing bullish trades','']+header
    stages=['# Recorded PCR and bias at every stage','',
        '| Date | Entry | Stage | Decision IST | Available at | Age seconds | Expiry | Fixed ATM / PCR / bias | Moving ATM / PCR / bias | Fixed CE / PE OI change % | Moving CE / PE OI change % | Status / reason |',
        '|---|---|---|---|---|---:|---|---|---|---|---|---|']
    unknown=0
    for t in sorted(trades,key=lambda t:t['entry']):
        signal,entry=cache[t['signal']],cache[t['entry']]
        complete=True
        for c in t['checkpoints']:
            d=cache[c['at']]
            valid=d.get('status')=='AVAILABLE' and all(panel(d,m) is not None and
                panel(d,m).get('pcr') is not None and panel(d,m).get('combined_bias') not in (None,'UNKNOWN','UNAVAILABLE')
                and panel(d,m).get('received')==panel(d,m).get('expected') for m in ('fixed','moving'))
            if not valid:complete=False;unknown+=1
            def oi(mode):
                p=panel(d,mode) or {};return number(p.get('ce_oi_change_pct'),2)+' / '+number(p.get('pe_oi_change_pct'),2)
            stages.append('| '+' | '.join([t['date'],t['entry'][11:16],c['stage'],c['at'][11:16],str(d.get('available_at','UNKNOWN')),
                number(d.get('age_seconds'),2),d.get('expiry','UNKNOWN'),panel_text(d,'fixed'),panel_text(d,'moving'),
                oi('fixed'),oi('moving'),('AVAILABLE' if valid else 'UNKNOWN: '+d.get('reason','INCOMPLETE_PANEL'))])+' |')
        expiries={cache[c['at']].get('expiry') for c in t['checkpoints'] if cache[c['at']].get('status')=='AVAILABLE'}
        status='ALL STAGES AVAILABLE' if complete else 'SOME STAGES UNKNOWN'
        if len(expiries)>1:status+='; EXPIRY CHANGED—DO NOT COMPARE AS SAME BASKET'
        row='| '+' | '.join([t['date'],t['setup'][11:16],t['signal'][11:16],t['entry'][11:16]+'–'+t['exit'][11:16],
            f"{t['points']:+.2f}"]+[number(t['signal_indicators'].get(k),2)+' → '+number(t['entry_indicators'].get(k),2) for k in ('rsi9','ema3','wma21')]+[panel_text(signal,'fixed')+' → '+panel_text(entry,'fixed'),
            panel_text(signal,'moving')+' → '+panel_text(entry,'moving'),status])+' |'
        (winners if t['points']>0 else losers).append(row)
    intro=('# Current combined: recorded bullish PCR context\n\n'
        'Observation only; no filters, strategy changes or orders. PCR is total PE OI / CE OI; combined bias is the existing '
        'positioning diagnostic, not a PCR threshold. Only causal fresh API evidence is accepted. '
        'Moving ATM basket changes must be distinguished from OI changes.\n\n'
        f'Sessions: {len(days)}; {min(days)} through {max(days)}. Bullish trades: {len(trades)}. '
        f'Requested through: {args.date or args.end_date}. Saved session dates: {", ".join(sorted(days))}. '
        f'Unknown/incomplete trade-stage observations: {unknown}. Horizon: {args.horizon}s; max age: {args.max_age}s. '
        'Dates without supplied saved research sessions are not evaluated, even if PCR records exist.\n\n')
    (args.output/'bullish-pcr-comparison.md').write_text(intro+'\n'.join(losers)+'\n\n'+'\n'.join(winners)+'\n')
    (args.output/'all-stage-pcr-details.md').write_text('\n'.join(stages)+'\n')
    (args.output/'report.json').write_text(json.dumps(dict(policy=POLICY,session_dates=sorted(days),provenance=proof,
        horizon=args.horizon,max_age=args.max_age,trades=trades,unknown_stage_count=unknown,orders_sent=False),indent=2))
    print('REPORT:',args.output/'bullish-pcr-comparison.md')
    print('STAGES:',args.output/'all-stage-pcr-details.md')

if __name__=='__main__':main()
