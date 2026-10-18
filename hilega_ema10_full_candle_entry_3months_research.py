"""Research only: confirmed baseline entry AND completed full-candle price EMA10 support.
No orders, API calls, installation or live strategy changes. Run from RB-ITOS-AI.
"""
import csv
import inspect
import json
import linecache
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest

MODEL='CONFIRMED_ENTRY_EMA10_WITH_EXISTING_BASELINE_2_V2'
BASES=('EXISTING','PREVIOUS_AND','FRESH_AND')
POLICIES=tuple(k for b in BASES for k in (b,b+'_EMA10_ENTRY'))+('EXISTING_BASELINE_2',)
WARNING=('Research only. Gross NIFTY points; no option fills or costs. Each EMA variant adds an entry gate to its own baseline. '
    'Latest completed 5m candle: bullish LOW > price EMA10 and EMA10 rising; bearish HIGH < EMA10 and EMA10 falling. '
    'Strict comparisons; equality waits. EMA10 uses close, alpha 2/11, first-close seed, continuous over original warmup. '
    'For the original three EMA variants, full baseline confirmation comes first. Failed EMA checks retain only that candidate within its original ten-minute window, '
    'with fresh baseline checks each minute. WMA-vetoed candidates stay consumed. Original exits and 14:55 cutoff retained. '
    'EXISTING_BASELINE_2 instead validates only completed 5m boundaries: strength >=0.75, positive gap expanding versus the prior completed 5m, '
    'plus the same full-candle EMA10 entry rule. No persistence veto or time-based candidate expiry in baseline 2. '
    'Existing setup generation, opposite-arm/setup cancellation, canonical cancellation, position ownership and exits remain in baseline 2; '
    'no WMA direction lock or RSI/EMA exception is added. A candidate can still be cancelled by original lifecycle events. '
    'The original first-post-setup timing and same-exit-boundary exception remain. No EMA exit or reversal override in any policy. '
    'Historical controls reproduce saved research, not historical broker execution; Oct16 recorded/API inputs are mixed. '
    'Exploratory sample already examined; no independent holdout or live changes.')


def single_session(value,calendar,start,end,extra_day):
    try:
        parsed=datetime.strptime(value,'%Y-%m-%d').date().isoformat()
    except ValueError as exc:raise ValueError('DATE_MUST_BE_YYYY_MM_DD') from exc
    if parsed!=value:raise ValueError('DATE_MUST_BE_YYYY_MM_DD')
    if not start<=value<=end:raise ValueError('DATE_OUTSIDE_SAVED_RESEARCH_RANGE:'+start+'..'+end)
    if value not in set(calendar)|{extra_day}:raise ValueError('REQUESTED_TRADING_SESSION_UNAVAILABLE:'+value)
    return [value]


def frame_check(side, frame, at):
    if side not in ('BULLISH','BEARISH'):raise ValueError('INVALID_DIRECTION')
    if frame is None:return dict(passed=False,reasons=['COMPLETED_5M_FRAME_MISSING'])
    available=datetime.fromisoformat(frame['available_at'])
    if available>at:raise ValueError('FUTURE_EMA_FRAME')
    if at-available>=timedelta(minutes=5):raise ValueError('STALE_EMA_FRAME')
    fields=('open','high','low','close','ema10','previous_ema10')
    for k in fields:
        v=frame[k]
        if isinstance(v,bool) or v is None or not math.isfinite(float(v)) or float(v)<=0:
            raise ValueError('INVALID_EMA_FRAME:'+k)
    o,h,l,c,e,p=(float(frame[k]) for k in fields)
    if h<max(o,l,c) or l>min(o,c):raise ValueError('INVALID_OHLC')
    correct_side=l>e if side=='BULLISH' else h<e
    correct_slope=e>p if side=='BULLISH' else e<p
    reasons=[]
    if not correct_side:reasons.append('ENTIRE_CANDLE_NOT_ABOVE_EMA10' if side=='BULLISH' else 'ENTIRE_CANDLE_NOT_BELOW_EMA10')
    if not correct_slope:reasons.append('EMA10_NOT_RISING' if side=='BULLISH' else 'EMA10_NOT_FALLING')
    return dict(frame,passed=not reasons,reasons=reasons,ema10_slope=e-p,
                entire_candle_pass=correct_side,slope_pass=correct_slope)


