"""Sequential confirmation research for today. No API/order/service operations.

Stage 1: original one-minute strength, persistence and gap checks confirm.
Stage 2: a strictly later completed 5m boundary must support the direction by
RSI/EMA/WMA ordering and directional WMA slope. Original minute conditions must
also pass again at entry. No two additional 5m persistence readings are required.
"""
import argparse
import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import textwrap
from types import SimpleNamespace
import unittest
from datetime import timedelta

def support_check(side,current,reference):
    sign=1 if side=='BULLISH' else -1
    ready=bool(current and current.ready and reference and reference.ready)
    alignment=bool(ready and sign*(current.rsi9-current.ema3_rsi)>0 and sign*(current.ema3_rsi-current.wma21_rsi)>0)
    slope=sign*(current.wma21_rsi-reference.wma21_rsi) if ready else None
    return dict(passed=bool(alignment and slope is not None and slope>0),alignment_pass=alignment,
                directional_wma_slope=slope,slope_pass=slope is not None and slope>0,
                rsi9=current.rsi9 if current else None,ema3=current.ema3_rsi if current else None,
                wma21=current.wma21_rsi if current else None,previous_completed_wma21=reference.wma21_rsi if reference else None)

def sequential_gate(Base,continued=False):
    source=textwrap.dedent(inspect.getsource(Base.evaluate))
    if continued:
        for old,new in (('elapsed=0<=age<10 or same_boundary','elapsed=age>=0 or same_boundary'),
                        ('elif age>=10 or self.locked:del self.pending[side]','elif self.locked:del self.pending[side]')):
            if source.count(old)!=1:raise ValueError('MINUTE_GATE_SOURCE_MISMATCH:'+old)
            source=source.replace(old,new,1)
    namespace=dict(Base.evaluate.__globals__);exec(compile(source,'<research-minute-confirmation>','exec'),namespace)
    evaluate_minute=namespace['evaluate']
    class Sequential(Base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);self.minute_confirmed={};self.policy_events=[]
        def evaluate(self,*,minute,current,reference,price,exit_boundary=False):
            at=minute+timedelta(minutes=1)
            self.can_signal('BULLISH',at)
            # Canonical cancellation / manual clearing of pending contexts is
            # honored. A latch never resurrects a removed or replaced setup.
            for side,latch in list(self.minute_confirmed.items()):
                pending=self.pending.get(side)
                if not pending or pending['available']!=latch['setup_available']:
                    self.policy_events.append(dict(time=at.isoformat(),event='LATCH_CLEARED_SETUP_REMOVED',direction=side))
                    del self.minute_confirmed[side]
            if self.owner!='NONE':
                return evaluate_minute(self,minute=minute,current=current,reference=reference,price=price,exit_boundary=exit_boundary)
            checks=[];eligible=[]
            for side,pending in list(self.pending.items()):
                # Independent minute probes: temporary acceptance cannot block
                # the other direction or become a real position before stage 2.
                probe=Base(opposite_switch=False);probe.previous=self.previous;probe.locked=self.locked
                probe.pending={side:dict(pending)}
                accepted,frames=evaluate_minute(probe,minute=minute,current=current,reference=reference,price=price,exit_boundary=exit_boundary)
                if len(frames)!=1:raise ValueError('ONE_MINUTE_CHECK_PER_CONTEXT_REQUIRED')
                frame=frames[0];minute_pass=bool(accepted)
                if side in probe.pending:self.pending[side]=probe.pending[side]
                elif accepted:
                    # Preserve the actual pending setup until final acceptance.
                    self.pending[side]=dict(pending)
                else:
                    self.pending.pop(side,None);self.minute_confirmed.pop(side,None)
                if accepted and side not in self.minute_confirmed:
                    self.minute_confirmed[side]=dict(first_confirmed_at=at,setup_available=pending['available'])
                    self.policy_events.append(dict(time=at.isoformat(),event='MINUTE_CONFIRMED_WAITING_FOR_5M',direction=side,signal_available_at=pending['available'].isoformat()))
                latch=self.minute_confirmed.get(side);five=support_check(side,current,reference) if at.minute%5==0 else None
                final=bool(minute_pass and latch and at>latch['first_confirmed_at'] and five and five['passed'])
                frame.update(minute_confirmation_pass=minute_pass,
                    first_minute_confirmed_at=latch['first_confirmed_at'].isoformat() if latch else None,
                    five_minute_support=five,waiting_for_five_minute_support=bool(latch and not final),
                    sequential_confirmation=True,continued_wait=continued)
                if latch and not final:
                    reasons=list(frame['reasons'])
                    if at.minute%5 or at<=latch['first_confirmed_at']:reasons.append('WAIT_NEXT_COMPLETED_5M_AFTER_MINUTE_CONFIRMATION')
                    elif not five['passed']:reasons.append('FIVE_MINUTE_SUPPORT_FAILED')
                    if not minute_pass:reasons.append('CURRENT_MINUTE_RECHECK_FAILED')
                    frame.update(status='WAIT_5M_SUPPORT',reasons=reasons)
                if final:
                    frame.update(status='ENTRY',reasons=[])
                    event=accepted[0]
                    self.policy_events.append(dict(time=at.isoformat(),event='SEQUENTIAL_ENTRY_ELIGIBLE',direction=side,
                        first_minute_confirmed_at=latch['first_confirmed_at'].isoformat(),support=five))
                    eligible.append((side,event))
                checks.append(frame)
            change=current.wma21_rsi-reference.wma21_rsi if current.ready and reference and reference.ready else None
            self.previous=dict(minute=minute,snapshot=current,wma_change=change)
            if len(eligible)>1:raise ValueError('AMBIGUOUS_SIMULTANEOUS_CONFIRMED_ENTRY')
            if not eligible:return [],checks
            side,event=eligible[0]
            self.owner=side;self.active=dict(time=at,price=price)
            self.pending.clear();self.minute_confirmed.clear();self.watch_side=None;self.watch_at=None
            return [event],checks
    return Sequential

