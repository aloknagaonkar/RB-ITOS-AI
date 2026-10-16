"""Post-entry WMA direction lock, today only; no live changes/API/orders.

The first normal entry is not filtered by WMA. Later completed 5m readings can
arm a lock ONLY while an actual research position is active. BULLISH + rising
WMA>55 arms bullish lock; BEARISH + falling WMA<45 arms bearish lock. A lock
survives exit, blocks opposite new entries, and releases only on a strict reverse
cross of its threshold (55 downward / 45 upward). Release does not open a trade
or automatically establish the opposite lock. Session starts with no lock.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from datetime import timedelta

class DirectionLock:
    def __init__(self):self.side='NONE';self.last_at=None;self.events=[]
    def observe(self,at,wma,previous,active):
        if self.last_at==at:return
        if self.last_at is not None and at<self.last_at:raise ValueError('LOCK_TIME_REGRESSION')
        if at.minute%5 or at.second or at.microsecond:raise ValueError('COMPLETED_5M_BOUNDARY_REQUIRED')
        for value in (wma,previous):
            if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=100):raise ValueError('INVALID_WMA')
        if wma is None:raise ValueError('CURRENT_WMA_REQUIRED')
        if active not in ('NONE','BULLISH','BEARISH'):raise ValueError('INVALID_ACTIVE_DIRECTION')
        before=self.side;reason=None
        if self.side=='BULLISH' and previous is not None and previous>=55 and wma<55:
            self.side='NONE';reason='BULLISH_LOCK_RELEASED_CROSS_DOWN_55'
        elif self.side=='BEARISH' and previous is not None and previous<=45 and wma>45:
            self.side='NONE';reason='BEARISH_LOCK_RELEASED_CROSS_UP_45'
        if self.side=='NONE' and previous is not None:
            if active=='BULLISH' and wma>55 and wma>previous:
                self.side='BULLISH';reason='ACTIVE_BULLISH_WMA_ABOVE_55_RISING'
            elif active=='BEARISH' and wma<45 and wma<previous:
                self.side='BEARISH';reason='ACTIVE_BEARISH_WMA_BELOW_45_FALLING'
        self.last_at=at
        if self.side!=before:self.events.append(dict(time=at.isoformat(),before=before,after=self.side,reason=reason,
                                                     active_direction=active,wma21=wma,previous_wma21=previous))
    def permits(self,side):
        if side not in ('BULLISH','BEARISH'):raise ValueError('INVALID_ENTRY_DIRECTION')
        return self.side in ('NONE',side)

def completed_frames(baseline,dt):
    frames={};previous=None;last=None
    for row in baseline['audit']:
        at=dt(row['checkpoint']);ind=row.get('completed_5m_indicators')
        if at.minute%5 or not ind or row.get('nifty_close') is None:continue
        value=ind['wma21']
        if at in frames:
            if frames[at]['wma21']!=value:raise ValueError('CONFLICTING_COMPLETED_WMA')
            continue
        if last is not None and at-last!=timedelta(minutes=5):raise ValueError('INCOMPLETE_COMPLETED_WMA_PATH')
        frames[at]=dict(wma21=value,previous_wma21=previous,available_at=at.isoformat())
        previous=value;last=at
    return frames

def lock_gate(Base,direction,frames):
    class Locked(Base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);self.direction_lock=DirectionLock();self.policy_events=[]
        def update_lock(self,at):
            if at.minute%5:return
            frame=frames.get(at)
            if frame is None:raise ValueError('COMPLETED_WMA_FRAME_MISSING:'+at.isoformat())
            before=len(self.direction_lock.events)
            self.direction_lock.observe(at,frame['wma21'],frame['previous_wma21'],self.owner)
            self.policy_events.extend(dict(e,event='POST_ENTRY_LOCK_CHANGE') for e in self.direction_lock.events[before:])
        def close(self,event,at,price):
            # Include the final completed bar before the existing exit commits.
            # Do not prevent, delay or alter that exit based on the lock.
            self.update_lock(at)
            return super().close(event,at,price)
        def evaluate(self,**kwargs):
            at=kwargs['minute']+timedelta(minutes=1)
            self.update_lock(at)
            entries,checks=super().evaluate(**kwargs)
            if not entries:return entries,checks
            if len(entries)!=1:raise ValueError('ONE_CONFIRMED_ENTRY_REQUIRED')
            side=direction(entries[0]);allowed=self.direction_lock.permits(side)
            boundary=at.replace(minute=at.minute-at.minute%5,second=0,microsecond=0)
            frame=frames.get(boundary)
            if frame is None:raise ValueError('ENTRY_WMA_FRAME_MISSING')
            self.policy_events.append(dict(time=at.isoformat(),event='CONFIRMED_ENTRY_LOCK_CHECK',direction=side,
                allowed=allowed,lock=self.direction_lock.side,wma21=frame['wma21'],wma_available_at=frame['available_at']))
            for check in checks:
                if check.get('status')=='ENTRY':
                    check['post_entry_wma_lock']=dict(side=self.direction_lock.side,allowed=allowed)
                    if not allowed:check.update(status='POST_ENTRY_WMA_LOCK_BLOCKED',reasons=list(check['reasons'])+['OPPOSITE_ENTRY_BLOCKED_BY_POST_ENTRY_WMA_LOCK'])
            if allowed:return entries,checks
            # Decline the fully evaluated entry without fabricating a position.
            # No extra wait, setup, exit or signal-generation rule is introduced.
            self.owner='NONE';self.active=None
            return [],checks
    return Locked

def frozen_screen(trades,frames,dt):
    lock=DirectionLock();states={}
    for at,frame in frames.items():
        active=[t for t in trades if dt(t['entry_time'])<at<=dt(t['exit_time'])]
        if len(active)>1:raise ValueError('OVERLAPPING_BASELINE_TRADES')
        owner=active[0]['direction'] if active else 'NONE'
        lock.observe(at,frame['wma21'],frame['previous_wma21'],owner);states[at]=lock.side
    rows=[]
    for trade in trades:
        at=dt(trade['entry_time']);boundary=at.replace(minute=at.minute-at.minute%5,second=0,microsecond=0)
        side=states[boundary]
        rows.append(dict(trade,lock_at_entry=side,passed=side in ('NONE',trade['direction']),wma21=frames[boundary]['wma21']))
    return rows,lock.events

class Checks(unittest.TestCase):
    def stamp(self,minute=0):
        from datetime import datetime
        return datetime.fromisoformat('2026-10-16T10:00:00+05:30')+timedelta(minutes=minute)
    def test_flat_market_cannot_create_lock(self):
        g=DirectionLock();g.observe(self.stamp(),60,59,'NONE');self.assertEqual(g.side,'NONE');self.assertTrue(g.permits('BEARISH'))
    def test_first_entry_allowed_below45(self):
        g=DirectionLock();g.observe(self.stamp(),36,35,'NONE');self.assertTrue(g.permits('BULLISH'))
    def test_active_bullish_above55_rising_locks(self):
        g=DirectionLock();g.observe(self.stamp(),56,54,'BULLISH');self.assertEqual(g.side,'BULLISH');self.assertFalse(g.permits('BEARISH'))
    def test_bullish_falling_above55_does_not_arm(self):
        g=DirectionLock();g.observe(self.stamp(),56,57,'BULLISH');self.assertEqual(g.side,'NONE')
    def test_lock_persists_after_exit_and_falling_above55(self):
        g=DirectionLock();g.observe(self.stamp(),58,57,'BULLISH');g.observe(self.stamp(5),56,58,'NONE');self.assertEqual(g.side,'BULLISH')
    def test_bullish_lock_releases_below55(self):
        g=DirectionLock();g.observe(self.stamp(),56,54,'BULLISH');g.observe(self.stamp(5),54,56,'NONE');self.assertEqual(g.side,'NONE');self.assertTrue(g.permits('BEARISH'))
    def test_bearish_lock_symmetric(self):
        g=DirectionLock();g.observe(self.stamp(),44,46,'BEARISH');self.assertFalse(g.permits('BULLISH'))
        g.observe(self.stamp(5),46,44,'NONE');self.assertEqual(g.side,'NONE')
    def test_equality_does_not_release(self):
        g=DirectionLock();g.observe(self.stamp(),56,54,'BULLISH');g.observe(self.stamp(5),55,56,'NONE');self.assertEqual(g.side,'BULLISH')
        g.observe(self.stamp(10),54,55,'NONE');self.assertEqual(g.side,'NONE')
    def test_no_automatic_opposite_lock_after_release(self):
        g=DirectionLock();g.observe(self.stamp(),56,54,'BULLISH');g.observe(self.stamp(5),40,56,'NONE');self.assertEqual(g.side,'NONE')
    def test_intra_minute_cannot_update_lock(self):
        with self.assertRaises(ValueError):DirectionLock().observe(self.stamp(1),56,54,'BULLISH')
    def test_invalid_wma_rejected(self):
        with self.assertRaises(ValueError):DirectionLock().observe(self.stamp(),float('nan'),54,'BULLISH')
    def test_same_boundary_is_idempotent(self):
        g=DirectionLock();g.observe(self.stamp(),56,54,'BULLISH');g.observe(self.stamp(),56,54,'NONE');self.assertEqual(len(g.events),1)
    def test_close_is_not_blocked_and_lock_survives(self):
        class Base:
            def __init__(self):self.owner='BULLISH';self.active={'price':100}
            def close(self,event,at,price):self.owner='NONE';self.active=None;return event
        at=self.stamp();g=lock_gate(Base,lambda e:'BULLISH',{at:dict(wma21=56,previous_wma21=54,available_at=at.isoformat())})()
        self.assertEqual(g.close('exit',at,110),'exit');self.assertEqual(g.owner,'NONE');self.assertEqual(g.direction_lock.side,'BULLISH')
    def test_opposite_confirmed_entry_veto_leaves_flat(self):
        class Base:
            def __init__(self):self.owner='NONE';self.active=None
            def evaluate(self,**kwargs):
                self.owner='BEARISH';self.active={'price':100}
                return ['BEARISH'],[dict(status='ENTRY',reasons=[])]
        at=self.stamp();g=lock_gate(Base,lambda e:e,{at:dict(wma21=56,previous_wma21=57,available_at=at.isoformat())})()
        g.direction_lock.side='BULLISH'
        entries,checks=g.evaluate(minute=at-timedelta(minutes=1))
        self.assertEqual(entries,[]);self.assertEqual(g.owner,'NONE');self.assertIsNone(g.active)
        self.assertEqual(checks[0]['status'],'POST_ENTRY_WMA_LOCK_BLOCKED')
    def test_first_confirmed_entry_unchanged(self):
        class Base:
            def __init__(self):self.owner='NONE';self.active=None
            def evaluate(self,**kwargs):
                self.owner='BULLISH';self.active={'price':100}
                return ['BULLISH'],[dict(status='ENTRY',reasons=[])]
        at=self.stamp();g=lock_gate(Base,lambda e:e,{at:dict(wma21=36,previous_wma21=35,available_at=at.isoformat())})()
        entries,checks=g.evaluate(minute=at-timedelta(minutes=1))
        self.assertEqual(entries,['BULLISH']);self.assertEqual(g.owner,'BULLISH');self.assertEqual(g.direction_lock.side,'NONE')

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--date',default='2026-10-16')
    ap.add_argument('--input',type=Path,default=Path('data/research/hilega-pending-previous10-plus-today-20261016-v3/today-recorded-overrides.json'))
    ap.add_argument('--audit',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-post-entry-wma-lock-20261016'))
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
    baseline=p.simulate(engine,a.date,raw,warm,asof,'CURRENT');frames=completed_frames(baseline,p.dt)
    parity=p.audit_parity(a.audit,a.date,asof,baseline)
    cutoffs=(json.loads(a.input.read_text()).get('provenance') or {}).get('cutoff_payloads')
    if not cutoffs:parity['issues'].append('RECORDED_CUTOFF_PROVENANCE_REQUIRED')
    else:parity['issues'].extend(batch.cutoff_parity(baseline,cutoffs))
    if parity['issues']:parity['status']='MISMATCH'
    proxy=SimpleNamespace(WmaGapGate=lock_gate(engine.WmaGapGate,engine.direction,frames),replay=engine.replay)
    filtered=p.simulate(proxy,a.date,raw,warm,asof,'CURRENT');filtered['research_variant']='POST_ENTRY_WMA_LOCK'
    for r in (baseline,filtered):batch.signature(r['trades'])
    if baseline['trades']:
        if not filtered['trades']:raise ValueError('FIRST_ENTRY_MUST_NOT_BE_BLOCKED')
        b,n=baseline['trades'][0],filtered['trades'][0]
        if any(b[k]!=n[k] for k in ('direction','entry_time','entry_price')):raise ValueError('FIRST_NORMAL_ENTRY_CHANGED')
    screen,screen_events=frozen_screen(baseline['trades'],frames,p.dt)
    taken=[t for t in screen if t['passed']];blocked=[t for t in screen if not t['passed']]
    report=dict(status='COMPLETE' if parity['status']=='PASS' else 'BASELINE_NOT_VERIFIED',baseline_parity=parity,observation_only=True,orders_sent=False,
       source_sha256=hashes,runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
       comparisons={'CURRENT':batch.stats(baseline['trades']),'POST_ENTRY_WMA_LOCK':batch.stats(filtered['trades'])},
       results=dict(CURRENT=baseline,POST_ENTRY_WMA_LOCK=filtered),fixed_baseline_trades=screen,
       fixed_baseline_lock_events=screen_events,fixed_baseline_screen=dict(taken=batch.stats(taken),blocked=batch.stats(blocked),
          loss_points_avoided=round(-sum(t['points'] for t in blocked if t['points']<0),4),profit_points_forgone=round(sum(t['points'] for t in blocked if t['points']>0),4)),
       warning='Research only. Gross NIFTY points, no option fills/costs. Mixed recorded/live and later API inputs; checkpoint parity does not verify every counterfactual minute. No live changes.',
       rules='First entry normal. Lock can arm only while a position is active, at a later completed 5m boundary: bullish WMA>55 and rising; bearish WMA<45 and falling. Lock persists after existing exit. Opposite new entries vetoed until strict cross down through55 / up through45 respectively releases lock to NONE. No automatic opposite lock, no WMA-generated entries. Session reset NONE. Existing setup, minute confirmation, direction watch, ten-minute window, exits and 14:55 cutoff retained. Not stacked with other research policies.')
    (a.output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    lines=['# Post-entry WMA direction lock — today','',report['rules'],'',report['warning'],'','Baseline parity: '+parity['status'],'',
       '| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for name,s in report['comparisons'].items():lines.append(f"| {name} | {s['trades']} | {s['points']:.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','## Original trades under frozen-baseline lock monitoring','','| Direction | Setup | Entry | Exit | Points | WMA | Lock at entry | Outcome |','|---|---|---|---|---:|---:|---|---|']
    for t in screen:lines.append(f"| {t['direction']} | {t['signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['points']:.2f} | {t['wma21']:.3f} | {t['lock_at_entry']} | {'TAKEN' if t['passed'] else 'BLOCKED'} |")
    lines+=['','## Stateful research trades','','| Direction | Setup | Entry | Exit | Points |','|---|---|---|---|---:|']
    for t in filtered['trades']:lines.append(f"| {t['direction']} | {t['signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['points']:.2f} |")
    lines+=['','## Actual research lock changes','','| Time | Before | After | Active direction | WMA | Reason |','|---|---|---|---|---:|---|']
    for e in filtered['policy_events']:
        if e['event']=='POST_ENTRY_LOCK_CHANGE':lines.append(f"| {e['time'][11:16]} | {e['before']} | {e['after']} | {e['active_direction']} | {e['wma21']:.3f} | {e['reason']} |")
    lines+=['','Fixed-baseline screening is separate from stateful replay: later candidate availability may differ.','',
       'Fixed-baseline counts: '+json.dumps(report['fixed_baseline_screen']),'','Parity issues: '+json.dumps(parity['issues'])]
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);print(text);print('REPORT:',a.output/'report.json')
    raise SystemExit(0 if parity['status']=='PASS' else 2)

if __name__=='__main__':main()
