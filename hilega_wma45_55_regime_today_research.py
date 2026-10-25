"""Today's WMA21-of-RSI 45/55 regime filter; isolated research only.

Above 55 -> BULLISH; below 45 -> BEARISH. A strict crossing downward
through 55 -> BEARISH; a strict crossing upward through 45 -> BULLISH.
Inside the band retain that direction. Equality alone retains state; there is
no overnight carry. A session beginning in the band has NONE until qualified.
Original setup/confirmation/exit rules are retained; vetoed entries are consumed,
not deferred. Runs fixed-baseline screening and a separate stateful replay.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

def advance(previous,current,state):
    for value in (current,previous):
        if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=100):
            raise ValueError('INVALID_WMA')
    if current is None:raise ValueError('CURRENT_WMA_REQUIRED')
    if state not in ('NONE','BULLISH','BEARISH'):raise ValueError('INVALID_REGIME')
    if current>55:return 'BULLISH','ABOVE_55'
    if current<45:return 'BEARISH','BELOW_45'
    if previous is not None and previous>=55 and current<55:return 'BEARISH','CROSS_DOWN_55'
    if previous is not None and previous<=45 and current>45:return 'BULLISH','CROSS_UP_45'
    return state,'RETAIN_PREVIOUS_REGIME' if state!='NONE' else 'NO_SESSION_REGIME_YET'

def make_frames(baseline,dt):
    samples={}
    for row in baseline['audit']:
        at=dt(row['checkpoint']);ind=row.get('completed_5m_indicators')
        # Keep last-minute decisions distinct from their same-time cutoff exit.
        if at.minute%5 or not ind or row.get('nifty_close') is None:continue
        minute=dt(row['minute_timestamp'])
        if (at-minute).total_seconds()!=60:raise ValueError('NON_CAUSAL_COMPLETED_FRAME')
        wma=ind['wma21']
        if at in samples and samples[at]!=wma:raise ValueError('CONFLICTING_WMA_FRAME')
        samples[at]=wma
    state='NONE';previous=None;frames={}
    for at,wma in sorted(samples.items()):
        state,reason=advance(previous,wma,state)
        frames[at]=dict(available_at=at.isoformat(),wma21=wma,previous_wma21=previous,
                       wma_change=wma-previous if previous is not None else None,regime=state,reason=reason)
        previous=wma
    return frames

def frame_at(frames,at):
    boundary=at.replace(minute=at.minute-at.minute%5,second=0,microsecond=0)
    if boundary not in frames:raise ValueError('COMPLETED_REGIME_FRAME_MISSING:'+boundary.isoformat())
    if not 0<=(at-boundary).total_seconds()<300:raise ValueError('STALE_REGIME_FRAME')
    return frames[boundary]

def filter_gate(Base,direction,frames):
    class Filtered(Base):
        def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.policy_events=[]
        def evaluate(self,**kwargs):
            from datetime import timedelta
            entries,checks=super().evaluate(**kwargs)
            if not entries:return entries,checks
            if len(entries)!=1:raise ValueError('ONE_ENTRY_REQUIRED')
            at=kwargs['minute']+timedelta(minutes=1);side=direction(entries[0]);frame=frame_at(frames,at)
            passed=side==frame['regime']
            self.policy_events.append(dict(time=at.isoformat(),direction=side,passed=passed,regime_frame=frame,
                                           reason='DIRECTION_ALLOWED' if passed else 'WMA_REGIME_VETO'))
            for check in checks:
                if check.get('status')=='ENTRY':
                    check['wma_regime_filter']=copy.deepcopy(frame)
                    if not passed:check.update(status='WMA_REGIME_BLOCKED',reasons=list(check['reasons'])+['WMA_REGIME_VETO'])
            if passed:return entries,checks
            self.owner='NONE';self.active=None
            return [],checks
    return Filtered

class Checks(unittest.TestCase):
    def test_above55_bullish_regardless_slope(self):self.assertEqual(advance(60,56,'BEARISH')[0],'BULLISH')
    def test_below45_bearish_regardless_slope(self):self.assertEqual(advance(40,44,'BULLISH')[0],'BEARISH')
    def test_cross_down55_is_bearish(self):self.assertEqual(advance(56,54,'BULLISH'),('BEARISH','CROSS_DOWN_55'))
    def test_cross_up45_is_bullish(self):self.assertEqual(advance(44,46,'BEARISH'),('BULLISH','CROSS_UP_45'))
    def test_middle_carries_regime(self):
        self.assertEqual(advance(54,53,'BEARISH')[0],'BEARISH');self.assertEqual(advance(46,48,'BULLISH')[0],'BULLISH')
    def test_equality_does_not_create_regime(self):
        self.assertEqual(advance(56,55,'BULLISH')[0],'BULLISH');self.assertEqual(advance(44,45,'BEARISH')[0],'BEARISH')
        self.assertEqual(advance(None,55,'NONE')[0],'NONE');self.assertEqual(advance(None,45,'NONE')[0],'NONE')
    def test_cross_from_equal_threshold(self):
        self.assertEqual(advance(55,54,'BULLISH')[0],'BEARISH');self.assertEqual(advance(45,46,'BEARISH')[0],'BULLISH')
    def test_starting_middle_has_no_direction(self):self.assertEqual(advance(None,50,'NONE')[0],'NONE')
    def test_invalid_wma_rejected(self):
        for value in (None,True,float('nan'),float('inf'),-1,101):
            with self.assertRaises(ValueError):advance(50,value,'NONE')
    def test_future_frame_not_used(self):
        from datetime import datetime
        t=datetime.fromisoformat('2026-10-16T14:20:00+05:30')
        frame={'regime':'BULLISH'}
        frames={t:frame, t.replace(minute=25):{'regime':'BEARISH'}}
        self.assertIs(frame_at(frames,t.replace(minute=23)),frame)
    def test_veto_reverts_position(self):
        from datetime import datetime,timedelta
        class Base:
            def __init__(self):self.owner='NONE';self.active=None
            def evaluate(self,**kwargs):self.owner='BEARISH';self.active={'price':100};return ['e'],[dict(status='ENTRY',reasons=[])]
        at=datetime.fromisoformat('2026-10-16T14:20:00+05:30')
        g=filter_gate(Base,lambda e:'BEARISH',{at:dict(regime='BULLISH')})()
        entries,checks=g.evaluate(minute=at-timedelta(minutes=1))
        self.assertFalse(entries);self.assertEqual(g.owner,'NONE');self.assertIsNone(g.active);self.assertEqual(checks[0]['status'],'WMA_REGIME_BLOCKED')

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--date',default='2026-10-16')
    ap.add_argument('--input',type=Path,default=Path('data/research/hilega-pending-previous10-plus-today-20261016-v3/today-recorded-overrides.json'))
    ap.add_argument('--audit',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-wma45-55-regime-20261016'))
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
    baseline=p.simulate(engine,a.date,raw,warm,asof,'CURRENT')
    frames=make_frames(baseline,p.dt)
    parity=p.audit_parity(a.audit,a.date,asof,baseline)
    cutoffs=(json.loads(a.input.read_text()).get('provenance') or {}).get('cutoff_payloads')
    if not cutoffs:parity['issues'].append('RECORDED_CUTOFF_PROVENANCE_REQUIRED')
    else:parity['issues'].extend(batch.cutoff_parity(baseline,cutoffs))
    if parity['issues']:parity['status']='MISMATCH'
    proxy=SimpleNamespace(WmaGapGate=filter_gate(engine.WmaGapGate,engine.direction,frames),replay=engine.replay)
    filtered=p.simulate(proxy,a.date,raw,warm,asof,'CURRENT');filtered['research_variant']='WMA45_55_REVERSAL_FILTER'
    screened=[]
    for t in baseline['trades']:
        frame=frame_at(frames,p.dt(t['entry_time']))
        screened.append(dict(t,regime=frame['regime'],wma21=frame['wma21'],wma_available_at=frame['available_at'],
                             regime_reason=frame['reason'],passed=t['direction']==frame['regime']))
    for r in (baseline,filtered):batch.signature(r['trades'])
    passed=[t for t in screened if t['passed']];blocked=[t for t in screened if not t['passed']]
    report=dict(status='COMPLETE' if parity['status']=='PASS' else 'BASELINE_NOT_VERIFIED',baseline_parity=parity,
        observation_only=True,orders_sent=False,source_sha256=hashes,runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        comparisons={'CURRENT':batch.stats(baseline['trades']),'STATEFUL_WMA45_55_FILTER':batch.stats(filtered['trades'])},
        fixed_baseline_screen=dict(taken=batch.stats(passed),blocked=batch.stats(blocked),
           loss_points_avoided=round(-sum(t['points'] for t in blocked if t['points']<0),4),
           profit_points_forgone=round(sum(t['points'] for t in blocked if t['points']>0),4)),
        fixed_baseline_trades=screened,regime_frames=list(frames.values()),results=dict(CURRENT=baseline,STATEFUL_WMA45_55_FILTER=filtered),
        warning='Gross NIFTY points, no option fills or execution costs. Mixed recorded/live and later API inputs; checkpoint parity does not verify every counterfactual minute. No live changes.',
        rules='WMA21 of RSI from completed 5m candles only. >55 BULLISH; <45 BEARISH; crossing down through 55 BEARISH; crossing up through 45 BULLISH. Middle band carries regime; equality creates no new direction. Reset regime each session; first reading in middle starts NONE. Filter existing confirmed entries only; veto consumes that confirmed setup, without adding wait. Existing minute checks, direction watch, exits and 14:55 cutoff unchanged. Not stacked with sequential-confirmation research.')
    (a.output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    lines=['# WMA45/55 regime and reversal research','',report['rules'],'',report['warning'],'','Baseline parity: '+parity['status'],'',
       '| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for name,s in report['comparisons'].items():lines.append(f"| {name} | {s['trades']} | {s['points']:.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','## Original signals: taken or blocked','','| Direction | Setup | Entry | Exit | Current points | Completed WMA | Allowed direction | Outcome |','|---|---|---|---|---:|---:|---|---|']
    for t in screened:lines.append(f"| {t['direction']} | {t['signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['points']:.2f} | {t['wma21']:.3f} | {t['regime']} | {'TAKEN' if t['passed'] else 'BLOCKED'} |")
    lines+=['','## Stateful filtered trades','','| Direction | Setup | Entry | Exit | Points |','|---|---|---|---|---:|']
    for t in filtered['trades']:lines.append(f"| {t['direction']} | {t['signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['points']:.2f} |")
    lines+=['','## Regime changes','','| Available at | Previous WMA | WMA | Allowed direction | Reason |','|---|---:|---:|---|---|']
    previous=None
    for frame in frames.values():
        if frame['regime']!=previous:
            lines.append(f"| {frame['available_at'][11:16]} | {frame['previous_wma21']} | {frame['wma21']:.3f} | {frame['regime']} | {frame['reason']} |")
        previous=frame['regime']
    lines+=['','Fixed-baseline screen: '+json.dumps(report['fixed_baseline_screen']),'','Parity issues: '+json.dumps(parity['issues'])]
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);print(text);print('REPORT:',a.output/'report.json')
    raise SystemExit(0 if parity['status']=='PASS' else 2)

if __name__=='__main__':main()
