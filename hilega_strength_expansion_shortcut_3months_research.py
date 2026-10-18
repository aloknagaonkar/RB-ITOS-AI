"""Research: valid setup + strength>=0.75 + expansion>=0.25; bypass persistence/entry lock.
Two variants: overall, or only while a WMA lock is active. No live changes/orders.
Run tests/replay on the Ubuntu VM, using the same frozen inputs as the prior 65 sessions.
"""
import csv
import inspect
import json
from pathlib import Path
import textwrap
from types import SimpleNamespace
import unittest

MODEL='STRENGTH_075_EXPANSION_025_NO_PERSISTENCE_LOCK_SHORTCUT_V1'
OUTPUT=Path('data/research/hilega-strength-expansion-shortcut-3months-20261016')
CONTROL=Path('data/research/hilega-and-fresh-setup-3months-20261016')
POLICIES=('EXISTING','PREVIOUS_AND','FRESH_AND','SHORTCUT_OVERALL','SHORTCUT_LOCK_ONLY')
LABELS=('Existing baseline','Previous AND','Fresh setups + AND','Shortcut overall','Shortcut during lock only')
WARNING=('Research only; gross NIFTY points, no option fills/costs. Shortcut requires an existing valid setup, '
    'directional WMA strength >=0.75, positive directional EMA3/WMA gap and expansion >=0.25 versus the previous ONE-MINUTE reading. '
    'It bypasses persistence and the WMA-lock/RSI-EMA entry veto only. Original post-setup timing, ten-minute expiry, '
    'direction watch, canonical cancellation, flat position, original dual exits and 14:55 cutoff remain. '
    'Both new variants use fresh eligible completed-5m setups. OVERALL applies shortcut at every eligible candidate check. '
    'LOCK_ONLY applies it while either BULLISH or BEARISH WMA lock is active, for either entry direction; '
    'with lock NONE it uses the original entry checks (including persistence and expansion >0). '
    'Locks continue to update normally and are not cleared by a bypass. No EMA10 exit or reversal override. '
    'Historical frozen reconstruction; Oct16 mixes recorded/API inputs. No live changes.')


def shortcut_candidate_gate(Base):
    source=textwrap.dedent(inspect.getsource(Base.evaluate))
    replacements={
        'expansion=gap is not None and prev_gap is not None and consecutive and gap>prev_gap':
            'expansion=gap is not None and prev_gap is not None and consecutive and (gap-prev_gap>=.25 if self._shortcut_active else gap>prev_gap)',
        "if not persistence:reasons.append('WAIT_LATER_PERSISTENCE')":
            "if not persistence and not self._shortcut_active:reasons.append('WAIT_LATER_PERSISTENCE')",
    }
    for old,new in replacements.items():
        if source.count(old)!=1:raise ValueError('SHORTCUT_GATE_SOURCE_DIFFERS:'+old)
        source=source.replace(old,new,1)
    namespace=dict(Base.evaluate.__globals__)
    exec(compile(source,'<isolated-strength-expansion-shortcut>','exec'),namespace)
    class Candidate(Base):
        _shortcut_active=False
        evaluate=namespace['evaluate']
    return Candidate


def shortcut_gate(engine,wm,lock,threshold,mode):
    if mode not in ('OVERALL','LOCK_ONLY'):raise ValueError('UNKNOWN_SHORTCUT_MODE')
    import hilega_existing_ema10_wma_combined_last10_research as combined
    Candidate=shortcut_candidate_gate(engine.WmaGapGate)
    proxy=SimpleNamespace(WmaGapGate=Candidate,direction=engine.direction)
    no_ema=SimpleNamespace(directional_exit_gate=lambda Base,unused:Base)
    Parent=combined.combined_gate(proxy,{},wm,lock,no_ema,threshold)
    class Shortcut(Parent):
        def evaluate(self,**kwargs):
            from datetime import timedelta
            at=kwargs['minute']+timedelta(minutes=1)
            self.update_lock(at)
            self._shortcut_active=mode=='OVERALL' or self.direction_lock.side in ('BULLISH','BEARISH')
            normal=self.direction_lock.permits
            # Bypass is consulted only after the candidate's mandatory checks pass.
            self.direction_lock.permits=lambda side: True if self._shortcut_active else normal(side)
            try:entries,checks=super().evaluate(**kwargs)
            finally:del self.direction_lock.permits
            for check in checks:
                check.update(shortcut_mode=mode,shortcut_applied=self._shortcut_active,
                    persistence_bypassed=self._shortcut_active,entry_lock_bypassed=self._shortcut_active,
                    expansion_minimum=.25 if self._shortcut_active else 0,
                    shortcut_lock_state=self.direction_lock.side)
                self.policy_events.append(dict(event='SHORTCUT_CANDIDATE_CHECK',time=check['decision_timestamp'],
                    direction=check['direction'],setup_available=check['signal_available_at'],
                    mode=mode,applied=self._shortcut_active,lock=self.direction_lock.side,
                    status=check['status'],reasons=check['reasons'],strength=check['directional_wma_strength'],
                    gap=check['current_gap'],expansion=check['gap_delta'],raw_persistence_pass=check['persistence_pass']))
            return entries,checks
    return Shortcut


