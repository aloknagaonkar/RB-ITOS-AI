"""Offline multi-session comparison of five HILEGA research policies.

Current 1m; retained 5m/no-persistence; +EMA10 exit; +WMA lock;
+corrected RSI/EMA lock exception (bullish>45, bearish<55).
No network calls, broker actions, service control or live strategy writes.
"""
import argparse
import csv
import hashlib
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

POLICIES=('ORIGINAL_CURRENT_1M','RETAINED_5M_NO_PERSISTENCE','RETAINED_5M_PLUS_EMA10_EXIT',
          'RETAINED_5M_EMA10_WMA_LOCK','RETAINED_5M_EMA10_WMA_EXCEPTION')
LABELS=('Existing strategy','Retained 5m, no persistence','+ EMA10 exit','+ WMA lock','+ RSI/EMA exceptions')

def load_stack(name=None):
    candidates=[name] if name else ['hilega_retained_ema10_wma_lock_research2','hilega_retained_ema10_wma_lock_research']
    for item in candidates:
        if not Path(item+'.py').exists():continue
        module=importlib.import_module(item)
        if not hasattr(module,'lock_exception_allows'):continue
        if (module.lock_exception_allows('BEARISH','BULLISH',dict(rsi9=46,ema3=46))
            and not module.lock_exception_allows('BEARISH','BULLISH',dict(rsi9=41,ema3=41))
            and module.lock_exception_allows('BULLISH','BEARISH',dict(rsi9=54,ema3=54))
            and not module.lock_exception_allows('BULLISH','BEARISH',dict(rsi9=56,ema3=56))):return module
    raise ValueError('CORRECTED_V2_STACK_MODULE_REQUIRED_BULL_GT45_BEAR_LT55')

def select_days(available,end,count,start=None):
    days=sorted({d for d in available if d<=end and (start is None or d>=start)})
    if start is None:
        if count<1 or len(days)<count:raise ValueError('INSUFFICIENT_SESSION_COVERAGE')
        days=days[-count:]
    if not days or days[-1]!=end:raise ValueError('END_SESSION_NOT_COVERED')
    return days

def trade_map(trades):
    mapped={(t['direction'],t['entry_time']):t for t in trades}
    if len(mapped)!=len(trades):raise ValueError('DUPLICATE_TRADE_IDENTITY')
    return mapped

def trade_cell(trade):
    return f"{trade['entry_time'][11:16]}–{trade['exit_time'][11:16]} · {float(trade['points']):+.2f}" if trade else '—'

