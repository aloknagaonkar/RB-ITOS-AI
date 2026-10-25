"""Research: retain pending setups until full entry confirmation or cutoff.

Offline only. No ten-minute expiry, opposite-arm cancellation, direction watch,
same-direction refresh, or canonical pending cancellation in the new variants.
Active position exits and 14:55 cutoff stay unchanged. No WMA45/55 lock.
"""
import argparse
import hashlib
import inspect
import json
import linecache
import os
from pathlib import Path
import textwrap
from types import SimpleNamespace
import unittest

def replace_once(source,old,new):
    if source.count(old)!=1:raise ValueError('RESEARCH_SOURCE_ANCHOR_MISMATCH:'+old[:90])
    return source.replace(old,new,1)

def unlimited_minute_gate(Base):
    source=textwrap.dedent(inspect.getsource(Base.evaluate))
    source=replace_once(source,'elapsed=0<=age<10 or same_boundary','elapsed=age>=0 or same_boundary')
    source=replace_once(source,'elif age>=10 or self.locked:del self.pending[side]','elif self.locked:del self.pending[side]')
    namespace=dict(Base.evaluate.__globals__)
    exec(compile(source,'<unlimited-minute-confirmation>','exec'),namespace)
    class Unlimited(Base):pass
    Unlimited.evaluate=namespace['evaluate']
    return Unlimited

def retained_gate(Base,direction):
    class Retained(Base):
        def signal(self,event,available):
            side=direction(event)
            if side in self.pending:
                self.policy_events.append(dict(time=available.isoformat(),event='SAME_DIRECTION_SETUP_RETAINED',direction=side,
                    original_available_at=self.pending[side]['available'].isoformat()))
                return
            return super().signal(event,available)
    return Retained

def retained_replay(engine):
    source=inspect.getsource(engine.replay)
    source=replace_once(source,
        "   for e in dec.accepted_events:\n    if e.event_type in EXIT_TYPES:g.pending.pop(direction(e),None)",
        "   # Retained-pending research: canonical exit does not cancel pending.\n   # Actual position dual exits below remain unchanged.")
    filename='<retained-pending-research-replay>'
    linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
    namespace=dict(engine.replay.__globals__)
    exec(compile(source,filename,'exec'),namespace)
    return namespace['replay']

