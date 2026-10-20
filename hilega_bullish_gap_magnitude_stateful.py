"""Research-only stateful bullish gap/magnitude replay, layered on V20.

Pass the existing replay CLI arguments, or --summarize-root ROOT repeatedly.
No orders or live configuration changes. Exits and bearish entry rules retained.
"""
import inspect
import argparse
import json
import linecache
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest
import hilega_ema10_full_candle_entry_3months_research as research

MODEL='BULLISH_GAP2_FULL_WMA2_STATEFUL_V1'
EXTRAS=('BULLISH_GAP2','BULLISH_GAP2_FULL_WMA2')
SPECS=[('BULLISH_GAP2',2,0),('BULLISH_GAP2_FULL_WMA2',2,2)]
ROOTS=(Path('data/research/hilega-touch-month-through-20261016'),Path('data/research/hilega-ema10-touch-wait-20261019-v2'))
RULE_TEXT=('Bullish signal must have completed EMA3(RSI9)-WMA21(RSI9)>=2. '
    'Combined variant additionally requires entry WMA minus the WMA immediately BEFORE the qualified signal >=2. '
    'Magnitude is checked only on an otherwise valid bullish entry. A failed magnitude check uses the existing follow-up lifecycle: '
    'EMA10 touch retains the original signal for the next boundary; without touch discard the reference and seek a fresh signal. '
    'Low-gap candles cannot qualify a bullish signal or override an opposite watch. Pending candidate monitoring continues. '
    'Bearish checks, active exits and cutoff are unchanged; actual subsequent trades may differ because positions differ. Research only; gross NIFTY points without costs.')

def numeric(value):
    return value is not None and not isinstance(value,bool) and math.isfinite(float(value))

def apply_gap(evidence,frame,minimum):
    e=frame.get('ema3_rsi') if frame else None;w=frame.get('wma21_rsi') if frame else None
    gap=float(e)-float(w) if numeric(e) and numeric(w) else None
    passed=gap is not None and gap>=minimum
    evidence.update(bullish_signal_gap=gap,bullish_signal_gap_min=minimum,bullish_signal_gap_pass=passed)
    if not passed:
        evidence['passed']=False;evidence['reasons'].append('BULLISH_SIGNAL_GAP_BELOW_MIN_OR_MISSING')

def apply_magnitude(evidence,waiting,frames,at,minimum):
    signal=frames.get(waiting['time']);entry=frames.get(at)
    previous=signal.get('previous_wma21_rsi') if signal else None
    current=entry.get('wma21_rsi') if entry else None
    valid=signal is not None and entry is not None and signal.get('available_at')==waiting['time'].isoformat() and entry.get('available_at')==at.isoformat()
    full=float(current)-float(previous) if valid and numeric(previous) and numeric(current) else None
    passed=full is not None and full>=minimum
    evidence.update(bullish_pre_signal_wma=previous,bullish_entry_wma=current,full_wma_magnitude=full,full_wma_min=minimum,full_wma_pass=passed)
    if not passed:
        evidence['passed']=False;evidence['reasons'].append('BULLISH_FULL_WMA_MAGNITUDE_BELOW_MIN_OR_MISSING')

def filtered_factory():
    # Clone only the entry-gate factory. Source anchors fail closed if V20 changes.
    source=inspect.getsource(research.entry_gate)
    def change(old,new):
        nonlocal source
        if source.count(old)!=1:raise ValueError('V20_FILTER_SOURCE_ANCHOR_MISMATCH:'+old)
        source=source.replace(old,new,1)
    change('touch_wait=False):','touch_wait=False,signal_gap_min=0,full_wma_min=0):')
    anchor="                if not price_pass and not fresh_pass:evidence['reasons'].append('FOLLOWUP_PRICE_AND_FRESH_CHECKS_FAILED')"
    change(anchor,anchor+"\n                if side=='BULLISH' and full_wma_min>0:apply_magnitude(evidence,waiting,frames,at,full_wma_min)")
    anchor="                if followup and evidence['passed']:"
    change(anchor,"                if side=='BULLISH' and signal_gap_min>0:apply_gap(evidence,frames.get(boundary),signal_gap_min)\n"+anchor)
    namespace=dict(research.entry_gate.__globals__,apply_gap=apply_gap,apply_magnitude=apply_magnitude)
    filename='<hilega-bullish-stateful-entry-filter>'
    linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
    exec(compile(source,filename,'exec'),namespace)
    return namespace['entry_gate']