class Checks(unittest.TestCase):
    def harness(self,mode='OVERALL',wma=30,side='BULLISH',hour='10:00'):
        from datetime import datetime
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        import hilega_post_entry_wma_lock_today_research as lock
        import hilega_wma_threshold_only_oct14_research as threshold
        at=datetime.fromisoformat('2026-10-05T'+hour+':00+05:30')
        wm={at:dict(wma21=wma,previous_wma21=wma,available_at=at.isoformat(),rsi9=20,ema3=20)}
        from datetime import timedelta
        for offset in (5,10,15):
            boundary=at+timedelta(minutes=offset)
            wm[boundary]=dict(wma21=wma,previous_wma21=wma,available_at=boundary.isoformat(),rsi9=20,ema3=20)
        Gate=shortcut_gate(engine,wm,lock,threshold,mode)
        g=Gate(opposite_switch=True);g.update_lock(at)
        event=engine.StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21' if side=='BULLISH' else 'ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={})
        g.signal(event,at)
        return g,at,engine

    def evaluate(self,g,at,offset,side='BULLISH',strength=.75,gap=1):
        from datetime import timedelta
        sign=1 if side=='BULLISH' else -1
        wma=50+sign*strength
        current=SimpleNamespace(ready=True,wma21_rsi=wma,ema3_rsi=wma+sign*gap,rsi9=wma+sign*(gap+1))
        return g.evaluate(minute=at+timedelta(minutes=offset),current=current,
            reference=SimpleNamespace(ready=True,wma21_rsi=50),price=100)

    def seed(self,g,at,side='BULLISH'):
        return self.evaluate(g,at,0,side,strength=.25,gap=.75)

    def test_exact_thresholds_bypass_persistence_and_opposite_lock(self):
        g,at,_=self.harness();self.seed(g,at)
        entries,c=self.evaluate(g,at,1)
        self.assertEqual(len(entries),1);self.assertFalse(c[0]['persistence_pass'])
        self.assertTrue(c[0]['shortcut_applied']);self.assertEqual(g.direction_lock.side,'BEARISH')

    def test_bearish_shortcut_is_symmetric(self):
        g,at,_=self.harness(wma=70,side='BEARISH');self.seed(g,at,'BEARISH')
        entries,c=self.evaluate(g,at,1,'BEARISH')
        self.assertEqual(len(entries),1);self.assertEqual(g.owner,'BEARISH')
        self.assertEqual(g.direction_lock.side,'BULLISH')

    def test_below_expansion_waits_without_consuming_candidate(self):
        g,at,_=self.harness();self.seed(g,at)
        entries,c=self.evaluate(g,at,1,gap=.99)
        self.assertFalse(entries);self.assertIn('BULLISH',g.pending)
        self.assertFalse(c[0]['gap_expanding_pass'])
        entries,c=self.evaluate(g,at,2,gap=1.25)
        self.assertEqual(len(entries),1)

    def test_strength_below_minimum_cannot_enter(self):
        g,at,_=self.harness();self.seed(g,at)
        entries,c=self.evaluate(g,at,1,strength=.5)
        self.assertFalse(entries);self.assertIn('WMA_THRESHOLD_NOT_MET',c[0]['reasons'])

    def test_lock_only_retains_persistence_when_lock_none(self):
        g,at,_=self.harness(mode='LOCK_ONLY',wma=50);self.seed(g,at)
        entries,c=self.evaluate(g,at,1)
        self.assertFalse(entries);self.assertFalse(c[0]['shortcut_applied'])
        self.assertIn('WAIT_LATER_PERSISTENCE',c[0]['reasons'])

    def test_lock_only_applies_while_lock_active(self):
        g,at,_=self.harness(mode='LOCK_ONLY');self.seed(g,at)
        entries,c=self.evaluate(g,at,1)
        self.assertEqual(len(entries),1);self.assertTrue(c[0]['shortcut_applied'])

    def test_overall_applies_even_without_lock(self):
        g,at,_=self.harness(wma=50);self.seed(g,at)
        entries,c=self.evaluate(g,at,1)
        self.assertEqual(len(entries),1);self.assertTrue(c[0]['shortcut_applied'])

    def test_original_post_setup_timing_is_preserved(self):
        g,at,_=self.harness()
        self.evaluate(g,at,-2,strength=.25,gap=.75)
        entries,c=self.evaluate(g,at,-1,strength=.75,gap=1)
        self.assertFalse(entries)
        self.assertIn('WAIT_FIRST_POST_SIGNAL_MINUTE',c[0]['reasons'])

    def test_setup_is_still_required(self):
        g,at,_=self.harness();g.pending.clear();self.seed(g,at)
        entries,_=self.evaluate(g,at,1)
        self.assertFalse(entries)

    def test_negative_gap_still_blocks(self):
        g,at,_=self.harness();self.evaluate(g,at,0,strength=.25,gap=-2)
        entries,c=self.evaluate(g,at,1,gap=-1)
        self.assertFalse(entries);self.assertIn('GAP_NOT_POSITIVE',c[0]['reasons'])

    def test_expired_candidate_not_resurrected(self):
        g,at,_=self.harness();self.seed(g,at)
        entries,c=self.evaluate(g,at,10,gap=2)
        self.assertFalse(entries);self.assertNotIn('BULLISH',g.pending)
        self.assertIn('WINDOW_EXPIRED',c[0]['reasons'])

    def test_cutoff_still_blocks(self):
        g,at,_=self.harness(hour='14:50');self.evaluate(g,at,3,strength=.25,gap=.75)
        entries,c=self.evaluate(g,at,4)
        self.assertFalse(entries);self.assertIn('SESSION_CUTOFF',c[0]['reasons'])

    def test_original_gate_source_unchanged(self):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        before=inspect.getsource(engine.WmaGapGate.evaluate)
        shortcut_candidate_gate(engine.WmaGapGate)
        self.assertEqual(inspect.getsource(engine.WmaGapGate.evaluate),before)


