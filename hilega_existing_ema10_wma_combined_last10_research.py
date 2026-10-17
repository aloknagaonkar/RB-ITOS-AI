"""One research strategy: ORIGINAL 1m entries + directional price EMA10 exit + WMA lock.
Threshold-only WMA lock from market open, no exceptions, no retained policy.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

MODEL='EXISTING_1M_DIRECTIONAL_EMA10_THRESHOLD_WMA_LOCK_V1'

def combined_gate(engine,frames,wm,lock,corrected,threshold):
    Ema=corrected.directional_exit_gate(engine.WmaGapGate,frames)
    Parent=threshold.lock_adapter(lock).lock_gate(Ema,engine.direction,wm)
    class Combined(Parent):
        def evaluate(self,**kwargs):
            entries,checks=super().evaluate(**kwargs)
            for check in checks:
                if check.get('status') in ('ENTRY','POST_ENTRY_WMA_LOCK_BLOCKED'):
                    self.policy_events.append(dict(event='COMBINED_ENTRY_DECISION',time=check['decision_timestamp'],
                        direction=check['direction'],setup_available=check['signal_available_at'],
                        outcome='PASS' if check['status']=='ENTRY' else 'BLOCKED_WMA_LOCK',
                        lock=check['post_entry_wma_lock']['side'],details=check))
            return entries,checks
    return Combined

def cell(trades):
    return '; '.join(f"{t['entry_time'][11:16]}–{t['exit_time'][11:16]} · {float(t['points']):+.2f}" for t in trades) or '—'

class Checks(unittest.TestCase):
    def harness(self,wma=60):
        from datetime import datetime,timedelta
        import hilega_ema10_directional_oct14_research as corrected
        import hilega_wma_threshold_only_oct14_research as threshold
        import hilega_post_entry_wma_lock_today_research as lock
        at=datetime.fromisoformat('2026-10-14T11:00:00+05:30')
        class Base:
            def __init__(self):self.owner='NONE';self.active=None;self.pending={'BEARISH':{}}
            def evaluate(self,**kwargs):
                self.owner='BEARISH';self.active=True;self.pending.clear()
                return ['BEARISH'],[dict(status='ENTRY',reasons=[],direction='BEARISH',
                    signal_available_at='2026-10-14T10:55:00+05:30',decision_timestamp=at.isoformat())]
            def close(self,event,at,price):self.owner='NONE';self.active=None;return event
        engine=SimpleNamespace(WmaGapGate=Base,direction=lambda e:e)
        wm={at:dict(wma21=wma,previous_wma21=wma+1,available_at=at.isoformat())}
        Gate=combined_gate(engine,{at:dict(close=101,ema10=100,candle_label='10:55')},wm,lock,corrected,threshold)
        return Gate(),at,timedelta
    def test_lock_veto_leaves_flat_and_consumes_candidate(self):
        g,at,delta=self.harness();entries,_=g.evaluate(minute=at-delta(minutes=1))
        self.assertFalse(entries);self.assertEqual(g.owner,'NONE');self.assertIsNone(g.active)
        self.assertFalse(g.pending);self.assertEqual(g.policy_events[-1]['outcome'],'BLOCKED_WMA_LOCK')
    def test_middle_band_allows_confirmed_entry(self):
        g,at,delta=self.harness(50);entries,_=g.evaluate(minute=at-delta(minutes=1))
        self.assertEqual(entries,['BEARISH']);self.assertEqual(g.policy_events[-1]['outcome'],'PASS')
    def test_existing_gate_not_retained(self):
        # Composition must use the original gate and replay, without a lifecycle wrapper.
        import inspect
        source=inspect.getsource(combined_gate)
        self.assertIn('engine.WmaGapGate',source)
        self.assertNotIn('retained_gate',source)
        self.assertNotIn('exception_lock_gate',source)
    def test_empty_cell(self):self.assertEqual(cell([]),'—')
    def test_signed_points(self):
        self.assertEqual(cell([dict(entry_time='2026-10-14T09:25:00+05:30',exit_time='2026-10-14T10:40:00+05:30',points=-22.35)]),'09:25–10:40 · -22.35')

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--test',action='store_true')
    ap.add_argument('--previous-root',type=Path,default=Path('data/research/hilega-retained-policy-last10-20261016'))
    ap.add_argument('--research-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    ap.add_argument('--today-input',type=Path,default=Path('data/research/hilega-pending-previous10-plus-today-20261016-v3/today-recorded-overrides.json'))
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-existing-ema10-wma-combined-last10-20261016'))
    a=ap.parse_args()
    import hilega_ema10_directional_oct14_research as corrected
    import hilega_wma_threshold_only_oct14_research as threshold
    if a.test:
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (Checks,corrected.Checks,threshold.Checks))
        r=unittest.TextTestRunner(verbosity=2).run(suite);raise SystemExit(0 if r.wasSuccessful() else 1)
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    import hilega_pending_confirmation_research as p
    import hilega_pending_previous10_research as stats
    import hilega_vwap_confirmed36_research as support
    import hilega_ema10_exit_day_research as ema
    import hilega_post_entry_wma_lock_today_research as lock
    from hilega_vwap_wait_alignment_research import source_data
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    if engine.RULES['version']!=p.VERSION:raise ValueError('ENGINE_VERSION_MISMATCH')
    prior=json.loads((a.previous_root/'report.json').read_text())
    if prior['status']!='COMPLETE' or prior['strategy_version']!=p.VERSION:raise ValueError('COMPLETE_MATCHING_BASELINE_REQUIRED')
    days=prior['session_dates']
    if len(days)!=10 or days[-1]!='2026-10-16':raise ValueError('EXPECTED_SAME_TEN_SESSIONS_ENDING_OCT16')
    parent=json.loads((a.research_root/'3-month/report.json').read_text())
    if parent['strategy_version']!=p.VERSION:raise ValueError('SOURCE_VERSION_MISMATCH')
    sessions,grouped=source_data(a.research_root,parent,support)
    extra=json.loads(a.today_input.read_text())
    results={};coverage=[];provenance={};a.output.mkdir(parents=True,exist_ok=True)
    for day in days:
        row=dict(session_date=day,status='INCOMPLETE',issues=[])
        try:
            asof=p.dt(day+'T14:55:00+05:30')
            if day==extra['session_date']:raw,warm,_=p.inputs(engine,day,a.today_input,False,a.output)
            else:raw=grouped[day];warm=[(d,grouped[d]) for d in sessions if d<day and grouped.get(d)][-30:]
            if len(warm)<20:raise ValueError('INSUFFICIENT_WARMUP')
            raw=[r for r in raw if p.dt(r['timestamp'])<=asof]
            digest=hashlib.sha256(json.dumps([raw,warm],sort_keys=True,default=str).encode()).hexdigest()
            if digest!=prior['provenance'][day]['raw_and_warm_sha256']:raise ValueError('BASELINE_INPUT_HASH_MISMATCH')
            baseline=p.simulate(engine,day,raw,warm,asof,'CURRENT')
            saved=json.loads((a.previous_root/'sessions'/day/'ORIGINAL_CURRENT_1M.json').read_text())
            parity=stats.frozen_parity(saved,baseline)
            if parity['status']!='PASS':raise ValueError('BASELINE_PARITY_FAILED:'+json.dumps(parity))
            wm=lock.completed_frames(baseline,p.dt);first=min(wm)
            audit=next(r for r in baseline['audit'] if p.dt(r['checkpoint'])==first and r.get('completed_5m_indicators'))
            delta=audit['five_minute_changes']['wma21']
            if delta is None:raise ValueError('OPENING_REFERENCE_REQUIRED')
            wm[first]['previous_wma21']=wm[first]['wma21']-delta
            frames=ema.ema_frames(engine,day,raw,warm,p.dt)
            Gate=combined_gate(engine,frames,wm,lock,corrected,threshold)
            changed=p.simulate(SimpleNamespace(WmaGapGate=Gate,replay=engine.replay),day,raw,warm,asof,'CURRENT')
            for value in (baseline,changed):stats.signature(value['trades'])
            results[day]=dict(EXISTING=baseline,COMBINED=changed)
            provenance[day]=dict(input_sha256=digest,warmup_sessions=len(warm),baseline_parity=parity)
            dest=a.output/'sessions'/(day+'.json');dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_text(json.dumps(results[day],indent=2,default=str)+'\n')
            row.update(status='COMPLETE',parity=parity)
        except Exception as exc:row['issues'].append(type(exc).__name__+': '+str(exc))
        coverage.append(row);print(json.dumps(row),flush=True)
    warning=('Research only: gross NIFTY points, no option fills/costs or live changes. '
        'COMBINED uses EXISTING 1m confirmation, persistence, ten-minute expiry, direction watch and canonical cancellation. '
        'Existing dual exit AND bullish close<price EMA10 / bearish close>price EMA10, same completed 5m boundary; no latch; 14:55 override. '
        'WMA lock from open: >55 bullish, <45 bearish, no slope requirement. Strict reverse cross releases to NONE; no same-boundary opposite lock. '
        'WMA veto consumes that confirmed candidate under this policy; no unlimited retention, no RSI/EMA exception. '
        'Historical inputs are frozen research; Oct16 uses mixed recorded/API inputs. Parity reproduces the saved baseline, not every historical live minute.')
    summary={k:stats.stats([t for day in sorted(results) for t in results[day][k]['trades']]) for k in ('EXISTING','COMBINED')}
    lines=['# Existing strategy + corrected EMA10 + threshold WMA lock — ten sessions','',warning,'',
        '| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for key,s in summary.items():lines.append(f"| {key} | {s['trades']} | {s['points']:+.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','| Date | Existing trades | Existing points | Combined trades | Combined points | Change | Lock vetoes |','|---|---:|---:|---:|---:|---:|---:|']
    details=['# Daily signal comparison','',warning,'','PASS means an executed combined entry. BLOCKED means an explicit WMA veto. NO ENTRY means no executed combined entry and no matched explicit veto; position/lifecycle may differ. Blocked rows have no actual P&L. Existing reference points are not automatically loss points avoided.','']
    for day,r in sorted(results.items()):
        before=stats.stats(r['EXISTING']['trades']);after=stats.stats(r['COMBINED']['trades'])
        decisions=[e for e in r['COMBINED']['policy_events'] if e['event']=='COMBINED_ENTRY_DECISION']
        vetoes=[e for e in decisions if e['outcome']=='BLOCKED_WMA_LOCK']
        lines.append(f"| {day} | {before['trades']} | {before['points']:+.2f} | {after['trades']} | {after['points']:+.2f} | {after['points']-before['points']:+.2f} | {len(vetoes)} |")
        identities={(t['direction'],t['signal_time']) for value in r.values() for t in value['trades']}
        identities.update((e['direction'],e['setup_available']) for e in decisions)
        details+=['','## '+day,'','| Direction | Setup available | Existing strategy | Combined strategy | Decision |','|---|---|---|---|---|']
        for side,signal in sorted(identities,key=lambda x:(x[1],x[0])):
            old=[t for t in r['EXISTING']['trades'] if (t['direction'],t['signal_time'])==(side,signal)]
            new=[t for t in r['COMBINED']['trades'] if (t['direction'],t['signal_time'])==(side,signal)]
            blocked=[e for e in vetoes if (e['direction'],e['setup_available'])==(side,signal)]
            status='PASS' if new else ('BLOCKED WMA: '+', '.join(e['time'][11:16] for e in blocked) if blocked else 'NO ENTRY')
            details.append('| '+side+' | '+signal[11:16]+' | '+cell(old)+' | '+cell(new)+' | '+status+' |')
        details+=['','### EMA10 exit checks','','| Time | Direction | Close | EMA10 | Action |','|---|---|---:|---:|---|']
        for e in r['COMBINED']['policy_events']:
            if e['event']=='EMA_EXIT_CHECK':details.append(f"| {e['time'][11:16]} | {e['direction']} | {e['close']:.2f} | {e['ema10']:.3f} | {'EXIT' if e['ema_pass'] else 'HOLD'} |")
    complete=len(results)==len(days)
    report=dict(status='COMPLETE' if complete else 'INCOMPLETE',model=MODEL,session_dates=days,coverage=coverage,
        comparisons=summary,provenance=provenance,warning=warning,orders_sent=False,observation_only=True)
    (a.output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    (a.output/'summary.md').write_text('\n'.join(lines)+'\n')
    (a.output/'daily-signal-comparison.md').write_text('\n'.join(details)+'\n')
    with (a.output/'trades.csv').open('w',newline='') as f:
        fields=['session_date','policy','direction','signal_time','entry_time','entry_price','exit_time','exit_price','points','exit_reason']
        writer=csv.DictWriter(f,fields,extrasaction='ignore');writer.writeheader()
        for day,r in sorted(results.items()):
            for key,value in r.items():
                for t in value['trades']:writer.writerow(dict(t,session_date=day,policy=key))
    print('\n'.join(lines));print('\n'.join(details));print('REPORT:',a.output/'report.json')
    raise SystemExit(0 if complete else 2)

if __name__=='__main__':main()
