"""Offline full-session batch; uses saved candle sessions, never sends orders."""
import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path

spec=importlib.util.spec_from_file_location('timing_core',Path(__file__).with_name('run.py'))
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

def select_sessions(warm,before,count):
    if count<=0:raise ValueError('POSITIVE_SESSION_COUNT_REQUIRED')
    days=sorted({d for d,rows in warm if d<before and rows})
    if len(days)<count:raise ValueError('INSUFFICIENT_SAVED_SESSION_COVERAGE')
    return days[-count:]

def trade_signature(trades):
    return sorted((t['direction'],t['entry_time'],t['exit_time'],round(t['entry_price'],5),
        round(t['exit_price'],5),round(t['points'],5)) for t in trades)

def stats(trades):
    equity=peak=drawdown=0
    for t in sorted(trades,key=lambda t:t['exit_time']):
        equity+=t['points'];peak=max(peak,equity);drawdown=max(drawdown,peak-equity)
    return dict(trades=len(trades),winners=sum(t['points']>0 for t in trades),
        losers=sum(t['points']<0 for t in trades),flat=sum(t['points']==0 for t in trades),
        winning_points=sum(max(0,t['points']) for t in trades),
        losing_points=sum(min(0,t['points']) for t in trades),
        net_points=sum(t['points'] for t in trades),closed_trade_drawdown=drawdown)