class Checks(unittest.TestCase):
    def harness(self,is_five=False):
        import hilega_pending_confirmation_research as p
        import hilega_five_min_confirmation_research as five
        from market_lab import hilega_v2_alignment_replay_v1 as e
        Base=five.five_gate(e.WmaGapGate,continued=True) if is_five else unlimited_minute_gate(e.WmaGapGate)
        Gate=retained_gate(p.changed_gate(Base),e.direction)
        g=Gate(opposite_switch=True);at=p.dt('2026-08-26T09:50:00+05:30')
        event=e.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={})
        g.signal(event,at)
        def tick(clock,wma=60,ema=59,strength=1):
            decision=p.dt('2026-08-26T'+clock+':00+05:30')
            snap=SimpleNamespace(ready=True,rsi9=ema-1,ema3_rsi=ema,wma21_rsi=wma)
            ref=SimpleNamespace(ready=True,wma21_rsi=wma+strength)
            return g.evaluate(minute=decision-p.timedelta(minutes=1),current=snap,reference=ref,price=100)
        return g,tick,event,at,e,p
    def test_setup_survives_ten_minutes(self):
        g,tick,*_=self.harness();tick('10:05',strength=.1);self.assertIn('BEARISH',g.pending)
    def test_repeated_same_direction_does_not_reset(self):
        g,tick,event,at,e,p=self.harness();original=g.pending['BEARISH']
        g.signal(event,at+p.timedelta(minutes=20));self.assertIs(g.pending['BEARISH'],original)
    def test_opposite_setup_keeps_both(self):
        g,tick,event,at,e,p=self.harness()
        opposite=e.StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21',at,None,'IDLE','ARMED',details={})
        g.signal(opposite,at+p.timedelta(minutes=20));self.assertEqual(set(g.pending),{'BULLISH','BEARISH'})
    def test_opposite_arm_does_not_cancel(self):
        g,tick,event,at,e,p=self.harness()
        arm=e.StrategyEvent('PATH1_ARMED_RSI_CROSS_EMA3_UP',at,None,'IDLE','ARMED',details={})
        g.observe_arms([arm],at);self.assertIn('BEARISH',g.pending)
    def test_five_minute_pending_can_confirm_after_expiry(self):
        g,tick,*_=self.harness(True);tick('10:00',strength=.3)
        self.assertFalse(tick('10:05',ema=58)[0]);self.assertTrue(tick('10:10',ema=57)[0])
        self.assertEqual(g.owner,'BEARISH');self.assertFalse(g.pending)
    def test_minute_confirmation_still_requires_fresh_checks(self):
        g,tick,*_=self.harness();tick('10:05',strength=1)
        self.assertFalse(tick('10:06',ema=59.5,strength=.1)[0]);self.assertEqual(g.owner,'NONE')
    def test_cutoff_prevents_entry(self):
        g,tick,*_=self.harness();entries,checks=tick('14:55')
        self.assertFalse(entries);self.assertIn('SESSION_CUTOFF',checks[0]['reasons'])

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--date',default='2026-08-26')
    ap.add_argument('--research-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    ap.add_argument('--output',type=Path);ap.add_argument('--test',action='store_true');a=ap.parse_args()
    if a.test:
        r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks));raise SystemExit(0 if r.wasSuccessful() else 1)
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    import hilega_pending_confirmation_research as p
    import hilega_pending_previous10_research as batch
    import hilega_five_min_confirmation_research as five
    import hilega_vwap_confirmed36_research as support
    from hilega_vwap_wait_alignment_research import source_data
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    if engine.RULES['version']!=p.VERSION:raise ValueError('ENGINE_VERSION_MISMATCH')
    asof=p.dt(a.date+'T14:55:00+05:30')
    if asof>p.datetime.now(p.IST):raise ValueError('SESSION_NOT_COMPLETE')
    parent=json.loads((a.research_root/'3-month/report.json').read_text())
    if parent['strategy_version']!=p.VERSION:raise ValueError('SOURCE_VERSION_MISMATCH')
    sessions,grouped=source_data(a.research_root,parent,support)
    raw=grouped[a.date];warm=[(d,grouped[d]) for d in sessions if d<a.date and grouped.get(d)][-30:]
    if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
    frozen=a.research_root/'replays'/(a.date+'.json');saved=json.loads(frozen.read_text())
    if saved['session_date']!=a.date or saved['strategy_version']!=p.VERSION:raise ValueError('BASELINE_IDENTITY_MISMATCH')
    baseline=p.simulate(engine,a.date,raw,warm,asof,'CURRENT');parity=batch.frozen_parity(saved,baseline)
    if parity['status']!='PASS':raise ValueError('BASELINE_PARITY_NOT_PASS:'+json.dumps(parity))
    results={'CURRENT_1M':baseline}
    proxy=SimpleNamespace(WmaGapGate=five.five_gate(engine.WmaGapGate,False),replay=engine.replay)
    results['CURRENT_5M_10M_WINDOW']=p.simulate(proxy,a.date,raw,warm,asof,'CURRENT')
    replay=retained_replay(engine)
    for name,Base in [('RETAINED_1M',unlimited_minute_gate(engine.WmaGapGate)),('RETAINED_5M',five.five_gate(engine.WmaGapGate,True))]:
        Gate=retained_gate(p.changed_gate(Base),engine.direction)
        proxy=SimpleNamespace(WmaGapGate=Gate,replay=replay)
        # CURRENT here avoids wrapping the already insulated gate twice.
        results[name]=p.simulate(proxy,a.date,raw,warm,asof,'CURRENT')
    for name,r in results.items():
        batch.signature(r['trades']);r['research_variant']=name
        if '5M' in name and any(p.dt(t['entry_time']).minute%5 for t in r['trades']):raise ValueError('OFF_BOUNDARY_ENTRY')
    output=a.output or Path('data/research/hilega-retained-pending-'+a.date.replace('-',''));output.mkdir(parents=True,exist_ok=True)
    rules='New variants retain earliest same-direction setup, remove time expiry and direction watch, keep both directions pending after opposite arms/setups, and remove canonical pending cancellation. First full entry wins and clears all pending contexts. Every entry still requires current strength >=0.75, persistence, positive expanding gap, flat position and pre-cutoff time. Existing active exits and 14:55 cutoff retained. No WMA45/55 lock.'
    summary={name:batch.stats(r['trades']) for name,r in results.items()}
    report=dict(status='COMPLETE',baseline_parity=parity,session_date=a.date,comparisons=summary,results=results,rules=rules,
        observation_only=True,orders_sent=False,baseline_sha256=hashlib.sha256(frozen.read_bytes()).hexdigest(),
        input_sha256=hashlib.sha256(json.dumps([raw,warm],sort_keys=True,default=str).encode()).hexdigest(),
        warning='Frozen research reconstruction; gross NIFTY points, no option fills/costs. No live changes. New variants change pending lifecycle as well as expiry; compare retained 1m versus retained 5m to isolate cadence.')
    (output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    lines=['# Retain setup until confirmed entry — '+a.date,'',rules,'',report['warning'],'','Baseline parity: PASS','',
        '| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for name,s in summary.items():lines.append(f"| {name} | {s['trades']} | {s['points']:.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','| Policy | Direction | Original setup | Entry | Exit | Points |','|---|---|---|---|---|---:|']
    for name,r in results.items():
        for t in r['trades']:lines.append(f"| {name} | {t['direction']} | {t['signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['points']:.2f} |")
    lines+=['','## Retained five-minute checks, 09:45–10:25','','| Decision | Direction | Original available | Status | Strength | Reasons |','|---|---|---|---|---:|---|']
    for row in results['RETAINED_5M']['audit']:
        for c in row.get('checks') or []:
            if '09:45'<=c['decision_timestamp'][11:16]<='10:25':
                lines.append(f"| {c['decision_timestamp'][11:16]} | {c['direction']} | {c['signal_available_at'][11:16]} | {c['status']} | {c.get('directional_wma_strength')} | {', '.join(c['reasons']) or 'ALL PASSED'} |")
    text='\n'.join(lines)+'\n';(output/'summary.md').write_text(text);print(text);print('REPORT:',output/'report.json')

if __name__=='__main__':main()