def build_frames(engine,day,raw,warm,dt):
    if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
    value=None;frames={};count=0
    for session,rows in list(warm)+[(day,raw)]:
        # The cutoff minute OPEN is replay evidence, not a completed 14:55-15:00 bar.
        if session==day:rows=[r for r in rows if dt(r['timestamp']).strftime('%H:%M')<'14:55']
        bars=engine.aggregate_exact_5m(engine.candles(rows),dt(session+'T00:00:00+05:30').date(),require_full_session=False)
        for bar in bars:
            previous=value;close=float(bar.close)
            if not math.isfinite(close) or close<=0:raise ValueError('INVALID_CLOSE')
            value=close if value is None else value+(2/11)*(close-value);count+=1
            if session==day:
                available=bar.ts+timedelta(minutes=5)
                if available in frames:raise ValueError('DUPLICATE_EMA_BOUNDARY')
                frames[available]=dict(open=float(bar.open),high=float(bar.high),low=float(bar.low),close=close,
                    ema10=value,previous_ema10=previous,candle_label=bar.ts.isoformat(),available_at=available.isoformat(),seeded_bar_count=count)
    return frames


def entry_gate(Parent,frames):
    class EmaEntry(Parent):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            if not hasattr(self,'policy_events'):self.policy_events=[]
        def evaluate(self,**kwargs):
            at=kwargs['minute']+timedelta(minutes=1)
            # Match the parent's watch expiry before snapshotting; never resurrect stale watch.
            self.can_signal('BULLISH',at)
            before={side:dict(p) for side,p in self.pending.items()}
            watch=(self.watch_side,self.watch_at)
            event_start=len(self.policy_events)
            entries,checks=super().evaluate(**kwargs)
            if not entries:return entries,checks
            side=self.owner
            matching=[c for c in checks if c.get('status')=='ENTRY' and c['direction']==side]
            if len(entries)!=1 or len(matching)!=1 or side not in before:raise ValueError('CONFIRMATION_IDENTITY_MISMATCH')
            check=matching[0];boundary=at.replace(minute=at.minute//5*5,second=0,microsecond=0)
            evidence=frame_check(side,frames.get(boundary),at)
            check['ema10_entry']=evidence
            self.policy_events.append(dict(event='EMA10_ENTRY_CHECK',time=at.isoformat(),direction=side,
                setup_available=check['signal_available_at'],baseline_confirmed=True,**evidence))
            if evidence['passed']:return entries,checks
            candidate=before[side]
            if candidate['available'].isoformat()!=check['signal_available_at']:raise ValueError('CANDIDATE_IDENTITY_MISMATCH')
            if candidate.get('armed_at') is None:candidate['armed_at']=kwargs['minute']
            self.owner='NONE';self.active=None
            self.pending[side]=candidate
            self.watch_side,self.watch_at=watch
            check.update(status='EMA10_ENTRY_WAIT',reasons=list(evidence['reasons']))
            for event in self.policy_events[event_start:]:
                if event.get('event')=='COMBINED_ENTRY_DECISION' and event.get('outcome')=='PASS':
                    event.update(outcome='WAIT_EMA10_ENTRY',baseline_confirmed=True)
            # previous minute snapshot remains current; no stale confirmation latch.
            return [],checks
    return EmaEntry


def baseline2_gate(engine,frames):
    """Original lifecycle, 5m checks, unlimited time window, no persistence veto."""
    import textwrap
    from hilega_five_min_confirmation_research import five_gate
    Base=engine.WmaGapGate
    source=textwrap.dedent(inspect.getsource(Base.evaluate))
    old="if not persistence:reasons.append('WAIT_LATER_PERSISTENCE')"
    if source.count(old)!=1:raise ValueError('BASELINE2_PERSISTENCE_ANCHOR_MISMATCH')
    source=source.replace(old,'# Persistence remains diagnostic only; not an entry veto.',1)
    filename='<hilega-baseline2-no-persistence>'
    linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
    namespace=dict(Base.evaluate.__globals__)
    exec(compile(source,filename,'exec'),namespace)
    NoPersistence=type('Baseline2NoPersistence',(Base,),{'evaluate':namespace['evaluate']})
    Boundary=five_gate(NoPersistence,continued=True)
    class ValidatedBoundary(Boundary):
        def evaluate(self,**kwargs):
            entries,checks=super().evaluate(**kwargs)
            for c in checks:c.update(persistence_required=False,candidate_time_expiry_enabled=False,policy_name='EXISTING_BASELINE_2')
            return entries,checks
    return entry_gate(ValidatedBoundary,frames)


def add_variants(engine,baseline,old,new,Gate,NewGate,fresh,p,day,raw,warm,asof):
    frames=build_frames(engine,day,raw,warm,p.dt)
    variants=dict(EXISTING=baseline,PREVIOUS_AND=old,FRESH_AND=new)
    for key,parent,replay in (
        ('EXISTING',engine.WmaGapGate,engine.replay),
        ('PREVIOUS_AND',Gate,engine.replay),
        ('FRESH_AND',NewGate,fresh.fresh_replay(engine))):
        variants[key+'_EMA10_ENTRY']=p.simulate(SimpleNamespace(WmaGapGate=entry_gate(parent,frames),replay=replay),day,raw,warm,asof,'CURRENT')
    variants['EXISTING_BASELINE_2']=p.simulate(SimpleNamespace(WmaGapGate=baseline2_gate(engine,frames),replay=engine.replay),day,raw,warm,asof,'CURRENT')
    return variants


def write_reports(output,days,results,coverage,provenance,version,unused,stats):
    import hilega_existing_ema10_wma_combined_last10_research as base
    control_root=Path('data/research/hilega-and-fresh-setup-3months-20261016')
    control=json.loads((control_root/'report.json').read_text())
    if control.get('status')!='COMPLETE' or control.get('strategy_version')!=version:raise ValueError('COMPLETE_THREE_MONTH_CONTROL_REQUIRED')
    for day,variants in results.items():
        if provenance[day]['input_sha256']!=control['provenance'][day]['input_sha256']:raise ValueError('CONTROL_INPUT_MISMATCH:'+day)
        saved=json.loads((control_root/'sessions'/(day+'.json')).read_text())
        for key in BASES:
            if stats.signature(saved[key]['trades'])!=stats.signature(variants[key]['trades']):raise ValueError('CONTROL_POLICY_MISMATCH:'+day+':'+key)
        provenance[day]['three_month_control_parity']='PASS'
    totals={k:stats.stats([t for day in sorted(results) for t in results[day][k]['trades']]) for k in POLICIES}
    complete=len(results)==len(days)
    lines=['# Confirmed entry + full-candle EMA10 support','',WARNING,'',
        f"Status: {'COMPLETE' if complete else 'INCOMPLETE'}; coverage {len(results)}/{len(days)} sessions.",'',
        '| Policy | Trades | Winning points | Losing points | Net points | Change vs own baseline | Winners | Losers | Flat | Closed-trade drawdown |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for key in POLICIES:
        s=totals[key];parent='EXISTING' if key=='EXISTING_BASELINE_2' else key.removesuffix('_EMA10_ENTRY')
        lines.append(f"| {key} | {s['trades']} | {s['gross_winning_points']:+.2f} | {-s['gross_losing_points']:.2f} | {s['points']:+.2f} | {s['points']-totals[parent]['points']:+.2f} | {s['winners']} | {s['losers']} | {s['flat']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','| Date | '+' | '.join(POLICIES)+' |','|---|'+'---:|'*len(POLICIES)]
    detail=['# Signal-wise actual entry / exit / points','',WARNING,'',
        'Times IST. A dash means no actual entry from that exact setup, not proof of direct rejection. WAIT_EMA10_ENTRY retains the original candidate only within its existing window. BLOCKED_WMA_LOCK consumes it. See entry-decisions.csv for explicit outcomes. Different setup identities can produce the same actual trade.','']
    trades=[];events=[]
    for day,v in sorted(results.items()):
        lines.append('| '+day+' | '+' | '.join(f"{stats.stats(v[k]['trades'])['points']:+.2f}" for k in POLICIES)+' |')
        identities={(t['direction'],t['signal_time']) for k in POLICIES for t in v[k]['trades']}
        for k in POLICIES:
            trades.extend(dict(t,policy=k,session_date=day) for t in v[k]['trades'])
            for e in v[k].get('policy_events',[]):
                if e['event'] not in ('EMA10_ENTRY_CHECK','COMBINED_ENTRY_DECISION'):continue
                identities.add((e['direction'],e['setup_available']))
                events.append(dict(session_date=day,policy=k,**e))
        detail+=['','## '+day,'','| Direction | Setup available | '+' | '.join(POLICIES)+' |','|---|---|'+'---|'*len(POLICIES)]
        for side,signal in sorted(identities,key=lambda z:(z[1],z[0])):
            cells=[base.cell([t for t in v[k]['trades'] if (t['direction'],t['signal_time'])==(side,signal)]) for k in POLICIES]
            detail.append('| '+side+' | '+signal[11:16]+' | '+' | '.join(cells)+' |')
    report=dict(model=MODEL,status='COMPLETE' if complete else 'INCOMPLETE',session_dates=days,strategy_version=version,
        coverage=coverage,provenance=provenance,comparisons=totals,warning=WARNING,orders_sent=False,observation_only=True)
    (output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
    (output/'daily-signal-comparison.md').write_text('\n'.join(detail)+'\n')
    validation=['# Completed five-minute EMA10 entry validation','',
        'Checks below occur only after that policy fully confirms an entry. WAIT is not an executed trade. Times IST.','',
        '| Date | Policy | Setup | Decision | Direction | Candle label | Open | High | Low | Close | EMA10 | EMA10 slope | Outcome / reason |',
        '|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|']
    for e in events:
        if e['event']!='EMA10_ENTRY_CHECK':continue
        vals=[f"{e[k]:.3f}" if e.get(k) is not None else '—' for k in ('open','high','low','close','ema10','ema10_slope')]
        outcome='PASS' if e['passed'] else 'WAIT: '+', '.join(e['reasons'])
        validation.append('| '+' | '.join([e['session_date'],e['policy'],e['setup_available'][11:16],e['time'][11:16],e['direction'],e.get('candle_label','—')[11:16]]+vals+[outcome])+' |')
    (output/'ema10-entry-validation.md').write_text('\n'.join(validation)+'\n')
    for name,rows in (('trades.csv',trades),('losing-trades.csv',[t for t in trades if t['points']<0]),('entry-decisions.csv',events)):
        fields=sorted({k for row in rows for k in row}) or ['session_date','policy']
        with (output/name).open('w',newline='') as f:
            writer=csv.DictWriter(f,fields);writer.writeheader()
            writer.writerows({k:json.dumps(v,default=str) if isinstance(v,(dict,list)) else v for k,v in row.items()} for row in rows)
    print('\n'.join(lines))
    if len(days)==1:print('\n'.join(detail));print('\n'.join(validation))
    print('SIGNAL TABLE:',output/'daily-signal-comparison.md')
    print('EMA VALIDATION:',output/'ema10-entry-validation.md')


class Checks(unittest.TestCase):
    at=datetime.fromisoformat('2026-10-16T10:03:00+05:30')
    def frame(self,**kw):
        return dict(dict(open=102,high=104,low=101,close=103,ema10=100,previous_ema10=99,
            available_at='2026-10-16T10:00:00+05:30'),**kw)
    def test_bullish_full_candle(self):self.assertTrue(frame_check('BULLISH',self.frame(),self.at)['passed'])
    def test_single_day_only(self):
        self.assertEqual(single_session('2026-10-14',['2026-10-13','2026-10-14','2026-10-15'],'2026-07-16','2026-10-16','2026-10-16'),['2026-10-14'])
    def test_single_extra_day(self):
        self.assertEqual(single_session('2026-10-16',[],'2026-07-16','2026-10-16','2026-10-16'),['2026-10-16'])
    def test_unavailable_single_day_rejected(self):
        with self.assertRaisesRegex(ValueError,'UNAVAILABLE'):
            single_session('2026-10-11',[],'2026-07-16','2026-10-16','2026-10-16')
    def test_out_of_range_rejected(self):
        with self.assertRaisesRegex(ValueError,'OUTSIDE'):
            single_session('2026-07-15',[],'2026-07-16','2026-10-16','2026-10-16')
    def test_noncanonical_date_rejected(self):
        with self.assertRaisesRegex(ValueError,'YYYY_MM_DD'):
            single_session('2026-8-26',[],'2026-07-16','2026-10-16','2026-10-16')
    def test_bearish_full_candle(self):self.assertTrue(frame_check('BEARISH',self.frame(ema10=105,previous_ema10=106),self.at)['passed'])
    def test_wick_fails(self):self.assertFalse(frame_check('BULLISH',self.frame(low=99),self.at)['passed'])
    def test_touch_fails(self):self.assertFalse(frame_check('BULLISH',self.frame(low=100),self.at)['passed'])
    def test_bearish_touch_fails(self):self.assertFalse(frame_check('BEARISH',self.frame(ema10=104,previous_ema10=105),self.at)['passed'])
    def test_falling_ema_fails_bullish(self):self.assertFalse(frame_check('BULLISH',self.frame(previous_ema10=101),self.at)['passed'])
    def test_flat_ema_fails(self):self.assertFalse(frame_check('BULLISH',self.frame(previous_ema10=100),self.at)['passed'])
    def test_future_rejected(self):
        with self.assertRaises(ValueError):frame_check('BULLISH',self.frame(available_at='2026-10-16T10:05:00+05:30'),self.at)
    def test_stale_rejected(self):
        with self.assertRaises(ValueError):frame_check('BULLISH',self.frame(available_at='2026-10-16T09:55:00+05:30'),self.at)
    def test_missing_waits(self):self.assertFalse(frame_check('BULLISH',None,self.at)['passed'])
    def harness(self,passed=True,veto=False,frame=None):
        at=self.at
        class Base:
            def __init__(self):
                self.pending={'BULLISH':dict(available=at-timedelta(minutes=3),armed_at=at-timedelta(minutes=2),event=None)}
                self.owner='NONE';self.active=None;self.watch_side='BULLISH';self.watch_at=at-timedelta(minutes=3)
            def can_signal(self,*a):return True
            def evaluate(self,**kw):
                self.previous=kw['minute']
                if not passed:return [],[]
                p=self.pending.pop('BULLISH')
                if veto:return [],[]
                self.owner='BULLISH';self.active=True;self.watch_side=None;self.watch_at=None
                return ['entry'],[dict(direction='BULLISH',status='ENTRY',signal_available_at=p['available'].isoformat(),reasons=[])]
            def close(self):return 'ORIGINAL_EXIT'
        return entry_gate(Base,{at.replace(minute=0):self.frame(low=99) if frame is None else frame})()
    def test_failed_gate_restores_original_candidate_and_keeps_history(self):
        g=self.harness();original=dict(g.pending['BULLISH']);minute=self.at-timedelta(minutes=1)
        entries,checks=g.evaluate(minute=minute)
        self.assertFalse(entries);self.assertEqual(g.pending['BULLISH'],original)
        self.assertEqual(g.owner,'NONE');self.assertIsNone(g.active);self.assertEqual(g.previous,minute)
        self.assertEqual(checks[0]['status'],'EMA10_ENTRY_WAIT')
    def test_no_baseline_confirmation_no_ema_entry(self):
        g=self.harness(passed=False);self.assertEqual(g.evaluate(minute=self.at-timedelta(minutes=1)),([],[]));self.assertFalse(g.policy_events)
    def test_wma_veto_not_resurrected(self):
        g=self.harness(veto=True);g.evaluate(minute=self.at-timedelta(minutes=1));self.assertFalse(g.pending);self.assertFalse(g.policy_events)
    def test_exit_unmodified(self):self.assertEqual(self.harness().close(),'ORIGINAL_EXIT')
    def test_supported_original_confirmation_enters(self):
        g=self.harness(frame=self.frame());entries,checks=g.evaluate(minute=self.at-timedelta(minutes=1))
        self.assertEqual(entries,['entry']);self.assertEqual(g.owner,'BULLISH');self.assertFalse(g.pending)
        self.assertTrue(checks[0]['ema10_entry']['passed'])
    def test_wait_can_pass_on_later_fresh_check(self):
        frame=self.frame(low=99);g=self.harness(frame=frame)
        self.assertFalse(g.evaluate(minute=self.at-timedelta(minutes=1))[0])
        frame['low']=101
        self.assertEqual(g.evaluate(minute=self.at)[0],['entry'])
    def test_ema_uses_close_alpha_and_cutoff_not_partial_bar(self):
        captured=[]
        class Engine:
            candles=staticmethod(lambda rows: rows)
            @staticmethod
            def aggregate_exact_5m(rows,day,**kw):
                captured.extend(rows)
                return [SimpleNamespace(ts=datetime.combine(day,datetime.min.time(),tzinfo=Checks.at.tzinfo).replace(hour=9,minute=15),
                    open=100,high=102,low=99,close=100 if day.day!=16 else 102)]
        warm=[('2026-09-01',[]) for _ in range(20)]
        # Synthetic deterministic bars isolate seeding and last cutoff-minute handling.
        raw=[dict(timestamp='2026-10-16T14:55:00+05:30'),dict(timestamp='2026-10-16T14:54:00+05:30')]
        frames=build_frames(Engine,'2026-10-16',raw,warm,datetime.fromisoformat)
        f=next(iter(frames.values()))
        self.assertAlmostEqual(f['previous_ema10'],100);self.assertAlmostEqual(f['ema10'],100+4/11)
        self.assertEqual(captured,[raw[1]]);self.assertEqual(len(raw),2)

    def baseline2_harness(self,ema_ok=True):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        at=datetime.fromisoformat('2026-10-16T14:20:00+05:30')
        frames={}
        for minutes in range(0,36,5):
            boundary=at+timedelta(minutes=minutes)
            frames[boundary]=dict(open=100,high=101 if ema_ok else 107,low=99,close=100,
                ema10=105,previous_ema10=106,available_at=boundary.isoformat())
        g=baseline2_gate(engine,frames)(opposite_switch=True)
        event=engine.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at-timedelta(minutes=5),None,'IDLE','ARMED',details={})
        g.signal(event,at)
        def tick(clock,ema=48,strength=1):
            t=datetime.fromisoformat('2026-10-16T'+clock+':00+05:30')
            snap=SimpleNamespace(ready=True,rsi9=ema-1,ema3_rsi=ema,wma21_rsi=49)
            ref=SimpleNamespace(ready=True,wma21_rsi=49+strength)
            return g.evaluate(minute=t-timedelta(minutes=1),current=snap,reference=ref,price=100)
        return g,tick,engine
    def test_baseline2_no_intermediate_minute_entry(self):
        g,tick,_=self.baseline2_harness();tick('14:20')
        self.assertEqual(tick('14:21',ema=45),([],[]));self.assertIsNone(g.pending['BEARISH']['armed_at'])
    def test_baseline2_first_qualifying_5m_needs_no_persistence(self):
        g,tick,_=self.baseline2_harness();tick('14:20')
        entries,checks=tick('14:25',ema=47)
        self.assertTrue(entries);self.assertFalse(checks[0]['persistence_pass']);self.assertFalse(checks[0]['persistence_required'])
    def test_baseline2_no_time_expiry(self):
        g,tick,_=self.baseline2_harness();tick('14:20');tick('14:25');tick('14:30');tick('14:31')
        self.assertIn('BEARISH',g.pending)
        self.assertTrue(tick('14:35',ema=47)[0])
    def test_baseline2_strength_still_required(self):
        g,tick,_=self.baseline2_harness();tick('14:20')
        entries,checks=tick('14:25',ema=47,strength=.74)
        self.assertFalse(entries);self.assertIn('WMA_THRESHOLD_NOT_MET',checks[0]['reasons'])
    def test_baseline2_expansion_uses_5m_not_minute(self):
        g,tick,_=self.baseline2_harness();tick('14:20');tick('14:24',ema=40)
        entries,checks=tick('14:25',ema=47)
        self.assertTrue(entries);self.assertEqual(checks[0]['previous_gap'],1)
    def test_baseline2_ema_rejection_retains_candidate_beyond_ten(self):
        g,tick,_=self.baseline2_harness(ema_ok=False);tick('14:20');tick('14:25')
        entries,checks=tick('14:35',ema=47)
        # A gap is only valid against consecutive completed 5m readings.
        self.assertFalse(entries);self.assertIn('BEARISH',g.pending)
        entries,checks=tick('14:40',ema=46)
        self.assertFalse(entries);self.assertEqual(checks[0]['status'],'EMA10_ENTRY_WAIT')
        self.assertEqual(g.owner,'NONE');self.assertIn('BEARISH',g.pending)
    def test_baseline2_cutoff_still_blocks(self):
        g,tick,_=self.baseline2_harness();tick('14:50')
        entries,checks=tick('14:55',ema=47)
        self.assertFalse(entries);self.assertIn('SESSION_CUTOFF',checks[0]['reasons'])
    def test_baseline2_original_opposite_setup_cancels(self):
        g,tick,engine=self.baseline2_harness();tick('14:20')
        at=datetime.fromisoformat('2026-10-16T14:25:00+05:30')
        event=engine.StrategyEvent('ENTRY_BULLISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={})
        g.signal(event,at)
        self.assertNotIn('BEARISH',g.pending);self.assertIn('BULLISH',g.pending)


def main():
    import hilega_and_fresh_setup_30_sessions_research as batch
    if '--test' in __import__('sys').argv:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        if not result.wasSuccessful():raise SystemExit(1)
        batch.main()  # Original control and composition tests, too.
        return
    source=inspect.getsource(batch.main)
    def replace(old,new):
        nonlocal source
        if source.count(old)!=1:raise ValueError('BATCH_SOURCE_ANCHOR_MISMATCH:'+old)
        source=source.replace(old,new,1)
    replace("default=30)","default=65)")
    replace("ap.add_argument('--test',action='store_true')",
        "ap.add_argument('--test',action='store_true')\n    ap.add_argument('--date',help='Replay only this saved trading session, YYYY-MM-DD')")
    replace('args=ap.parse_args()',
        "args=ap.parse_args()\n    if args.date:\n        if any(x in ('--sessions','--end-date') or x.startswith(('--sessions=','--end-date=')) for x in sys.argv[1:]):ap.error('--date cannot be combined with --sessions or --end-date')\n        args.end_date=args.date\n        args.sessions=1\n        if not any(x=='--output' or x.startswith('--output=') for x in sys.argv[1:]):args.output=Path('data/research/hilega-ema10-entry-day-'+args.date.replace('-',''))")
    replace("days=select_sessions(calendar,parent['start_date'],args.end_date,args.sessions,extra['session_date'])",
        "days=single_session(args.date,calendar,parent['start_date'],extra['session_date'],extra['session_date']) if args.date else select_sessions(calendar,parent['start_date'],args.end_date,args.sessions,extra['session_date'])")
    replace("data/research/hilega-and-fresh-setup-30sessions-20261016","data/research/hilega-ema10-entry-with-baseline2-3months-20261016")
    replace('variants=dict(EXISTING=baseline,PREVIOUS_AND=old,FRESH_AND=new)',
        'variants=add_variants(engine,baseline,old,new,Gate,NewGate,fresh,p,day,raw,warm,asof)')
    namespace=dict(batch.main.__globals__,add_variants=add_variants,write_reports=write_reports,single_session=single_session,sys=sys)
    filename='<hilega-ema10-entry-batch>'
    linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
    exec(compile(source,filename,'exec'),namespace)
    namespace['main']()


if __name__=='__main__':main()
