"""Thirty trading sessions: existing baseline / previous AND / fresh setups + AND.
Research only. Cached inputs only; no orders, service control or live changes.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

MODEL='AND_FRESH_SETUP_THIRTY_SESSION_COMPARISON_V1'
POLICIES=('EXISTING','PREVIOUS_AND','FRESH_AND')
LABELS=('Existing baseline','Previous AND','Fresh setups + AND')


def select_sessions(calendar,start,end,count,extra_day):
    if count<1:raise ValueError('POSITIVE_SESSION_COUNT_REQUIRED')
    candidates=sorted({d for d in calendar if start<=d<=end} | ({extra_day} if start<=extra_day<=end else set()))
    if not candidates or candidates[-1]!=end:raise ValueError('END_SESSION_UNAVAILABLE')
    if len(candidates)<count:raise ValueError('INSUFFICIENT_SESSION_COVERAGE')
    return candidates[-count:]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--test',action='store_true')
    ap.add_argument('--sessions',type=int,default=30)
    ap.add_argument('--end-date',default='2026-10-16')
    ap.add_argument('--research-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    ap.add_argument('--today-input',type=Path,default=Path('data/research/hilega-pending-previous10-plus-today-20261016-v3/today-recorded-overrides.json'))
    ap.add_argument('--previous-and-root',type=Path,default=Path('data/research/hilega-existing-minute-wma-exception-no-ema-last10-20261016'))
    ap.add_argument('--previous-fresh-root',type=Path,default=Path('data/research/hilega-and-fresh-setup-last10-20261016'))
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-and-fresh-setup-30sessions-20261016'))
    args=ap.parse_args()
    import hilega_and_fresh_setup_last10_research as fresh
    import hilega_existing_minute_wma_exception_no_ema_last10_research as previous
    import hilega_existing_ema10_wma_exception_40_60_last10_research as exception
    import hilega_wma_threshold_only_oct14_research as threshold
    if args.test:
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in
            (Checks,fresh.Checks,previous.Checks,exception.Checks,threshold.Checks))
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    import hilega_pending_confirmation_research as p
    import hilega_pending_previous10_research as stats
    import hilega_vwap_confirmed36_research as support
    import hilega_post_entry_wma_lock_today_research as lock
    from hilega_vwap_wait_alignment_research import source_data
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    if engine.RULES['version']!=p.VERSION:raise ValueError('ENGINE_VERSION_MISMATCH')
    if p.dt(args.end_date+'T14:55:00+05:30')>p.datetime.now(p.IST):raise ValueError('FULL_END_SESSION_NOT_COMPLETE')
    parent=json.loads((args.research_root/'3-month/report.json').read_text())
    if parent['strategy_version']!=p.VERSION:raise ValueError('SOURCE_VERSION_MISMATCH')
    calendar,grouped=source_data(args.research_root,parent,support)
    extra=json.loads(args.today_input.read_text())
    days=select_sessions(calendar,parent['start_date'],args.end_date,args.sessions,extra['session_date'])
    old_and=json.loads((args.previous_and_root/'report.json').read_text())
    old_fresh=json.loads((args.previous_fresh_root/'report.json').read_text())
    if old_and['status']!='COMPLETE' or old_and['model']!='EXISTING_1M_WMA_EXCEPTION_40_60_ORIGINAL_EXITS_V1':
        raise ValueError('VERIFIED_PREVIOUS_AND_REPORT_REQUIRED')
    if old_fresh['status']!='COMPLETE' or old_fresh['model']!='AND_40_60_FRESH_5M_SETUP_ORIGINAL_1M_CONFIRMATION_V1':
        raise ValueError('VERIFIED_PREVIOUS_FRESH_REPORT_REQUIRED')
    args.output.mkdir(parents=True,exist_ok=True)
    results={};coverage=[];provenance={}
    for day in days:
        status=dict(session_date=day,status='INCOMPLETE',issues=[])
        try:
            asof=p.dt(day+'T14:55:00+05:30')
            if day==extra['session_date']:
                raw,warm,_=p.inputs(engine,day,args.today_input,False,args.output)
                saved=json.loads((args.previous_fresh_root/'sessions'/(day+'.json')).read_text())['EXISTING']
                basis='RECORDED_LIVE_WHERE_AVAILABLE_OTHERWISE_LATER_API'
            else:
                raw=grouped[day]
                warm=[(d,grouped[d]) for d in calendar if d<day and grouped.get(d)][-30:]
                saved=json.loads((args.research_root/'replays'/(day+'.json')).read_text())
                basis='FROZEN_RESEARCH_CACHE'
            if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
            if saved['session_date']!=day or saved['strategy_version']!=p.VERSION:raise ValueError('BASELINE_IDENTITY_MISMATCH')
            raw=[r for r in raw if p.dt(r['timestamp'])<=asof]
            digest=hashlib.sha256(json.dumps([raw,warm],sort_keys=True,default=str).encode()).hexdigest()
            baseline=p.simulate(engine,day,raw,warm,asof,'CURRENT')
            parity=stats.frozen_parity(saved,baseline)
            if parity['status']!='PASS':raise ValueError('BASELINE_PARITY_FAILED:'+json.dumps(parity))
            wm=lock.completed_frames(baseline,p.dt)
            for audit_row in baseline['audit']:
                boundary=p.dt(audit_row['checkpoint'])
                if boundary in wm and audit_row.get('completed_5m_indicators') and audit_row.get('nifty_close') is not None:
                    wm[boundary].update(rsi9=audit_row['completed_5m_indicators']['rsi9'],ema3=audit_row['completed_5m_indicators']['ema3'])
            first=min(wm)
            opening=next(r for r in baseline['audit'] if p.dt(r['checkpoint'])==first and r.get('completed_5m_indicators'))
            delta=opening['five_minute_changes']['wma21']
            if delta is None:raise ValueError('OPENING_REFERENCE_REQUIRED')
            wm[first]['previous_wma21']=wm[first]['wma21']-delta
            Gate=previous.combined_gate(engine,{},wm,lock,None,threshold)
            old=p.simulate(SimpleNamespace(WmaGapGate=Gate,replay=engine.replay),day,raw,warm,asof,'CURRENT')
            NewGate=fresh.combined_gate(engine,{},wm,lock,None,threshold)
            new=p.simulate(SimpleNamespace(WmaGapGate=NewGate,replay=fresh.fresh_replay(engine)),day,raw,warm,asof,'CURRENT')
            variants=dict(EXISTING=baseline,PREVIOUS_AND=old,FRESH_AND=new)
            for value in variants.values():stats.signature(value['trades'])
            for value in (old,new):
                if any(e['event'].startswith('EMA_EXIT') or e['event']=='CONFIRMED_OPPOSITE_EXIT_OVERRIDE' for e in value['policy_events']):
                    raise ValueError('DISABLED_FEATURE_USED')
            overlap={}
            for key,root,prior,value in (('PREVIOUS_AND',args.previous_and_root,old_and,old),('FRESH_AND',args.previous_fresh_root,old_fresh,new)):
                if day in prior['session_dates']:
                    if digest!=prior['provenance'][day]['input_sha256']:raise ValueError('PREVIOUS_TEN_INPUT_MISMATCH:'+key)
                    recorded=json.loads((root/'sessions'/(day+'.json')).read_text())
                    if stats.signature(recorded['COMBINED']['trades'])!=stats.signature(value['trades']):raise ValueError('PREVIOUS_TEN_POLICY_PARITY_FAILED:'+key)
                    overlap[key]='PASS'
            dest=args.output/'sessions'/(day+'.json');dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_text(json.dumps(variants,indent=2,default=str)+'\n')
            results[day]=variants
            provenance[day]=dict(input_sha256=digest,warmup_sessions=len(warm),input_basis=basis,baseline_parity=parity,previous_ten_policy_parity=overlap)
            status.update(status='COMPLETE',parity=parity,previous_ten_policy_parity=overlap)
        except Exception as exc:status['issues'].append(type(exc).__name__+': '+str(exc))
        coverage.append(status);print(json.dumps(status),flush=True)
    write_reports(args.output,days,results,coverage,provenance,p.VERSION,fresh.WARNING,stats)
    raise SystemExit(0 if len(results)==len(days) else 2)


def write_reports(output,days,results,coverage,provenance,version,warning,stats):
    import hilega_existing_ema10_wma_combined_last10_research as base
    complete=len(results)==len(days)
    totals={key:stats.stats([t for day in sorted(results) for t in results[day][key]['trades']]) for key in POLICIES}
    lines=['# Existing / Previous AND / Fresh setups + AND','',warning,'',
        f"Status: {'COMPLETE' if complete else 'INCOMPLETE'}; coverage {len(results)}/{len(days)} trading sessions.",
        'Incomplete sessions are excluded from all three totals. Previous AND uses the original one-per-alignment-episode setup rule. Fresh AND reevaluates setup eligibility each completed 5m boundary. Both use original 1m confirmation and original exits.','',
        '| Policy | Trades | Winning points | Losing points | Net NIFTY points | Winners | Losers | Flat | Drawdown |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for key,label in zip(POLICIES,LABELS):
        s=totals[key]
        lines.append(f"| {label} | {s['trades']} | {s['gross_winning_points']:+.2f} | {-s['gross_losing_points']:.2f} | {s['points']:+.2f} | {s['winners']} | {s['losers']} | {s['flat']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','| Date | Existing trades | Existing points | AND trades | AND points | Fresh trades | Fresh points | Fresh vs existing | Fresh vs AND |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    details=['# Signal-wise comparison','',warning,'',
        'Times IST. PASS means actual execution. BLOCKED means explicit lock veto; blocked rows have no realized P&L. A dash is no entry from that exact setup and is not proof of a direct rejection. Different setup times may lead to the same actual trade. Full setup prerequisites and minute checks are in sessions/*.json.','']
    all_trades=[]
    for day,variants in sorted(results.items()):
        daily=[stats.stats(variants[key]['trades']) for key in POLICIES]
        a,b,c=daily
        lines.append(f"| {day} | {a['trades']} | {a['points']:+.2f} | {b['trades']} | {b['points']:+.2f} | {c['trades']} | {c['points']:+.2f} | {c['points']-a['points']:+.2f} | {c['points']-b['points']:+.2f} |")
        decisions={key:[e for e in variants[key].get('policy_events',[]) if e['event']=='COMBINED_ENTRY_DECISION'] for key in POLICIES}
        identities={(t['direction'],t['signal_time']) for v in variants.values() for t in v['trades']}
        identities.update((e['direction'],e['setup_available']) for values in decisions.values() for e in values)
        details+=['','## '+day,'','| Direction | Setup available | Existing baseline | Previous AND | Fresh setups + AND | Previous AND decision | Fresh AND decision |',
            '|---|---|---|---|---|---|---|']
        for side,signal in sorted(identities,key=lambda x:(x[1],x[0])):
            cells=[base.cell([t for t in variants[key]['trades'] if (t['direction'],t['signal_time'])==(side,signal)]) for key in POLICIES]
            reasons=[]
            for key in POLICIES[1:]:
                matched=[e for e in decisions[key] if (e['direction'],e['setup_available'])==(side,signal)]
                reasons.append('; '.join(('PASS' if e['outcome']=='PASS' else 'BLOCKED: '+e['lock']+' lock; AND exception failed')+' at '+e['time'][11:16] for e in matched) or 'NO ENTRY from this setup')
            details.append('| '+side+' | '+signal[11:16]+' | '+' | '.join(cells+reasons)+' |')
        for key in POLICIES:
            all_trades.extend(dict(t,session_date=day,policy=key) for t in variants[key]['trades'])
    report=dict(model=MODEL,status='COMPLETE' if complete else 'INCOMPLETE',strategy_version=version,session_dates=days,
        coverage=coverage,comparisons=totals,provenance=provenance,warning=warning,orders_sent=False,observation_only=True)
    (output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
    (output/'daily-signal-comparison.md').write_text('\n'.join(details)+'\n')
    for filename,trades in (('trades.csv',all_trades),('losing-trades.csv',[t for t in all_trades if t['points']<0])):
        with (output/filename).open('w',newline='') as f:
            fields=['session_date','policy','direction','signal_time','entry_time','entry_price','exit_time','exit_price','points','exit_reason']
            writer=csv.DictWriter(f,fields,extrasaction='ignore');writer.writeheader();writer.writerows(trades)
    print('\n'.join(lines));print('SIGNAL TABLE:',output/'daily-signal-comparison.md');print('REPORT:',output/'report.json')


class Checks(unittest.TestCase):
    def test_counts_trading_sessions_not_calendar_days(self):
        self.assertEqual(select_sessions(['2026-10-08','2026-10-09','2026-10-12'],'2026-10-08','2026-10-13',3,'2026-10-13'),['2026-10-09','2026-10-12','2026-10-13'])
    def test_duplicate_extra_day_not_counted_twice(self):
        self.assertEqual(select_sessions(['2026-10-12'],'2026-10-12','2026-10-12',1,'2026-10-12'),['2026-10-12'])
    def test_short_coverage_rejected(self):
        with self.assertRaises(ValueError):select_sessions(['2026-10-12'],'2026-10-12','2026-10-12',30,'2026-10-12')
    def test_end_session_required(self):
        with self.assertRaises(ValueError):select_sessions(['2026-10-12'],'2026-10-12','2026-10-14',1,'2026-10-13')
    def test_zero_sessions_rejected(self):
        with self.assertRaises(ValueError):select_sessions([],'2026-10-01','2026-10-16',0,'2026-10-16')


if __name__=='__main__':main()
