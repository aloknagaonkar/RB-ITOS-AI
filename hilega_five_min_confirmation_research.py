"""Today's five-minute confirmation research. No API calls or live changes.

Uses the recorded-overrides input from the completed pending-direction research.
Setup generation retains its existing minute-gap inputs. ONLY confirmation uses
completed 5m readings; persistence compares consecutive 5m readings. Ordinary
new setups require first post-setup reading then a later qualifying reading.
"""
import argparse
import copy
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import os
import unittest
from datetime import timedelta

def five_gate(Base,continued=False):
    source=inspect.getsource(Base.evaluate)
    source=__import__('textwrap').dedent(source)
    needle="previous['minute']==minute-timedelta(minutes=1)"
    if source.count(needle)!=1:raise ValueError('CONFIRMATION_CONSECUTIVE_ANCHOR_MISMATCH')
    source=source.replace(needle,"previous['minute']==minute-timedelta(minutes=5)",1)
    if continued:
        old='elapsed=0<=age<10 or same_boundary'
        if source.count(old)!=1:raise ValueError('WINDOW_ANCHOR_MISMATCH')
        source=source.replace(old,'elapsed=age>=0 or same_boundary',1)
        old='elif age>=10 or self.locked:del self.pending[side]'
        if source.count(old)!=1:raise ValueError('EXPIRY_ANCHOR_MISMATCH')
        source=source.replace(old,'elif self.locked:del self.pending[side]',1)
    namespace=dict(Base.evaluate.__globals__)
    exec(compile(source,'<research-five-minute-confirmation>','exec'),namespace)
    evaluate_boundary=namespace['evaluate']
    class FiveMinuteGate(Base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);self.five_previous=None;self.cadence_audit=[]
        def evaluate(self,*,minute,current,reference,price,exit_boundary=False):
            at=minute+timedelta(minutes=1)
            change=current.wma21_rsi-reference.wma21_rsi if current.ready and reference and reference.ready else None
            minute_previous=dict(minute=minute,snapshot=current,wma_change=change)
            if at.minute%5:
                # Preserve minute inputs used by the unchanged setup generator,
                # but do not confirm/arm entries from these intermediate bars.
                self.can_signal('BULLISH',at)
                for side,pending in list(self.pending.items()):
                    if self.locked or (not continued and (minute-pending['available']).total_seconds()/60>=10):
                        self.cadence_audit.append(dict(time=at.isoformat(),event='PENDING_EXPIRED_OR_LOCKED',direction=side))
                        del self.pending[side]
                self.previous=minute_previous
                return [],[]
            self.previous=self.five_previous
            entries,checks=evaluate_boundary(self,minute=minute,current=current,reference=reference,price=price,exit_boundary=exit_boundary)
            self.five_previous=self.previous
            self.previous=minute_previous
            for check in checks:
                check.update(confirmation_interval_minutes=5,confirmation_snapshot_basis='COMPLETED_FIVE_MINUTE',
                             persistence_reference='PREVIOUS_COMPLETED_FIVE_MINUTE',continued_wait=continued)
            self.cadence_audit.append(dict(time=at.isoformat(),event='FIVE_MINUTE_CONFIRMATION_CHECK',checks=copy.deepcopy(checks)))
            return entries,checks
    return FiveMinuteGate