class Checks(unittest.TestCase):
    def harness(self,continued=False):
        import hilega_pending_confirmation_research as p
        from market_lab import hilega_v2_alignment_replay_v1 as e
        gate=sequential_gate(e.WmaGapGate,continued)(opposite_switch=False)
        available=p.dt('2026-10-16T14:20:00+05:30')
        event=e.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',available-timedelta(minutes=5),None,'IDLE','ARMED',details={})
        gate.signal(event,available)
        def tick(clock,gap):
            at=p.dt('2026-10-16T'+clock+':00+05:30')
            snapshot=SimpleNamespace(ready=True,rsi9=48-gap,ema3_rsi=49-gap,wma21_rsi=49)
            reference=SimpleNamespace(ready=True,wma21_rsi=50)
            return gate.evaluate(minute=at-timedelta(minutes=1),current=snapshot,reference=reference,price=100)
        return gate,tick
    def prime(self,tick):tick('14:20',1);tick('14:21',2);return tick('14:22',3)
    def test_minute_pass_does_not_enter(self):
        gate,tick=self.harness();entries,checks=self.prime(tick)
        self.assertFalse(entries);self.assertEqual(gate.owner,'NONE');self.assertIn('BEARISH',gate.minute_confirmed)
        self.assertTrue(checks[0]['minute_confirmation_pass'])
    def test_supported_boundary_enters(self):
        gate,tick=self.harness();self.prime(tick);tick('14:23',4);tick('14:24',5)
        entries,checks=tick('14:25',6)
        self.assertEqual(len(entries),1);self.assertEqual(gate.owner,'BEARISH');self.assertTrue(checks[0]['five_minute_support']['passed'])
    def test_stale_minute_pass_cannot_authorize_entry(self):
        gate,tick=self.harness();self.prime(tick);tick('14:23',4);tick('14:24',5)
        entries,checks=tick('14:25',4)
        self.assertFalse(entries);self.assertIn('CURRENT_MINUTE_RECHECK_FAILED',checks[0]['reasons'])
    def test_removed_setup_clears_latch(self):
        gate,tick=self.harness();self.prime(tick);gate.pending.clear();tick('14:23',4)
        self.assertFalse(gate.minute_confirmed);self.assertEqual(gate.owner,'NONE')
    def test_no_second_five_minute_persistence_required(self):
        gate,tick=self.harness();self.prime(tick);tick('14:23',4);tick('14:24',5)
        self.assertTrue(tick('14:25',6)[0])
    def test_alignment_and_slope_both_required(self):
        snap=SimpleNamespace(ready=True,rsi9=40,ema3_rsi=45,wma21_rsi=49)
        self.assertTrue(support_check('BEARISH',snap,SimpleNamespace(ready=True,wma21_rsi=50))['passed'])
        self.assertFalse(support_check('BEARISH',snap,SimpleNamespace(ready=True,wma21_rsi=48))['passed'])
        self.assertFalse(support_check('BULLISH',snap,SimpleNamespace(ready=True,wma21_rsi=48))['passed'])
    def test_continued_latch_survives_ten_minutes(self):
        gate,tick=self.harness(True);self.prime(tick)
        tick('14:31',4);self.assertIn('BEARISH',gate.pending);self.assertIn('BEARISH',gate.minute_confirmed)
    def test_cutoff_cannot_enter(self):
        gate,tick=self.harness(True);self.prime(tick)
        entries,checks=tick('14:55',6)
        self.assertFalse(entries);self.assertIn('SESSION_CUTOFF',checks[0]['reasons'])

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--date',default='2026-10-16')
    ap.add_argument('--input',type=Path,default=Path('data/research/hilega-pending-previous10-plus-today-20261016-v3/today-recorded-overrides.json'))
    ap.add_argument('--audit',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-minute-then-five-support-20261016'))
    ap.add_argument('--test',action='store_true');a=ap.parse_args()
    if a.test:
        r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks));raise SystemExit(0 if r.wasSuccessful() else 1)
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    import hilega_pending_confirmation_research as p
    import hilega_pending_previous10_research as batch
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    if engine.RULES['version']!=p.VERSION:raise ValueError('ENGINE_VERSION_MISMATCH')
    asof=p.dt(a.date+'T14:55:00+05:30')
    if asof>p.datetime.now(p.IST):raise ValueError('SESSION_NOT_COMPLETE')
    a.output.mkdir(parents=True,exist_ok=True);raw,warm,hashes=p.inputs(engine,a.date,a.input,False,a.output)
    raw=[r for r in raw if p.dt(r['timestamp'])<=asof]
    specs=(('CURRENT_MINUTE',False,False,False),('MINUTE_THEN_5M_EXISTING_10M',True,False,False),
           ('MINUTE_THEN_5M_CONTINUED_CONFIRMED_OPPOSITE',True,True,True))
    results={}
    for name,sequential,continued,confirmed in specs:
        Gate=sequential_gate(engine.WmaGapGate,continued) if sequential else engine.WmaGapGate
        proxy=SimpleNamespace(WmaGapGate=Gate,replay=engine.replay)
        r=p.simulate(proxy,a.date,raw,warm,asof,'CONFIRMED_OPPOSITE_ONLY' if confirmed else 'CURRENT')
        r['research_variant']=name;batch.signature(r['trades'])
        if sequential:
            for trade in r['trades']:
                check=trade['entry_checks'];entry=p.dt(trade['entry_time'])
                if entry.minute%5 or not check['minute_confirmation_pass'] or not check['five_minute_support']['passed'] or p.dt(check['first_minute_confirmed_at'])>=entry:
                    raise ValueError('SEQUENTIAL_ENTRY_INVARIANT_FAILED')
        results[name]=r;(a.output/(name+'.json')).write_text(json.dumps(r,indent=2,default=str)+'\n')
    parity=p.audit_parity(a.audit,a.date,asof,results['CURRENT_MINUTE'])
    source=json.loads(a.input.read_text());cutoffs=(source.get('provenance') or {}).get('cutoff_payloads')
    if not cutoffs:parity['issues'].append('RECORDED_CUTOFF_PROVENANCE_REQUIRED')
    else:parity['issues'].extend(batch.cutoff_parity(results['CURRENT_MINUTE'],cutoffs))
    if parity['issues']:parity['status']='MISMATCH'
    report=dict(status='COMPLETE' if parity['status']=='PASS' else 'BASELINE_NOT_VERIFIED',baseline_parity=parity,
        comparisons={name:batch.stats(r['trades']) for name,r in results.items()},results=results,source_sha256=hashes,
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),observation_only=True,orders_sent=False,
        warning='Research only. Gross NIFTY points, not option P&L; costs excluded. Recorded/live and later API inputs are mixed. Checkpoint parity does not verify all counterfactual minutes. No live changes.',
        policy='Minute confirmation latches; no entry yet. At a strictly later completed 5m boundary require same-direction RSI/EMA/WMA ordering, directional WMA slope >0, and fresh passing minute checks. No additional 5m persistence requirement. Continued variant removes pending expiry and direction watch, but existing canonical cancellation and cutoff still apply.')
    (a.output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    lines=['# One-minute confirmation then five-minute support','',report['warning'],'',report['policy'],'','Baseline parity: '+parity['status'],'',
       '| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for name,s in report['comparisons'].items():lines.append(f"| {name} | {s['trades']} | {s['points']:.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','| Policy | Direction | Setup | First minute confirmation | Entry | Exit | Points |','|---|---|---|---|---|---|---:|']
    for name,r in results.items():
        for t in r['trades']:
            first=(t['entry_checks'].get('first_minute_confirmed_at') or t['entry_time'])[11:16]
            lines.append(f"| {name} | {t['direction']} | {t['signal_time'][11:16]} | {first} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['points']:.2f} |")
    lines+=['','Parity issues: '+json.dumps(parity['issues'])]
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);print(text);print('REPORT:',a.output/'report.json')
    raise SystemExit(0 if parity['status']=='PASS' else 2)

if __name__=='__main__':main()