def write_reports(output,days,results,coverage,provenance,version,unused,stats):
    import hilega_existing_ema10_wma_combined_last10_research as base
    prior=json.loads((CONTROL/'report.json').read_text())
    if (prior['status']!='COMPLETE' or prior['session_dates']!=days or
        prior['model']!='AND_FRESH_SETUP_THIRTY_SESSION_COMPARISON_V1' or prior['strategy_version']!=version):
        raise ValueError('COMPLETE_IDENTICAL_THREE_MONTH_CONTROL_REQUIRED')
    for day,variants in results.items():
        saved=json.loads((CONTROL/'sessions'/(day+'.json')).read_text())
        if provenance[day]['input_sha256']!=prior['provenance'][day]['input_sha256']:
            raise ValueError('THREE_MONTH_CONTROL_INPUT_MISMATCH:'+day)
        for key in POLICIES[:3]:
            if stats.signature(saved[key]['trades'])!=stats.signature(variants[key]['trades']):
                raise ValueError('THREE_MONTH_CONTROL_POLICY_PARITY_FAILED:'+day+':'+key)
        provenance[day]['three_month_control_policy_parity']='PASS'
        for key in POLICIES[3:]:
            for t in variants[key]['trades']:
                c=t['entry_checks']
                if c['shortcut_applied'] and (c['directional_wma_strength']<.75 or c['gap_delta']<.25 or c['current_gap']<=0):
                    raise ValueError('SHORTCUT_ENTRY_THRESHOLD_FAILED')
            if any(e['event'].startswith('EMA_EXIT') or e['event']=='CONFIRMED_OPPOSITE_EXIT_OVERRIDE' for e in variants[key]['policy_events']):
                raise ValueError('DISABLED_FEATURE_USED')
    complete=len(results)==len(days)
    totals={k:stats.stats([t for day in sorted(results) for t in results[day][k]['trades']]) for k in POLICIES}
    lines=['# Strength/expansion shortcut: overall versus during WMA lock','',WARNING,'',
        f"Status: {'COMPLETE' if complete else 'INCOMPLETE'}; coverage {len(results)}/{len(days)}.",'',
        '| Policy | Trades | Winning points | Losing points | Net NIFTY points | Winners | Losers | Flat | Drawdown |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for key,label in zip(POLICIES,LABELS):
        s=totals[key]
        lines.append(f"| {label} | {s['trades']} | {s['gross_winning_points']:+.2f} | {-s['gross_losing_points']:.2f} | {s['points']:+.2f} | {s['winners']} | {s['losers']} | {s['flat']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','| Date | Existing | Previous AND | Fresh AND | Shortcut overall | Shortcut during lock |','|---|---:|---:|---:|---:|---:|']
    details=['# Signal-wise shortcut comparison','',WARNING,'',
        'Times IST. Cells show executed entry–exit and NIFTY points. Dash means no execution from that setup; not automatic proof of a veto. Full minute checks, reasons and bypass flags remain in sessions/*.json.','']
    trades=[];checks=[]
    for day,r in sorted(results.items()):
        lines.append('| '+day+' | '+' | '.join(f"{stats.stats(r[k]['trades'])['points']:+.2f}" for k in POLICIES)+' |')
        identities={(t['direction'],t['signal_time']) for k in POLICIES for t in r[k]['trades']}
        for k in POLICIES:
            identities.update((e['direction'],e['setup_available']) for e in r[k].get('policy_events',[]) if e['event']=='COMBINED_ENTRY_DECISION')
            trades.extend(dict(t,session_date=day,policy=k) for t in r[k]['trades'])
        details+=['','## '+day,'','| Direction | Setup | '+' | '.join(LABELS)+' |','|---|---|---|---|---|---|---|']
        for side,signal in sorted(identities,key=lambda x:(x[1],x[0])):
            cells=[base.cell([t for t in r[k]['trades'] if (t['direction'],t['signal_time'])==(side,signal)]) for k in POLICIES]
            details.append('| '+side+' | '+signal[11:16]+' | '+' | '.join(cells)+' |')
        for k in POLICIES[3:]:
            checks.extend(dict(e,session_date=day,policy=k) for e in r[k]['policy_events'] if e['event']=='SHORTCUT_CANDIDATE_CHECK')
    report=dict(model=MODEL,status='COMPLETE' if complete else 'INCOMPLETE',strategy_version=version,session_dates=days,
        coverage=coverage,provenance=provenance,comparisons=totals,warning=WARNING,orders_sent=False,observation_only=True)
    (output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
    (output/'daily-signal-comparison.md').write_text('\n'.join(details)+'\n')
    for filename,rows,fields in (
        ('trades.csv',trades,['session_date','policy','direction','signal_time','entry_time','entry_price','exit_time','exit_price','points','exit_reason']),
        ('shortcut-checks.csv',checks,['session_date','policy','time','direction','setup_available','mode','applied','lock','status','strength','gap','expansion','raw_persistence_pass','reasons'])):
        with (output/filename).open('w',newline='') as f:
            writer=csv.DictWriter(f,fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    print('\n'.join(lines));print('SIGNAL TABLE:',output/'daily-signal-comparison.md');print('REPORT:',output/'report.json')


def main():
    import hilega_and_fresh_setup_30_sessions_research as batch
    source=inspect.getsource(batch.main)
    replacements={
        "ap.add_argument('--sessions',type=int,default=30)":"ap.add_argument('--sessions',type=int,default=65)",
        "Path('data/research/hilega-and-fresh-setup-30sessions-20261016')":'OUTPUT',
        '(Checks,fresh.Checks,previous.Checks,exception.Checks,threshold.Checks)':
            '(Checks,batch.Checks,fresh.Checks,previous.Checks,exception.Checks,threshold.Checks)',
        'variants=dict(EXISTING=baseline,PREVIOUS_AND=old,FRESH_AND=new)':
            "variants=dict(EXISTING=baseline,PREVIOUS_AND=old,FRESH_AND=new)\n            for key,mode in (('SHORTCUT_OVERALL','OVERALL'),('SHORTCUT_LOCK_ONLY','LOCK_ONLY')):\n                SG=shortcut_gate(engine,wm,lock,threshold,mode)\n                variants[key]=p.simulate(SimpleNamespace(WmaGapGate=SG,replay=fresh.fresh_replay(engine)),day,raw,warm,asof,'CURRENT')\n                stats.signature(variants[key]['trades'])",
    }
    for old,new in replacements.items():
        if source.count(old)!=1:raise ValueError('BATCH_SOURCE_DIFFERS:'+old)
        source=source.replace(old,new,1)
    namespace=dict(vars(batch),MODEL=MODEL,OUTPUT=OUTPUT,Checks=Checks,batch=batch,
        shortcut_gate=shortcut_gate,write_reports=write_reports)
    exec(compile(source,'<shortcut-three-month-runner>','exec'),namespace)
    namespace['main']()


if __name__=='__main__':main()