def extend_variants(original):
    factory=filtered_factory()
    def add(engine,baseline,old,new,Gate,NewGate,fresh,p,day,raw,warm,asof,wm,lock,threshold):
        variants=original(engine,baseline,old,new,Gate,NewGate,fresh,p,day,raw,warm,asof,wm,lock,threshold)
        frames=research.attach_completed_rsi(research.build_frames(engine,day,raw,warm,p.dt),baseline,p.dt)
        for name,gap_min,magnitude_min in SPECS:
            parent=research.direct_five_base(engine.WmaGapGate,no_expiry=True)
            watch=research.qualified_opposite_watch_gate(parent,frames,engine.direction,require_wma_permission=False,signal_rule='CLOSE_RSI40_60_SLOPE_COLOUR',until_opposite=True)
            class GapWatch(watch):
                def qualifies(self,side,at):
                    if not super().qualifies(side,at):return False
                    if side!='BULLISH':return True
                    ev=dict(passed=True,reasons=[]);apply_gap(ev,frames.get(at),gap_min)
                    return ev['passed']
            gate=factory(GapWatch,frames,rule='CLOSE_RSI40_60_SLOPE_COLOUR',followup=True,continue_waiting=False,
                until_opposite=True,reset_reference_only=True,touch_wait=True,signal_gap_min=gap_min,full_wma_min=magnitude_min)
            replay=research.direct_fresh_replay(engine,fresh,retry_followup=True,until_opposite=True)
            value=p.simulate(SimpleNamespace(WmaGapGate=gate,replay=replay),day,raw,warm,asof,'CURRENT')
            value['research_entry_rules']=dict(variants['FRESH_AND_EMA10_ENTRY']['research_entry_rules'],bullish_signal_gap_min=gap_min,bullish_full_wma_min=magnitude_min,filter_scope='BULLISH_ONLY',stateful=True)
            variants[name]=value
        return variants
    return add