class Checks(unittest.TestCase):
    def harness(self,continued=False):
        import hilega_pending_confirmation_research as p
        from market_lab import hilega_v2_alignment_replay_v1 as e
        gate=five_gate(e.WmaGapGate,continued)(opposite_switch=False)
        at=p.dt('2026-10-16T14:20:00+05:30')
        event=e.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at-timedelta(minutes=5),None,'IDLE','ARMED',details={})
        gate.signal(event,at)
        def tick(clock,wma=49,ema=47):
            t=p.dt('2026-10-16T'+clock+':00+05:30')
            snap=SimpleNamespace(ready=True,rsi9=ema-1,ema3_rsi=ema,wma21_rsi=wma)
            ref=SimpleNamespace(ready=True,wma21_rsi=wma+1)
            return gate.evaluate(minute=t-timedelta(minutes=1),current=snap,reference=ref,price=100)
        return gate,tick
    def test_no_minute_entry_or_arming(self):
        g,tick=self.harness();tick('14:20');entries,checks=tick('14:21')
        self.assertEqual((entries,checks),([],[]));self.assertIsNone(g.pending['BEARISH']['armed_at'])
    def test_two_post_setup_five_minute_readings(self):
        g,tick=self.harness();tick('14:20',49,48)
        self.assertFalse(tick('14:25',49,47)[0])
        self.assertTrue(tick('14:30',49,46)[0]);self.assertEqual(g.owner,'BEARISH')
    def test_gap_compares_five_minute_not_last_minute(self):
        g,tick=self.harness();tick('14:20',49,48);tick('14:24',49,40)
        _,checks=tick('14:25',49,47)
        self.assertTrue(checks[0]['gap_expanding_pass']);self.assertEqual(checks[0]['previous_gap'],1)
    def test_ten_minute_expiry_retained(self):
        g,tick=self.harness();tick('14:20');tick('14:25');tick('14:30')
        tick('14:31');self.assertFalse(g.pending)
    def test_continued_wait_does_not_expire_at_ten(self):
        g,tick=self.harness(True);tick('14:20',49,48);tick('14:25',49,48);tick('14:30',49,48)
        tick('14:31',49,48);self.assertIn('BEARISH',g.pending)
        self.assertTrue(tick('14:35',49,47)[0])
    def test_cutoff_still_prevents_entry(self):
        g,tick=self.harness(True);tick('14:20',49,48);tick('14:25',49,48)
        entries,checks=tick('14:55',49,47)
        self.assertFalse(entries);self.assertIn('SESSION_CUTOFF',checks[0]['reasons'])

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--date',default='2026-10-16')
    ap.add_argument('--input',type=Path,default=Path('data/research/hilega-pending-previous10-plus-today-20261016-v3/today-recorded-overrides.json'))
    ap.add_argument('--audit',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-five-minute-confirmation-20261016'))
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
    a.output.mkdir(parents=True,exist_ok=True)
    raw,warm,hashes=p.inputs(engine,a.date,a.input,False,a.output)
    raw=[r for r in raw if p.dt(r['timestamp'])<=asof]
    results={};specs=(('CURRENT_MINUTE',False,False,False),('FIVE_MINUTE_10M_WINDOW',True,False,False),
       ('CONFIRMED_OPPOSITE_MINUTE',False,True,False),('CONFIRMED_OPPOSITE_5M_10M_WINDOW',True,True,False),
       ('CONFIRMED_OPPOSITE_5M_CONTINUED',True,True,True))
    for name,is_five,confirmed,continued in specs:
        Gate=five_gate(engine.WmaGapGate,continued) if is_five else engine.WmaGapGate
        proxy=SimpleNamespace(WmaGapGate=Gate,replay=engine.replay)
        result=p.simulate(proxy,a.date,raw,warm,asof,'CONFIRMED_OPPOSITE_ONLY' if confirmed else 'CURRENT')
        result['research_variant']=name
        for t in result['trades']:
            at=p.dt(t['entry_time'])
            if is_five and at.minute%5:raise ValueError('OFF_BOUNDARY_ENTRY:'+name+':'+t['entry_time'])
        batch.signature(result['trades'])
        results[name]=result
        (a.output/(name+'.json')).write_text(json.dumps(result,indent=2,default=str)+'\n')
    parity=p.audit_parity(a.audit,a.date,asof,results['CURRENT_MINUTE'])
    provenance=json.loads(a.input.read_text()).get('provenance') or {}
    if not provenance.get('cutoff_payloads'):parity['issues'].append('RECORDED_CUTOFF_PROVENANCE_REQUIRED')
    else:parity['issues'].extend(batch.cutoff_parity(results['CURRENT_MINUTE'],provenance['cutoff_payloads']))
    if parity['issues']:parity['status']='MISMATCH'
    summary={name:batch.stats(r['trades']) for name,r in results.items()}
    report=dict(status='COMPLETE' if parity['status']=='PASS' else 'BASELINE_NOT_VERIFIED',baseline_parity=parity,comparisons=summary,
       results=results,source_sha256=hashes,runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),observation_only=True,orders_sent=False,
       warning='Gross NIFTY points; no option fills or costs. Today uses recorded and later API inputs; checkpoint parity does not validate every counterfactual minute. No live changes.',
       interpretation='Compare CURRENT_MINUTE versus FIVE_MINUTE_10M_WINDOW to isolate cadence; compare CONFIRMED_OPPOSITE_MINUTE versus CONFIRMED_OPPOSITE_5M_10M_WINDOW for cadence under the prior research policy; compare the latter with CONTINUED to isolate pending expiry. Continued pending ends on full entry confirmation, existing canonical cancellation, or cutoff. Existing canonical cancellation is NOT removed.')
    (a.output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    lines=['# Five-minute entry confirmation research','',report['warning'],'',report['interpretation'],'','Baseline parity: '+parity['status'],'',
       '| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for name,s in summary.items():lines.append(f"| {name} | {s['trades']} | {s['points']:.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','## Trade details','','| Policy | Direction | Setup | Entry | Exit | Points |','|---|---|---|---|---|---:|']
    for name,r in results.items():
        for t in r['trades']:lines.append(f"| {name} | {t['direction']} | {t['signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['points']:.2f} |")
    lines+=['','Parity issues: '+json.dumps(parity['issues'])]
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);print(text);print('REPORT:',a.output/'report.json')
    raise SystemExit(0 if parity['status']=='PASS' else 2)

if __name__=='__main__':main()
