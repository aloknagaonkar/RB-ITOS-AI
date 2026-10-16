"""Offline WMA post-entry lock: June-August, September and October 2026.

Requires the existing today policy and replay helpers. No network, broker,
service or live strategy changes. Missing frozen baselines are never fabricated.
October is month-to-date through --as-of, default 2026-10-16.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

POLICIES=('CURRENT','POST_ENTRY_WMA_LOCK')
PERIODS={
    'JUNE':('2026-06-01','2026-06-30'),
    'JULY':('2026-07-01','2026-07-31'),
    'AUGUST':('2026-08-01','2026-08-31'),
    'JUNE_JULY_AUGUST':('2026-06-01','2026-08-31'),
    'SEPTEMBER':('2026-09-01','2026-09-30'),
    'OCTOBER_MTD':('2026-10-01','2026-10-16'),
}

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def dates_for(days,start,end):return sorted({d for d in days if start<=d<=end})

def baseline_for(day,roots,version):
    found=[]
    for root in roots:
        for path in (root/'replays'/(day+'.json'),root/(day+'.json')):
            if not path.exists():continue
            row=json.loads(path.read_text())
            if row.get('session_date')==day and row.get('strategy_version')==version and isinstance(row.get('audit'),list) and isinstance(row.get('trades'),list):
                found.append((path,row))
    if not found:raise ValueError('VERSION_MATCHED_FROZEN_BASELINE_REQUIRED:'+day)
    # Full trade/audit parity is checked after replay. Never accept a baseline
    # solely because its filename or strategy label happens to match.
    return found[0]

def first_entry_unchanged(b,n):
    if b['trades'] and (not n['trades'] or any(b['trades'][0][k]!=n['trades'][0][k] for k in ('direction','entry_time','entry_price'))):
        raise ValueError('FIRST_NORMAL_ENTRY_CHANGED')

class Checks(unittest.TestCase):
    def test_june_aug_excludes_september(self):
        self.assertEqual(dates_for(['2026-08-31','2026-09-01','2026-06-01'],'2026-06-01','2026-08-31'),['2026-06-01','2026-08-31'])
    def test_sessions_deduplicated(self):
        self.assertEqual(dates_for(['2026-10-01','2026-10-01'],'2026-10-01','2026-10-16'),['2026-10-01'])
    def test_empty_first_entry_allowed(self):first_entry_unchanged({'trades':[]},{'trades':[]})
    def test_first_trade_cannot_be_blocked(self):
        with self.assertRaises(ValueError):first_entry_unchanged({'trades':[dict(direction='BULLISH',entry_time='a',entry_price=10)]},{'trades':[]})
    def test_missing_baseline_fails(self):
        with self.assertRaises(ValueError):baseline_for('2026-06-01',[],'v')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--research-root',type=Path,action='append',help='Existing cache root with 3-month/report.json and raw-provider-get; repeat to extend coverage.')
    ap.add_argument('--baseline-root',type=Path,action='append',default=[],help='Additional root containing replays/YYYY-MM-DD.json or YYYY-MM-DD.json.')
    ap.add_argument('--today-input',type=Path,default=Path('data/research/hilega-pending-previous10-plus-today-20261016-v3/today-recorded-overrides.json'))
    ap.add_argument('--audit',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    ap.add_argument('--as-of',default='2026-10-16')
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-post-entry-wma-lock-months-20261016'))
    ap.add_argument('--test',action='store_true');a=ap.parse_args()
    import hilega_post_entry_wma_lock_today_research as lock
    if a.test:
        suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(Checks),unittest.defaultTestLoader.loadTestsFromTestCase(lock.Checks)])
        r=unittest.TextTestRunner(verbosity=2).run(suite);raise SystemExit(0 if r.wasSuccessful() else 1)
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    import hilega_pending_confirmation_research as p
    import hilega_pending_previous10_research as batch
    import hilega_vwap_confirmed36_research as support
    from hilega_vwap_wait_alignment_research import source_data
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    if engine.RULES['version']!=p.VERSION:raise ValueError('ENGINE_VERSION_MISMATCH')
    if not '2026-10-01'<=a.as_of<='2026-10-31':raise ValueError('AS_OF_MUST_BE_OCTOBER_2026')
    if p.dt(a.as_of+'T14:55:00+05:30')>p.datetime.now(p.IST):raise ValueError('AS_OF_SESSION_NOT_COMPLETE')
    roots=a.research_root or [Path('data/research/hilega-vwap-monthly-20261015')]
    baseline_roots=roots+a.baseline_root
    calendars=set();grouped={};conflicts=set();cache_sources=[]
    for root in roots:
        parent_path=root/'3-month/report.json';parent=json.loads(parent_path.read_text())
        if parent['strategy_version']!=p.VERSION:raise ValueError('SOURCE_VERSION_MISMATCH:'+str(root))
        sessions,rows=source_data(root,parent,support);calendars.update(sessions)
        for day,values in rows.items():
            if day in grouped and grouped[day]!=values:conflicts.add(day)
            else:grouped[day]=values
        cache_sources.append(dict(root=str(root),report_sha256=digest(parent_path),first_calendar=min(sessions),last_calendar=max(sessions)))
    # Raw daily calendars include the historical warmup dates. Their presence
    # does not imply a version-matched replay exists for those earlier dates.
    extra=json.loads(a.today_input.read_text());extra_day=extra['session_date']
    calendars.add(extra_day)
    dates=dates_for(calendars,'2026-06-01',a.as_of)
    a.output.mkdir(parents=True,exist_ok=True);coverage=[];evaluated={};screens={};sources={}
    for day in dates:
        row=dict(session_date=day,status='INCOMPLETE',issues=[])
        try:
            asof=p.dt(day+'T14:55:00+05:30')
            if day==extra_day:
                raw,warm,hashes=p.inputs(engine,day,a.today_input,False,a.output)
                source={**(extra.get('provenance') or {}),'input_sha256':digest(a.today_input),'warmup_sources_sha256':hashes}
                if not source.get('cutoff_payloads'):raise ValueError('RECORDED_CUTOFF_PROVENANCE_REQUIRED')
            else:
                path,saved=baseline_for(day,baseline_roots,p.VERSION)
                if day in conflicts:raise ValueError('CONFLICTING_RAW_CACHE:'+day)
                if day not in grouped:raise ValueError('RAW_MINUTE_DATA_REQUIRED:'+day)
                raw=grouped[day];warm_days=[d for d in sorted(calendars) if d<day and grouped.get(d)][-30:]
                if any(d in conflicts for d in warm_days):raise ValueError('CONFLICTING_WARMUP_CACHE')
                warm=[(d,grouped[d]) for d in warm_days]
                if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
                source=dict(input_basis='FROZEN_RESEARCH_CACHE',baseline_path=str(path),baseline_sha256=digest(path))
            raw=[r for r in raw if p.dt(r['timestamp'])<=asof]
            source['warmup_sessions']=len(warm)
            source['raw_and_warm_sha256']=hashlib.sha256(json.dumps([raw,warm],sort_keys=True,default=str).encode()).hexdigest()
            baseline=p.simulate(engine,day,raw,warm,asof,'CURRENT')
            if day==extra_day:
                parity=p.audit_parity(a.audit,day,asof,baseline)
                parity['issues'].extend(batch.cutoff_parity(baseline,source['cutoff_payloads']))
                if parity['issues']:parity['status']='MISMATCH'
            else:parity=batch.frozen_parity(saved,baseline)
            row.update(parity=parity,input_basis=source['input_basis'],warmup_sessions=len(warm))
            if parity['status']!='PASS':raise ValueError('BASELINE_PARITY_NOT_PASS')
            frames=lock.completed_frames(baseline,p.dt)
            proxy=SimpleNamespace(WmaGapGate=lock.lock_gate(engine.WmaGapGate,engine.direction,frames),replay=engine.replay)
            changed=p.simulate(proxy,day,raw,warm,asof,'CURRENT');changed['research_variant']=POLICIES[1]
            first_entry_unchanged(baseline,changed)
            result=dict(CURRENT=baseline,POST_ENTRY_WMA_LOCK=changed)
            for name,value in result.items():
                batch.signature(value['trades']);dest=a.output/'sessions'/day/(name+'.json')
                dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(value,indent=2,default=str)+'\n')
            screen,events=lock.frozen_screen(baseline['trades'],frames,p.dt)
            screens[day]=dict(trades=screen,lock_events=events);evaluated[day]=result;sources[day]=source;row['status']='COMPLETE'
        except Exception as exc:row['issues'].append(type(exc).__name__+': '+str(exc))
        coverage.append(row);print(json.dumps(row,default=str),flush=True)
        (a.output/'progress.json').write_text(json.dumps(coverage,indent=2,default=str)+'\n')
    periods={}
    for name,(start,end) in PERIODS.items():
        if name=='OCTOBER_MTD':end=a.as_of
        requested=dates_for(calendars,start,end);valid=[d for d in requested if d in evaluated]
        # Daily calendar envelope must cover both requested endpoints; absent
        # cache months are not silently interpreted as holidays or zero trades.
        calendar_covered=bool(calendars and min(calendars)<=start and max(calendars)>=end)
        comparisons={k:batch.stats([t for d in valid for t in evaluated[d][k]['trades']]) for k in POLICIES}
        directional={side:{k:batch.stats([t for d in valid for t in evaluated[d][k]['trades'] if t['direction']==side]) for k in POLICIES} for side in ('BULLISH','BEARISH')}
        blocked=[t for d in valid for t in screens[d]['trades'] if not t['passed']]
        periods[name]=dict(start_date=start,end_date=end,calendar_envelope_covered=calendar_covered,requested_sessions=len(requested),comparable_sessions=len(valid),
            status='COMPLETE' if requested and calendar_covered and len(valid)==len(requested) else 'INCOMPLETE',
            comparisons=comparisons,directional=directional,session_dates=valid,
            fixed_baseline_blocked=batch.stats(blocked),losers_blocked=sum(t['points']<0 for t in blocked),winners_blocked=sum(t['points']>0 for t in blocked),
            loss_points_avoided=round(-sum(t['points'] for t in blocked if t['points']<0),4),profit_points_forgone=round(sum(t['points'] for t in blocked if t['points']>0),4))
    warning=('Research only, gross NIFTY points, no option fills/costs. Frozen historical baselines; latest recorded/API inputs mixed. '
             'Only parity-passing days enter totals. Partial periods cannot be treated as full-month results. '
             'Calendar-envelope coverage does not independently certify every exchange holiday. '
             'Counterfactual minute inputs are not all verified. Month groups overlap the combined June-August period; do not add them twice. '
             'Frozen-baseline blocked counts differ from stateful trade-count changes. No live changes.')
    report=dict(status='COMPLETE' if all(v['status']=='COMPLETE' for v in periods.values()) else 'INCOMPLETE',strategy_version=p.VERSION,
        periods=periods,coverage=coverage,cache_sources=cache_sources,provenance=sources,frozen_baseline_screen=screens,warning=warning,
        observation_only=True,orders_sent=False,policy_sha256=digest(Path(lock.__file__)),runner_sha256=digest(Path(__file__)),engine_sha256=digest(Path(engine.__file__)))
    (a.output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    lines=['# Post-entry WMA lock — monthly comparisons','',warning,'','Status: '+report['status'],'',
           '| Period | Status | Sessions | Policy | Trades | Points | Winners | Losers | Drawdown |',
           '|---|---|---|---|---:|---:|---:|---:|---:|']
    for name,v in periods.items():
        for k,s in v['comparisons'].items():lines.append(f"| {name} | {v['status']} | {v['comparable_sessions']}/{v['requested_sessions']} | {k} | {s['trades']} | {s['points']:.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','## Blocked baseline trades','','| Period | Losing trades blocked | Winning trades blocked | Loss points avoided | Winner points forgone |','|---|---:|---:|---:|---:|']
    for name,v in periods.items():lines.append(f"| {name} | {v['losers_blocked']} | {v['winners_blocked']} | {v['loss_points_avoided']:.2f} | {v['profit_points_forgone']:.2f} |")
    lines+=['','## Directional comparison','','| Period | Direction | Current trades | Current points | Lock trades | Lock points |','|---|---|---:|---:|---:|---:|']
    for name,v in periods.items():
        for side,values in v['directional'].items():
            b,n=(values[k] for k in POLICIES);lines.append(f"| {name} | {side} | {b['trades']} | {b['points']:.2f} | {n['trades']} | {n['points']:.2f} |")
    lines+=['','## Daily comparison','','| Date | Current trades | Current points | Lock trades | Lock points | Change |','|---|---:|---:|---:|---:|---:|']
    for day in sorted(evaluated):
        b,n=(batch.stats(evaluated[day][k]['trades']) for k in POLICIES)
        lines.append(f"| {day} | {b['trades']} | {b['points']:.2f} | {n['trades']} | {n['points']:.2f} | {n['points']-b['points']:.2f} |")
    lines+=['','## Missing or rejected sessions','']
    for row in coverage:
        if row['status']!='COMPLETE':lines.append('- '+row['session_date']+': '+ '; '.join(row['issues']))
    for name,v in periods.items():
        if not v['calendar_envelope_covered']:lines.append('- '+name+': DAILY_CALENDAR_RANGE_INCOMPLETE')
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text)
    with (a.output/'trades.csv').open('w',newline='') as handle:
        fields=['session_date','policy','direction','signal_time','entry_time','entry_price','exit_time','exit_price','points','exit_reason']
        writer=csv.DictWriter(handle,fields,extrasaction='ignore');writer.writeheader()
        for day in sorted(evaluated):
            for k in POLICIES:
                for t in evaluated[day][k]['trades']:writer.writerow(dict(t,session_date=day,policy=k))
    with (a.output/'baseline-taken-blocked.csv').open('w',newline='') as handle:
        fields=['session_date','direction','entry_time','exit_time','points','passed','lock_at_entry','wma21']
        writer=csv.DictWriter(handle,fields,extrasaction='ignore');writer.writeheader()
        for day in sorted(screens):
            for t in screens[day]['trades']:writer.writerow(dict(t,session_date=day))
    print(text);print('REPORT:',a.output/'report.json')
    raise SystemExit(0 if report['status']=='COMPLETE' else 2)

if __name__=='__main__':main()