def compact(output,results,stats):
    policies=('EXISTING','FRESH_AND','FRESH_AND_EMA10_ENTRY')+EXTRAS
    lines=['# Stateful bullish gap / WMA magnitude comparison','',RULE_TEXT,'',
        f"Coverage: {len(results)} trading sessions; {min(results) if results else 'NONE'} through {max(results) if results else 'NONE'}.",'',
        '| Scope | Policy | Trades | Winning points | Losing points | Net points | Drawdown |',
        '|---|---|---:|---:|---:|---:|---:|']
    for scope in ('ALL','BULLISH','BEARISH'):
        for key in policies:
            trades=[t for d in sorted(results) for t in results[d][key]['trades'] if scope=='ALL' or t['direction']==scope]
            s=stats.stats(trades)
            lines.append(f"| {scope} | {key} | {s['trades']} | {s['gross_winning_points']:+.2f} | {-s['gross_losing_points']:.2f} | {s['points']:+.2f} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','## Monthly consistency','','Calendar months at the edges may be partial. All periods are previously examined research data, not independent holdouts.','',
        '| Month | First session | Last session | Sessions | Policy | Bullish points | All-trade points | Change vs EMA10-touch control |',
        '|---|---|---|---:|---|---:|---:|---:|']
    for month in sorted({day[:7] for day in results}):
        days=sorted(d for d in results if d.startswith(month))
        control=sum(t['points'] for d in days for t in results[d]['FRESH_AND_EMA10_ENTRY']['trades'])
        for key in policies:
            trades=[t for d in days for t in results[d][key]['trades']]
            bullish=sum(t['points'] for t in trades if t['direction']=='BULLISH');total=sum(t['points'] for t in trades)
            lines.append(f'| {month} | {days[0]} | {days[-1]} | {len(days)} | {key} | {bullish:+.2f} | {total:+.2f} | {total-control:+.2f} |')
    lines+=['','## Parameters','','| Policy | Bullish signal gap minimum | Full WMA magnitude minimum |','|---|---:|---:|']
    lines += [f'| {name} | {gap} | {magnitude if magnitude else "Disabled"} |' for name,gap,magnitude in SPECS]
    lines+=['','## Actual trades','','| Date | Policy | Direction | Setup | Entry | Exit | NIFTY points |','|---|---|---|---|---|---|---:|']
    for day,variants in sorted(results.items()):
        for key in policies:
            for t in variants[key]['trades']:
                lines.append(f"| {day} | {key} | {t['direction']} | {t['signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['points']:+.2f} |")
    lines+=['','## Explicit bullish filter checks','','| Date | Policy | Decision | Setup | Stage | Signal gap | Full WMA rise | Pass | Reason |','|---|---|---|---|---|---:|---:|---|---|']
    for day,variants in sorted(results.items()):
        for key in EXTRAS:
            for e in variants[key].get('policy_events',[]):
                if 'bullish_signal_gap_pass' not in e and 'full_wma_pass' not in e:continue
                lines.append('| '+' | '.join(map(str,(day,key,e['time'][11:16],e['setup_available'][11:16],e['event'],e.get('bullish_signal_gap','—'),e.get('full_wma_magnitude','—'),e['passed'],', '.join(e.get('reasons',[])))))+' |')
    (output/'stateful-comparison.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines[:20]));print('STATEFUL TABLE:',output/'stateful-comparison.md')

def checked_writer(original):
    def write(output,days,results,coverage,provenance,version,unused,stats):
        for day,variants in results.items():
            roots=[r for r in ROOTS if (r/'sessions'/(day+'.json')).exists()]
            if len(roots)!=1:raise ValueError('UNIQUE_SAVED_V20_CONTROL_REQUIRED:'+day)
            root=roots[0];control=json.loads((root/'report.json').read_text())
            if control.get('model')!='FRESH_DIRECT_5M_RSI40_60_EMA_TOUCH_WAIT_V20':raise ValueError('V20_CONTROL_MODEL_REQUIRED')
            if control['provenance'][day]['input_sha256']!=provenance[day]['input_sha256']:raise ValueError('V20_INPUT_HASH_MISMATCH:'+day)
            saved=json.loads((root/'sessions'/(day+'.json')).read_text())
            for key in ('EXISTING','FRESH_AND','FRESH_AND_EMA10_ENTRY'):
                if stats.signature(saved[key]['trades'])!=stats.signature(variants[key]['trades']):raise ValueError('UNCHANGED_V20_CONTROL_MISMATCH:'+day+':'+key)
            provenance[day]['v20_control_parity']='PASS'
        original(output,days,results,coverage,provenance,version,unused,stats)
        compact(output,results,stats)
    return write

class Checks(unittest.TestCase):
    def test_sensitivity_grid_includes_original_pair_and_neighbours(self):
        specs=sensitivity_specs()
        self.assertEqual(len(specs),12)
        self.assertEqual(len({s[0] for s in specs}),12)
        for gap in (1.5,2,2.5):
            for magnitude in (1.8,2,2.2):
                self.assertTrue(any(g==gap and m==magnitude for _,g,m in specs))
    def test_thirty_sessions_include_end_without_duplicates(self):
        days=[f'2026-09-{i:02}' for i in range(1,31)]+['2026-10-19']
        chosen=summary_days(days+days,30,'2026-10-19')
        self.assertEqual(len(chosen),30);self.assertEqual(chosen[-1],'2026-10-19');self.assertEqual(chosen[0],'2026-09-02')
    def test_short_summary_coverage_rejected(self):
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):
            summary_days(['2026-10-19'],30,'2026-10-19')
    def test_summary_end_required(self):
        with self.assertRaisesRegex(ValueError,'END_SESSION'):
            summary_days(['2026-10-16'],1,'2026-10-19')
    def test_three_month_calendar_window(self):
        days=['2026-07-16','2026-07-17','2026-07-20','2026-10-16','2026-10-19']
        self.assertEqual(summary_days(days,None,'2026-10-19','2026-07-19'),days[2:])
    def test_magnitude_veto_restores_flat_then_touch_wait_can_enter(self):
        at=datetime.fromisoformat('2026-10-19T09:40:00+05:30');next_at=at+timedelta(minutes=5);last=next_at+timedelta(minutes=5)
        class Base:
            def __init__(self):
                self.pending={'BULLISH':dict(available=at,armed_at=None)};self.owner='NONE';self.active=None
                self.watch_side=None;self.watch_at=None;self.locked=False
            def can_signal(self,*a):return True
            def evaluate(self,**kw):
                p=self.pending.pop('BULLISH');self.owner='BULLISH';self.active=True
                return ['entry'],[dict(direction='BULLISH',status='ENTRY',signal_available_at=p['available'].isoformat(),reasons=[],wma_threshold_pass=True,gap_positive_pass=True,gap_expanding_pass=True)]
        def f(t,w,previous,rsi):
            return dict(available_at=t.isoformat(),rsi_available_at=t.isoformat(),open=101,high=105,low=99,close=103,ema10=100,previous_ema10=99,
                previous_rsi9=rsi-1,rsi9=rsi,ema3_rsi=w+3,wma21_rsi=w,previous_wma21_rsi=previous)
        frames={at:f(at,50,49,60),next_at:f(next_at,50.5,50,61),last:f(last,51,50.5,62)}
        g=filtered_factory()(Base,frames,rule='CLOSE_RSI40_60_SLOPE_COLOUR',followup=True,until_opposite=True,
            reset_reference_only=True,touch_wait=True,signal_gap_min=2,full_wma_min=2)()
        self.assertFalse(g.evaluate(minute=at-timedelta(minutes=1))[0])
        self.assertFalse(g.evaluate(minute=next_at-timedelta(minutes=1))[0])
        self.assertEqual(g.owner,'NONE');self.assertIsNone(g.active)
        self.assertEqual(g.followup_signal['time'],at)
        self.assertEqual(g.followup_signal['due'],last)
        self.assertTrue(g.evaluate(minute=last-timedelta(minutes=1))[0])
    def test_gap_equality_and_missing_fail_closed(self):
        for frame,expected in [(dict(ema3_rsi=52,wma21_rsi=50),True),(dict(ema3_rsi=51.9,wma21_rsi=50),False),({},False)]:
            e=dict(passed=True,reasons=[]);apply_gap(e,frame,2);self.assertEqual(e['passed'],expected)
    def test_full_magnitude_uses_previous_signal_not_signal(self):
        t=datetime.fromisoformat('2026-10-19T09:40:00+05:30');at=t+timedelta(minutes=5)
        frames={t:dict(available_at=t.isoformat(),previous_wma21_rsi=48.726,wma21_rsi=49.664),at:dict(available_at=at.isoformat(),wma21_rsi=50.636)}
        ev=dict(passed=True,reasons=[]);apply_magnitude(ev,dict(time=t),frames,at,2)
        self.assertAlmostEqual(ev['full_wma_magnitude'],1.91);self.assertFalse(ev['passed'])
        frames[at]['wma21_rsi']=50.726;ev=dict(passed=True,reasons=[])
        apply_magnitude(ev,dict(time=t),frames,at,2);self.assertTrue(ev['passed'])
    def test_factory_preserves_original(self):
        original=research.entry_gate
        self.assertIn('signal_gap_min',inspect.signature(filtered_factory()).parameters)
        self.assertIs(research.entry_gate,original)