class Checks(unittest.TestCase):
    def test_last_ten_sessions(self):
        self.assertEqual(select_days(['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16'],'2026-10-16',2),['2026-10-15','2026-10-16'])
    def test_range_ignores_count(self):
        self.assertEqual(select_days(['2026-10-12','2026-10-13'],'2026-10-13',10,'2026-10-12'),['2026-10-12','2026-10-13'])
    def test_missing_end_fails(self):
        with self.assertRaises(ValueError):select_days(['2026-10-15'],'2026-10-16',1)
    def test_duplicate_trade_fails(self):
        row=dict(direction='BULLISH',entry_time='a')
        with self.assertRaises(ValueError):trade_map([row,row])

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--end-date',default='2026-10-16');ap.add_argument('--sessions',type=int,default=10)
    ap.add_argument('--start-date',help='Use every cached session in this date range instead of --sessions.')
    ap.add_argument('--policy-module',default='hilega_retained_pending_day_research1')
    ap.add_argument('--stack-module',help='Corrected V2 stack; auto-detect research2.py then the canonical filename.')
    ap.add_argument('--research-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    ap.add_argument('--today-input',type=Path,default=Path('data/research/hilega-pending-previous10-plus-today-20261016-v3/today-recorded-overrides.json'))
    ap.add_argument('--audit',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-retained-policy-last10-20261016'))
    ap.add_argument('--test',action='store_true');a=ap.parse_args()
    stack=load_stack(a.stack_module)
    import hilega_ema10_exit_day_research as exits
    import hilega_post_entry_wma_lock_today_research as lock
    if a.test:
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (Checks,stack.Checks,exits.Checks,lock.Checks))
        r=unittest.TextTestRunner(verbosity=2).run(suite);raise SystemExit(0 if r.wasSuccessful() else 1)
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    retained=importlib.import_module(a.policy_module)
    if not hasattr(retained,'five_gate_no_persistence'):raise ValueError('UPDATED_RETAINED_POLICY_REQUIRED')
    import hilega_pending_confirmation_research as p
    import hilega_pending_previous10_research as batch
    import hilega_vwap_confirmed36_research as support
    from hilega_vwap_wait_alignment_research import source_data
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    if engine.RULES['version']!=p.VERSION:raise ValueError('ENGINE_VERSION_MISMATCH')
    if p.dt(a.end_date+'T14:55:00+05:30')>p.datetime.now(p.IST):raise ValueError('END_SESSION_NOT_COMPLETE')
    if a.start_date and a.start_date>a.end_date:raise ValueError('INVALID_DATE_RANGE')
    parent=json.loads((a.research_root/'3-month/report.json').read_text())
    if parent['strategy_version']!=p.VERSION:raise ValueError('SOURCE_VERSION_MISMATCH')
    sessions,grouped=source_data(a.research_root,parent,support)
    available=[d for d in sessions if parent['start_date']<=d<=parent['end_date']]
    extra=json.loads(a.today_input.read_text());extra_day=extra['session_date'];available.append(extra_day)
    days=select_days(available,a.end_date,a.sessions,a.start_date)
    a.output.mkdir(parents=True,exist_ok=True);coverage=[];evaluated={};provenance={}
    for day in days:
        row=dict(session_date=day,status='INCOMPLETE',issues=[])
        try:
            asof=p.dt(day+'T14:55:00+05:30')
            if day==extra_day:
                raw,warm,hashes=p.inputs(engine,day,a.today_input,False,a.output)
                source={**(extra.get('provenance') or {}),'warmup_sources_sha256':hashes}
                if not source.get('cutoff_payloads'):raise ValueError('RECORDED_CUTOFF_PROVENANCE_REQUIRED')
            else:
                raw=grouped[day];warm=[(d,grouped[d]) for d in sessions if d<day and grouped.get(d)][-30:]
                if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
                path=a.research_root/'replays'/(day+'.json');saved=json.loads(path.read_text())
                if saved['session_date']!=day or saved['strategy_version']!=p.VERSION:raise ValueError('FROZEN_BASELINE_IDENTITY_MISMATCH')
                source=dict(input_basis='FROZEN_RESEARCH_CACHE',baseline_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            raw=[r for r in raw if p.dt(r['timestamp'])<=asof]
            source['warmup_sessions']=len(warm)
            source['raw_and_warm_sha256']=hashlib.sha256(json.dumps([raw,warm],sort_keys=True,default=str).encode()).hexdigest()
            original=p.simulate(engine,day,raw,warm,asof,'CURRENT')
            if day==extra_day:
                parity=p.audit_parity(a.audit,day,asof,original)
                parity['issues'].extend(batch.cutoff_parity(original,source['cutoff_payloads']))
                if parity['issues']:parity['status']='MISMATCH'
            else:parity=batch.frozen_parity(saved,original)
            row.update(parity=parity,input_basis=source['input_basis'],warmup_sessions=len(warm))
            if parity['status']!='PASS':raise ValueError('BASELINE_PARITY_NOT_PASS')
            Base=retained.retained_gate(p.changed_gate(retained.five_gate_no_persistence(engine.WmaGapGate)),engine.direction)
            replay=retained.retained_replay(engine)
            em=exits.ema_frames(engine,day,raw,warm,p.dt);wm=lock.completed_frames(original,p.dt)
            indicators={p.dt(r['checkpoint']):r['completed_5m_indicators'] for r in original['audit']
                if r.get('nifty_close') is not None and r.get('completed_5m_indicators') and p.dt(r['checkpoint']).minute%5==0}
            Ema=exits.exit_gate(Base,em)
            specs=[(POLICIES[1],Base),(POLICIES[2],Ema),
                   (POLICIES[3],stack.retaining_lock_gate(Ema,engine.direction,wm,lock)),
                   (POLICIES[4],stack.exception_lock_gate(Ema,engine.direction,wm,indicators,lock))]
            result={POLICIES[0]:original}
            for name,Gate in specs:
                result[name]=p.simulate(SimpleNamespace(WmaGapGate=Gate,replay=replay),day,raw,warm,asof,'CURRENT')
                if any(p.dt(t['entry_time']).minute%5 for t in result[name]['trades']):raise ValueError('OFF_BOUNDARY_ENTRY:'+name)
            for name,value in result.items():
                batch.signature(value['trades']);trade_map(value['trades']);value['research_variant']=name
                dest=a.output/'sessions'/day/(name+'.json');dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_text(json.dumps(value,indent=2,default=str)+'\n')
            prior_path=Path('data/research/hilega-retained-ema10-wma-exception-v2-'+day.replace('-',''))/'report.json'
            if prior_path.exists():
                prior=json.loads(prior_path.read_text());prior_checks={}
                if prior.get('exception_policy_version')!='RSI_EMA_LOCK_EXCEPTION_V2_BULL_GT45_BEAR_LT55':
                    raise ValueError('PRIOR_EXCEPTION_VERSION_MISMATCH')
                for name in POLICIES:
                    prior_checks[name]=batch.frozen_parity(prior['results'][name],result[name])
                    if prior_checks[name]['status']!='PASS':raise ValueError('PREVIOUS_DAY_POLICY_PARITY_NOT_PASS:'+name)
                row['prior_policy_parity']=prior_checks
            # Current day is reproduced under all five variants from identical
            # inputs. Every session starts with newly constructed, empty gates.
            evaluated[day]=result;provenance[day]=source;row['status']='COMPLETE'
        except Exception as exc:row['issues'].append(type(exc).__name__+': '+str(exc))
        coverage.append(row);print(json.dumps(row,default=str),flush=True)
        (a.output/'progress.json').write_text(json.dumps(coverage,indent=2,default=str)+'\n')
    summary={k:batch.stats([t for d in sorted(evaluated) for t in evaluated[d][k]['trades']]) for k in POLICIES}
    warning='Research only: gross NIFTY points, not option P&L; fills/costs excluded. Only parity-passing sessions enter totals. Historical baseline is frozen research; latest recorded/API inputs are mixed and checkpoint parity does not verify every counterfactual minute. Standard WMA locks retain vetoed candidates. Corrected exception uses completed RSI9 AND EMA3 of RSI >45 for bullish under bearish lock, <55 for bearish under bullish lock; no 40/60 thresholds. EMA10 is NIFTY price EMA, close>EMA10 for both exit directions. No live changes.'
    report=dict(status='COMPLETE' if len(evaluated)==len(days) else 'INCOMPLETE',strategy_version=p.VERSION,
        session_dates=days,coverage=coverage,comparisons=summary,provenance=provenance,warning=warning,
        observation_only=True,orders_sent=False,exception_policy_version='RSI_EMA_LOCK_EXCEPTION_V2_BULL_GT45_BEAR_LT55',
        daily=[dict(session_date=d,comparisons={k:batch.stats(evaluated[d][k]['trades']) for k in POLICIES}) for d in sorted(evaluated)],
        source_sha256={str(Path(m.__file__)):hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in (retained,stack,exits,lock,engine)})
    (a.output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    lines=['# Retained policy multi-session comparison','',warning,'','Status: '+report['status'],f'Coverage: {len(evaluated)}/{len(days)}','',
        '| Policy | Trades | Points | Winners | Losers | Win rate % | Closed-trade drawdown |','|---|---:|---:|---:|---:|---:|---:|']
    for k,label in zip(POLICIES,LABELS):
        s=summary[k];lines.append(f"| {label} | {s['trades']} | {s['points']:.2f} | {s['winners']} | {s['losers']} | {s['win_rate_percent']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','## Daily NIFTY points','','| Date | '+' | '.join(LABELS)+' |','|---|'+'---:|'*len(POLICIES)]
    for day in sorted(evaluated):lines.append('| '+day+' | '+' | '.join(f"{batch.stats(evaluated[day][k]['trades'])['points']:+.2f}" for k in POLICIES)+' |')
    details=['# Daily entry and exit comparisons','',warning,'',
        'All times IST. Cell format: entry–exit · NIFTY points. Rows match exact direction and entry time, not assumed trade correspondence. Different entry times appear on separate rows. A dash means no entry at that time; it does not by itself prove a direct rejection. Explicit lock vetoes appear in the lock audit.','']
    for day in sorted(evaluated):
        maps={k:trade_map(evaluated[day][k]['trades']) for k in POLICIES}
        identities=sorted(set().union(*(set(m) for m in maps.values())),key=lambda x:(x[1],x[0]))
        details+=['','## '+day,'','| Direction | Entry | '+' | '.join(LABELS)+' |','|---|---|'+'---|'*len(POLICIES)]
        for side,at in identities:details.append('| '+side+' | '+at[11:16]+' | '+' | '.join(trade_cell(maps[k].get((side,at))) for k in POLICIES)+' |')
        details.append('| **Total** | | '+' | '.join(f"**{batch.stats(evaluated[day][k]['trades'])['points']:+.2f}**" for k in POLICIES)+' |')
        details+=['','### Lock audit','','| Policy | Time | Event | Details |','|---|---|---|---|']
        for k in POLICIES[3:]:
            for e in evaluated[day][k]['policy_events']:
                event=e['event'];description=None
                if event=='POST_ENTRY_LOCK_CHANGE':description=f"{e['before']} → {e['after']}; WMA {e['wma21']:.3f}; {e['reason']}"
                elif event=='CONFIRMED_ENTRY_LOCK_CHECK':description=f"{e['direction']}; lock {e['lock']}; allowed={e['allowed']}; WMA {e['wma21']:.3f}"
                elif event=='WMA_LOCK_EXCEPTION_CHECK':description=f"{e['direction']}; RSI {e['rsi9']:.3f}; EMA3 {e['ema3_rsi']:.3f}; allowed={e['allowed']}"
                if description:details.append(f"| {LABELS[POLICIES.index(k)]} | {e['time'][11:16]} | {event} | {description} |")
    lines+=['','Incomplete sessions: '+json.dumps([r for r in coverage if r['status']!='COMPLETE'],default=str)]
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text)
    (a.output/'daily-trade-comparison.md').write_text('\n'.join(details)+'\n')
    with (a.output/'trades.csv').open('w',newline='') as handle:
        fields=['session_date','policy','direction','signal_time','entry_time','entry_price','exit_time','exit_price','points','exit_reason']
        writer=csv.DictWriter(handle,fields,extrasaction='ignore');writer.writeheader()
        for day in sorted(evaluated):
            for k in POLICIES:
                for t in evaluated[day][k]['trades']:writer.writerow(dict(t,session_date=day,policy=k))
    print(text);print('TRADE TABLES:',a.output/'daily-trade-comparison.md');print('REPORT:',a.output/'report.json')
    raise SystemExit(0 if report['status']=='COMPLETE' else 2)

if __name__=='__main__':main()
