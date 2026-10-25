"""Cache-only last-five-session post-entry WMA lock research.

Reuses the exact tested today policy, including its existing setup/confirmation
rules and exits. Never installs strategy changes, fetches quotes or sends orders.
Historical results must reproduce the frozen baseline before being aggregated.
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

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def select_days(sessions,end,count):
    days=sorted({d for d in sessions if d<=end})[-count:]
    if count<1 or len(days)!=count or days[-1]!=end:
        raise ValueError('REQUESTED_SESSION_COVERAGE_REQUIRED')
    return days

def require_first_entry(baseline,research):
    if baseline['trades']:
        if not research['trades']:raise ValueError('FIRST_ENTRY_MUST_NOT_BE_BLOCKED')
        if any(baseline['trades'][0][k]!=research['trades'][0][k] for k in ('direction','entry_time','entry_price')):
            raise ValueError('FIRST_NORMAL_ENTRY_CHANGED')

class Checks(unittest.TestCase):
    def test_five_sessions_include_end(self):
        self.assertEqual(select_days(['2026-10-09','2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16'],'2026-10-16',5),
                         ['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16'])
    def test_missing_end_rejected(self):
        with self.assertRaises(ValueError):select_days(['2026-10-15'],'2026-10-16',1)
    def test_short_coverage_rejected(self):
        with self.assertRaises(ValueError):select_days(['2026-10-16'],'2026-10-16',5)
    def test_first_trade_changed_rejected(self):
        b={'trades':[dict(direction='BULLISH',entry_time='a',entry_price=100)]}
        with self.assertRaises(ValueError):require_first_entry(b,{'trades':[dict(direction='BULLISH',entry_time='b',entry_price=100)]})
    def test_flat_baseline_allowed(self):require_first_entry({'trades':[]},{'trades':[]})

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--end-date',default='2026-10-16')
    ap.add_argument('--sessions',type=int,default=5)
    ap.add_argument('--research-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    ap.add_argument('--today-input',type=Path,default=Path('data/research/hilega-pending-previous10-plus-today-20261016-v3/today-recorded-overrides.json'))
    ap.add_argument('--audit',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-post-entry-wma-lock-last5-20261016'))
    ap.add_argument('--test',action='store_true');a=ap.parse_args()
    if a.test:
        import hilega_post_entry_wma_lock_today_research as lock
        suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(Checks),
                                 unittest.defaultTestLoader.loadTestsFromTestCase(lock.Checks)])
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if a.sessions<1:ap.error('--sessions must be positive')
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    import hilega_post_entry_wma_lock_today_research as lock
    import hilega_pending_confirmation_research as p
    import hilega_pending_previous10_research as batch
    import hilega_vwap_confirmed36_research as support
    from hilega_vwap_wait_alignment_research import source_data
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    if engine.RULES['version']!=p.VERSION:raise ValueError('ENGINE_VERSION_MISMATCH')
    if p.dt(a.end_date+'T14:55:00+05:30')>p.datetime.now(p.IST):raise ValueError('SESSION_NOT_COMPLETE')
    parent=json.loads((a.research_root/'3-month/report.json').read_text())
    if parent['strategy_version']!=p.VERSION:raise ValueError('SOURCE_VERSION_MISMATCH')
    sessions,grouped=source_data(a.research_root,parent,support)
    extra=json.loads(a.today_input.read_text());extra_day=extra['session_date']
    days=select_days([d for d in sessions if parent['start_date']<=d<=parent['end_date']]+[extra_day],a.end_date,a.sessions)
    a.output.mkdir(parents=True,exist_ok=True)
    coverage=[];evaluated={};screens={};sources={}
    for day in days:
        row=dict(session_date=day,status='INCOMPLETE',issues=[])
        try:
            asof=p.dt(day+'T14:55:00+05:30')
            if day==extra_day:
                raw,warm,hashes=p.inputs(engine,day,a.today_input,False,a.output)
                source=dict(extra.get('provenance') or {},input_sha256=digest(a.today_input),warmup_sources_sha256=hashes)
                if not source.get('cutoff_payloads'):raise ValueError('RECORDED_CUTOFF_PROVENANCE_REQUIRED')
            else:
                raw=grouped[day];warm=[(d,grouped[d]) for d in sessions if d<day and grouped.get(d)][-30:]
                if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
                path=a.research_root/'replays'/(day+'.json');saved=json.loads(path.read_text())
                if saved['session_date']!=day or saved['strategy_version']!=p.VERSION:raise ValueError('FROZEN_BASELINE_IDENTITY_MISMATCH')
                source=dict(input_basis='FROZEN_RESEARCH_CACHE',baseline_sha256=digest(path))
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
            require_first_entry(baseline,changed)
            result=dict(CURRENT=baseline,POST_ENTRY_WMA_LOCK=changed)
            for name,value in result.items():
                batch.signature(value['trades'])
                dest=a.output/'sessions'/day/(name+'.json');dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_text(json.dumps(value,indent=2,default=str)+'\n')
            screen,events=lock.frozen_screen(baseline['trades'],frames,p.dt)
            screens[day]=dict(trades=screen,lock_events=events)
            evaluated[day]=result;sources[day]=source;row['status']='COMPLETE'
        except Exception as exc:row['issues'].append(type(exc).__name__+': '+str(exc))
        coverage.append(row);print(json.dumps(row,default=str),flush=True)
        (a.output/'progress.json').write_text(json.dumps(coverage,indent=2,default=str)+'\n')
    totals={name:batch.stats([t for day in sorted(evaluated) for t in evaluated[day][name]['trades']]) for name in POLICIES}
    warning=('Gross NIFTY points, not option P&L; costs excluded. Only parity-passing sessions enter totals. '
             'Historical sessions use frozen research inputs; latest recorded/API inputs are mixed. '
             'Checkpoint parity does not verify every counterfactual minute. No live changes. '
             'Frozen-baseline blocked counts and stateful trade-count changes are separate measures.')
    report=dict(status='COMPLETE' if len(evaluated)==len(days) else 'INCOMPLETE',strategy_version=p.VERSION,
                session_dates=days,coverage=coverage,comparisons=totals,provenance=sources,
                daily=[dict(session_date=d,comparisons={k:batch.stats(v['trades']) for k,v in evaluated[d].items()}) for d in sorted(evaluated)],
                frozen_baseline_screen=screens,observation_only=True,orders_sent=False,warning=warning,
                policy_sha256=digest(Path(lock.__file__)),runner_sha256=digest(Path(__file__)),engine_sha256=digest(Path(engine.__file__)))
    (a.output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    with (a.output/'trades.csv').open('w',newline='') as handle:
        fields=['session_date','policy','direction','signal_time','entry_time','entry_price','exit_time','exit_price','points','exit_reason']
        writer=csv.DictWriter(handle,fields,extrasaction='ignore');writer.writeheader()
        for day in sorted(evaluated):
            for name in POLICIES:
                for t in evaluated[day][name]['trades']:writer.writerow(dict(t,session_date=day,policy=name))
    lines=['# Post-entry WMA lock — last five sessions','',warning,'','Status: '+report['status'],
           'Coverage: '+str(len(evaluated))+'/'+str(len(days)),'',
           '| Policy | Trades | Points | Winners | Losers | Closed-trade drawdown |','|---|---:|---:|---:|---:|---:|']
    for name,s in totals.items():lines.append(f"| {name} | {s['trades']} | {s['points']:.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','| Date | Current trades | Current points | Lock trades | Lock points | Change | Baseline losers blocked* | Baseline winners blocked* |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for d in sorted(evaluated):
        b=batch.stats(evaluated[d]['CURRENT']['trades']);n=batch.stats(evaluated[d][POLICIES[1]]['trades'])
        blocked=[t for t in screens[d]['trades'] if not t['passed']]
        lines.append(f"| {d} | {b['trades']} | {b['points']:.2f} | {n['trades']} | {n['points']:.2f} | {n['points']-b['points']:.2f} | {sum(t['points']<0 for t in blocked)} | {sum(t['points']>0 for t in blocked)} |")
    lines+=['','*Frozen-baseline screen; consult the stateful trade lists below for actual research entries.']
    for d in sorted(evaluated):
        lines+=['','## '+d,'','| Policy | Direction | Setup | Entry | Exit | Points |','|---|---|---|---|---|---:|']
        for name in POLICIES:
            for t in evaluated[d][name]['trades']:
                lines.append(f"| {name} | {t['direction']} | {t['signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['points']:.2f} |")
        lines+=['','| Lock time | Before | After | WMA | Reason |','|---|---|---|---:|---|']
        for e in evaluated[d][POLICIES[1]]['policy_events']:
            if e['event']=='POST_ENTRY_LOCK_CHANGE':lines.append(f"| {e['time'][11:16]} | {e['before']} | {e['after']} | {e['wma21']:.3f} | {e['reason']} |")
    lines+=['','Incomplete sessions: '+json.dumps([r for r in coverage if r['status']!='COMPLETE'],default=str)]
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);print(text);print('REPORT:',a.output/'report.json')
    raise SystemExit(0 if report['status']=='COMPLETE' else 2)

if __name__=='__main__':main()