def trade_tables(day,five,three):
    lines=['## '+day,'',
        'Rows pair trades by chronological sequence only; different cadences can create different signals.',
        '', '| # | 5m direction | Setup / qualified | Entry–exit | NIFTY points | 3m direction | Setup / qualified | Entry–exit | NIFTY points |',
        '|---|---|---|---|---:|---|---|---|---:|']
    def cells(t):
        if t is None:return ['—']*4
        hm=lambda v:v[11:16] if v else '—'
        return [t['direction'],hm(t.get('setup'))+' / '+hm(t.get('qualified')),
            hm(t['entry_time'])+'–'+hm(t['exit_time']),f"{t['points']:+.2f}"]
    for i in range(max(len(five['trades']),len(three['trades']))):
        a=five['trades'][i] if i<len(five['trades']) else None
        b=three['trades'][i] if i<len(three['trades']) else None
        lines.append('| '+' | '.join([str(i+1),*cells(a),*cells(b)])+' |')
    lines+=['','### Signal checks','',
        '| Policy | Time | Direction | RSI | EMA3 RSI | WMA | Strength | Gap | Expansion | Status | Reasons |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---|---|']
    for name,result in [('5m',five),('3m',three)]:
        for row in result['audit']:
            for c in row['checks']:
                def val(k):
                    v=c.get(k)
                    return f'{v:.3f}' if isinstance(v,(int,float)) else '—'
                reasons=', '.join(c.get('reasons',[])) or 'PASS'
                if name=='3m':reasons=reasons.replace('5M','3M').replace('PREVIOUS_MINUTE','PREVIOUS_CANDLE')
                lines.append('| '+' | '.join([name,row['time'][11:16],c['direction'],
                    val('current_rsi9'),val('current_ema3'),val('current_wma21'),
                    val('directional_wma_strength'),val('current_gap'),val('gap_delta'),
                    c.get('status','—'),reasons])+' |')
    return lines

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-zip',type=Path,required=True)
    ap.add_argument('--before',default='2026-10-21')
    ap.add_argument('--sessions',type=int,default=10)
    ap.add_argument('--today-input',type=Path)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    core.verify_sources()
    warm,records=core.read_inputs(args.input_zip)
    days=select_sessions(warm,args.before,args.sessions)
    inputs=dict(warm)
    if args.today_input:
        data=json.loads(args.today_input.read_text())
        if data['session_date']!=args.before:raise ValueError('TODAY_INPUT_DATE_MISMATCH')
        inputs[args.before]=data['candles']
        days.append(args.before)
    p3,l3=core.isolated_three()
    from market_lab import hilega_combined_replay_v1 as installed
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'sessions').mkdir(exist_ok=True)
    results=[];details=['# Daily trade and signal comparison','',
        'Research only. Gross NIFTY points, no fills, costs or live changes.']
    for day in days:
        until=datetime.fromisoformat(day+'T14:55:00+05:30')
        try:
            raw=inputs[day]
            five=core.run(core.policy5,core.legacy5,warm,raw,day,5,until)
            three=core.run(p3,l3,warm,raw,day,3,until)
            if five['open_trade'] or three['open_trade']:raise ValueError('UNRESOLVED_FULL_DAY_POSITION')
            if day==args.before:
                proof=core.parity(five,records,until)
                basis='RECORDED_LIVE_PARITY'
            else:
                original=installed.replay(day,raw,[(d,r) for d,r in warm if d<day])
                issues=[] if trade_signature(five['trades'])==trade_signature(original['trades']) else ['INSTALLED_REPLAY_TRADE_MISMATCH']
                proof=dict(status='PASS' if not issues else 'FAIL',issues=issues)
                basis='RECONSTRUCTED_INSTALLED_5M_PARITY'
            if proof['status']!='PASS':raise ValueError('BASELINE_PARITY_FAILED:'+json.dumps(proof))
            row=dict(session_date=day,status='COMPLETE',basis=basis,parity=proof,
                five=five,three=three,five_stats=stats(five['trades']),three_stats=stats(three['trades']))
            details+=trade_tables(day,five,three)+['']
        except Exception as exc:
            row=dict(session_date=day,status='INCOMPLETE',issues=[type(exc).__name__+': '+str(exc)])
        results.append(row)
        (args.output/'sessions'/(day+'.json')).write_text(json.dumps(row,indent=2))
        print(json.dumps({k:v for k,v in row.items() if k not in ('five','three')}),flush=True)
    complete=[r for r in results if r['status']=='COMPLETE']
    historical=[r for r in complete if r['session_date']<args.before]
    today=[r for r in complete if r['session_date']==args.before]
    lines=['# Full-session 5m versus 3m','',
        'Saved-session coverage: '+str(len(historical))+'/'+str(args.sessions),
        'Historical parity reproduces installed research, not historical live execution.',
        '3m recalculates indicators on 3m candles. Same numerical thresholds. No live changes.',
        '', '| Date | 5m trades | 5m points | 3m trades | 3m points | Difference |',
        '|---|---:|---:|---:|---:|---:|']
    for r in complete:
        a,b=r['five_stats'],r['three_stats']
        lines.append(f"| {r['session_date']} | {a['trades']} | {a['net_points']:+.2f} | {b['trades']} | {b['net_points']:+.2f} | {b['net_points']-a['net_points']:+.2f} |")
    lines+=['','| Period | Policy | Trades | Winning points | Losing points | Net points | Winners | Losers | Flat | Drawdown |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    totals={}
    for period,group in [('PREVIOUS_10',historical),('TODAY',today),('COMBINED',complete)]:
        if not group:continue
        totals[period]={}
        for key in ('five','three'):
            s=stats([t for r in group for t in r[key]['trades']]);totals[period][key]=s
            lines.append(f"| {period} | {'5m' if key=='five' else '3m'} | {s['trades']} | {s['winning_points']:+.2f} | {s['losing_points']:+.2f} | {s['net_points']:+.2f} | {s['winners']} | {s['losers']} | {s['flat']} | {s['closed_trade_drawdown']:.2f} |")
    failed=[r for r in results if r['status']!='COMPLETE']
    lines+=['','Incomplete sessions: '+json.dumps(failed)]
    report=dict(status='COMPLETE' if not failed else 'INCOMPLETE',sessions=results,totals=totals,
        selected_session_dates=days,coverage_basis='LATEST_NONEMPTY_SAVED_CANDLE_SESSIONS',
        warning='Missing saved dates are not independently verified against an exchange calendar.',
        observation_only=True,orders_sent=False)
    (args.output/'report.json').write_text(json.dumps(report,indent=2))
    (args.output/'summary.md').write_text('\n'.join(lines)+'\n')
    (args.output/'daily-trade-comparison.md').write_text('\n'.join(details)+'\n')
    print('\n'.join(lines))
    print('TRADE TABLES:',args.output/'daily-trade-comparison.md')

if __name__=='__main__':main()