def summary_days(days,count,end,start='2026-09-19'):
    if datetime.fromisoformat(start)>datetime.fromisoformat(end):raise ValueError('INVALID_SUMMARY_DATE_WINDOW')
    values=sorted(set(d for d in days if d<=end))
    if not values or values[-1]!=end:raise ValueError('SUMMARY_END_SESSION_REQUIRED')
    if count is not None:
        if count<1 or len(values)<count:raise ValueError('INSUFFICIENT_SUMMARY_TRADING_SESSIONS')
        return values[-count:]
    return [d for d in values if start<=d<=end]


def sensitivity_specs():
    def label(value):return str(value).replace('.','p')
    return [(f'BULLISH_GAP{label(gap)}',gap,0) for gap in (1.5,2,2.5)]+[
        (f'BULLISH_GAP{label(gap)}_FULL_WMA{label(magnitude)}',gap,magnitude)
        for gap in (1.5,2,2.5) for magnitude in (1.8,2,2.2)]


def main():
    global ROOTS,SPECS,EXTRAS,MODEL,RULE_TEXT
    controls=argparse.ArgumentParser(add_help=False)
    controls.add_argument('--control-root',type=Path,action='append')
    controls.add_argument('--sensitivity',action='store_true')
    control_args,remaining=controls.parse_known_args()
    if control_args.control_root:ROOTS=tuple(control_args.control_root)
    if control_args.sensitivity:
        SPECS=sensitivity_specs();EXTRAS=tuple(name for name,_,_ in SPECS)
        MODEL='BULLISH_GAP_WMA_STATEFUL_SENSITIVITY_V1'
        RULE_TEXT=('Research-only sensitivity grid: bullish signal gap minima 1.5,2,2.5; full WMA rise minima 1.8,2,2.2, plus gap-only controls. '
            'Exact thresholds are shown in the parameter table. Full rise is entry WMA minus WMA immediately BEFORE the qualified signal. '
            'A magnitude rejection waits only on EMA10 touch; otherwise discard the reference and seek fresh qualification. '
            'Signal gap also gates opposite-watch override. Existing bearish rules, exits and cutoff retained. '
            'Stateful replay; gross NIFTY points, costs excluded. All data already examined; no independent holdout or live changes.')
    sys.argv=[sys.argv[0]]+remaining
    if '--summarize-root' in sys.argv:
        ap=argparse.ArgumentParser()
        ap.add_argument('--summarize-root',type=Path,action='append',required=True)
        ap.add_argument('--output',type=Path,required=True)
        ap.add_argument('--summary-sessions',type=int)
        ap.add_argument('--start-date',default='2026-09-19')
        ap.add_argument('--end-date',default='2026-10-19')
        args=ap.parse_args();results={};proof={}
        control_days=set()
        for root in ROOTS:
            report=json.loads((root/'report.json').read_text())
            if report.get('model')!='FRESH_DIRECT_5M_RSI40_60_EMA_TOUCH_WAIT_V20' or report.get('status')!='COMPLETE':
                raise ValueError('COMPLETE_V20_SUMMARY_CONTROL_REQUIRED:'+str(root))
            control_days.update(report['session_dates'])
        expected=set(summary_days(control_days,args.summary_sessions,args.end_date,args.start_date))
        for root in args.summarize_root:
            report=json.loads((root/'report.json').read_text())
            if report.get('model')!=MODEL or report.get('status')!='COMPLETE':raise ValueError('COMPLETE_STATEFUL_REPORT_REQUIRED:'+str(root))
            for day in report['session_dates']:
                if day not in expected:continue
                if report['provenance'][day].get('v20_control_parity')!='PASS':raise ValueError('V20_CONTROL_PARITY_REQUIRED:'+day)
                if day in results:raise ValueError('DUPLICATE_SUMMARY_SESSION:'+day)
                results[day]=json.loads((root/'sessions'/(day+'.json')).read_text());proof[day]=report['provenance'][day]
        if set(results)!=expected:raise ValueError('SUMMARY_COVERAGE_MISMATCH:'+str(sorted(expected-set(results))))
        import hilega_pending_previous10_research as stats
        args.output.mkdir(parents=True,exist_ok=True);compact(args.output,results,stats)
        (args.output/'report.json').write_text(json.dumps(dict(model=MODEL,status='COMPLETE',session_dates=sorted(results),provenance=proof,rules=RULE_TEXT,orders_sent=False),indent=2)+'\n')
        return
    if '--test' in sys.argv:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        if not result.wasSuccessful():raise SystemExit(1)
        research.main();return
    # Changes apply only in this isolated CLI process, never to source files.
    research.add_variants=extend_variants(research.add_variants)
    research.write_reports=checked_writer(research.write_reports)
    research.POLICIES=research.POLICIES+EXTRAS
    research.MODEL=MODEL
    research.WARNING+=' '+RULE_TEXT
    research.main()

if __name__=='__main__':main()
