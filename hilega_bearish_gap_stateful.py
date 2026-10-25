"""Stateful bearish gap comparison with bullish 2/2 fixed. Research only.

Uses the same CLI arguments as hilega_bullish_gap_magnitude_stateful.py.
No orders, no live configuration edits; run tests on the Ubuntu VM.
"""
import inspect
import argparse
import json
import linecache
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
import hilega_bullish_gap_magnitude_stateful as base

SPECS=[('BULLISH_GAP2_FULL_WMA2',0),('BULL2_WMA2_BEAR_GAP2',2),('BULL2_WMA2_BEAR_GAP2p5',2.5)]
ORIGINAL_FACTORY=base.filtered_factory
ORIGINAL_COMPACT=base.compact
ORIGINAL_WRITER=base.checked_writer
CONTROL_ROOTS=[Path('data/research/hilega-sensitivity-through-20261016'),Path('data/research/hilega-sensitivity-20261019')]

def checked_writer(original):
    checked=ORIGINAL_WRITER(original)
    def write(output,days,results,coverage,provenance,version,warning,stats):
        for day,variants in results.items():
            roots=[root for root in CONTROL_ROOTS if (root/'sessions'/(day+'.json')).exists()]
            if len(roots)!=1:raise ValueError('UNIQUE_BULLISH_2_2_CONTROL_REQUIRED:'+day)
            root=roots[0];report=json.loads((root/'report.json').read_text())
            if report.get('status')!='COMPLETE' or report.get('model') not in ('BULLISH_GAP_WMA_STATEFUL_SENSITIVITY_V1','BULLISH_GAP2_FULL_WMA2_STATEFUL_V1'):
                raise ValueError('COMPLETE_BULLISH_CONTROL_REQUIRED:'+day)
            if report['provenance'][day]['input_sha256']!=provenance[day]['input_sha256']:
                raise ValueError('BULLISH_CONTROL_INPUT_MISMATCH:'+day)
            saved=json.loads((root/'sessions'/(day+'.json')).read_text())
            key='BULLISH_GAP2_FULL_WMA2'
            if stats.signature(saved[key]['trades'])!=stats.signature(variants[key]['trades']):
                raise ValueError('UNCHANGED_BULLISH_2_2_CONTROL_MISMATCH:'+day)
            provenance[day]['bullish_2_2_control_parity']='PASS'
        return checked(output,days,results,coverage,provenance,version,warning,stats)
    return write

def bearish_gap(evidence,frame,minimum):
    ema=frame.get('ema3_rsi') if frame else None
    wma=frame.get('wma21_rsi') if frame else None
    value=float(wma)-float(ema) if base.numeric(ema) and base.numeric(wma) else None
    passed=value is not None and value>=minimum
    evidence.update(bearish_signal_gap=value,bearish_signal_gap_min=minimum,bearish_signal_gap_pass=passed)
    if not passed:
        evidence['passed']=False
        evidence['reasons'].append('BEARISH_SIGNAL_GAP_BELOW_MIN_OR_MISSING')

def filtered_factory():
    original=ORIGINAL_FACTORY();source=inspect.getsource(original)
    replacements=[('full_wma_min=0):','full_wma_min=0,bearish_gap_min=0):'),
        ("                if followup and evidence['passed']:",
         "                if side=='BEARISH' and bearish_gap_min>0:bearish_gap(evidence,frames.get(boundary),bearish_gap_min)\n                if followup and evidence['passed']:")]
    for old,new in replacements:
        if source.count(old)!=1:raise ValueError('BEARISH_FACTORY_SOURCE_ANCHOR_MISMATCH:'+old)
        source=source.replace(old,new,1)
    namespace=dict(original.__globals__,bearish_gap=bearish_gap)
    filename='<hilega-bearish-gap-stateful>'
    linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
    exec(compile(source,filename,'exec'),namespace)
    return namespace['entry_gate']

def extend_variants(original):
    factory=filtered_factory();r=base.research
    def add(engine,baseline,old,new,Gate,NewGate,fresh,p,day,raw,warm,asof,wm,lock,threshold):
        variants=original(engine,baseline,old,new,Gate,NewGate,fresh,p,day,raw,warm,asof,wm,lock,threshold)
        frames=r.attach_completed_rsi(r.build_frames(engine,day,raw,warm,p.dt),baseline,p.dt)
        for name,bear_min in SPECS:
            parent=r.direct_five_base(engine.WmaGapGate,no_expiry=True)
            watch=r.qualified_opposite_watch_gate(parent,frames,engine.direction,require_wma_permission=False,
                signal_rule='CLOSE_RSI40_60_SLOPE_COLOUR',until_opposite=True)
            class DirectionGapWatch(watch):
                def qualifies(self,side,at):
                    if not super().qualifies(side,at):return False
                    ev=dict(passed=True,reasons=[])
                    if side=='BULLISH':base.apply_gap(ev,frames.get(at),2)
                    elif bear_min>0:bearish_gap(ev,frames.get(at),bear_min)
                    return ev['passed']
            gate=factory(DirectionGapWatch,frames,rule='CLOSE_RSI40_60_SLOPE_COLOUR',followup=True,
                continue_waiting=False,until_opposite=True,reset_reference_only=True,touch_wait=True,
                signal_gap_min=2,full_wma_min=2,bearish_gap_min=bear_min)
            replay=r.direct_fresh_replay(engine,fresh,retry_followup=True,until_opposite=True)
            value=p.simulate(SimpleNamespace(WmaGapGate=gate,replay=replay),day,raw,warm,asof,'CURRENT')
            value['research_entry_rules']=dict(variants['FRESH_AND_EMA10_ENTRY']['research_entry_rules'],
                bullish_signal_gap_min=2,bullish_full_wma_min=2,bearish_signal_gap_min=bear_min,
                bearish_full_wma_min=0,stateful=True)
            variants[name]=value
        return variants
    return add

def cell(trades):
    return '<br>'.join(f"{t['entry_time'][11:16]}–{t['exit_time'][11:16]} · {t['points']:+.2f}" for t in trades) or '—'

def compact(output,results,stats):
    ORIGINAL_COMPACT(output,results,stats)
    lines=['# Stateful bearish gap comparison','','Bullish signal gap>=2 and full WMA magnitude>=2 are fixed. '
        'Bearish gap filters run at signal qualification and opposite-watch qualification, not again on the follow-up. '
        'Follow-up colour/RSI and price OR fresh checks, EMA10-touch waiting, exits and cutoff remain unchanged. '
        'No additional bearish magnitude veto. Gross NIFTY points; costs excluded. Research only.','',
        '| Date | Direction | Setup available | Fixed bullish 2/2, no bearish filter | + bearish gap ≥2 | + bearish gap ≥2.5 |','|---|---|---|---|---|---|']
    for day,variants in sorted(results.items()):
        ids={(t['direction'],t['signal_time']) for name,_ in SPECS for t in variants[name]['trades']}
        for side,setup in sorted(ids,key=lambda x:(x[1],x[0])):
            groups=[[t for t in variants[name]['trades'] if t['direction']==side and t['signal_time']==setup] for name,_ in SPECS]
            lines.append('| '+' | '.join([day,side,setup[11:16]]+[cell(g) for g in groups])+' |')
    lines+=['','A dash means no executed entry from that exact setup; it does not by itself establish a direct rejection. '
        'Later fresh qualification may enter under the same setup. Explicit gap rejections are listed below.','',
        '| Date | Policy | Decision | Setup | Bearish gap | Minimum | Gap passed | Other recorded reasons |',
        '|---|---|---|---|---:|---:|---|---|']
    for day,variants in sorted(results.items()):
        for name,_ in SPECS:
            for e in variants[name].get('policy_events',[]):
                if 'bearish_signal_gap_pass' not in e:continue
                lines.append('| '+' | '.join(map(str,[day,name,e['time'][11:16],str(e.get('setup_available',''))[11:16],
                    e['bearish_signal_gap'],e['bearish_signal_gap_min'],e['bearish_signal_gap_pass'],', '.join(e.get('reasons',[]))]))+' |')
    (output/'bearish-signal-comparison.md').write_text('\n'.join(lines)+'\n')
    print('SIGNAL TABLE:',output/'bearish-signal-comparison.md')

class Checks(unittest.TestCase):
    def test_bearish_signal_waits_for_followup_and_gap_veto_blocks_qualification(self):
        at=base.datetime.fromisoformat('2026-10-19T10:00:00+05:30');later=at+base.timedelta(minutes=5)
        class Gate:
            def __init__(self):
                self.pending={'BEARISH':dict(available=at,armed_at=None)};self.owner='NONE';self.active=None
                self.watch_side=None;self.watch_at=None;self.locked=False
            def can_signal(self,*args):return True
            def evaluate(self,**kwargs):
                pending=self.pending.pop('BEARISH');self.owner='BEARISH';self.active=True
                return ['entry'],[dict(direction='BEARISH',status='ENTRY',signal_available_at=pending['available'].isoformat(),
                    reasons=[],wma_threshold_pass=True,gap_positive_pass=True,gap_expanding_pass=True)]
        def frame(t,wma,rsi,close):
            return dict(available_at=t.isoformat(),rsi_available_at=t.isoformat(),open=99,high=101,low=95,close=close,
                ema10=100,previous_ema10=101,previous_rsi9=rsi+1,rsi9=rsi,
                ema3_rsi=wma-3,wma21_rsi=wma,previous_wma21_rsi=wma+1)
        frames={at:frame(at,60,50,97),later:frame(later,59,49,96)}
        for minimum,expected in ((2.5,True),(4,False)):
            gate=filtered_factory()(Gate,frames,rule='CLOSE_RSI40_60_SLOPE_COLOUR',followup=True,
                until_opposite=True,reset_reference_only=True,touch_wait=True,
                signal_gap_min=2,full_wma_min=2,bearish_gap_min=minimum)()
            self.assertFalse(gate.evaluate(minute=at-base.timedelta(minutes=1))[0])
            entries,_=gate.evaluate(minute=later-base.timedelta(minutes=1))
            self.assertEqual(bool(entries),expected)
    def test_gap_sign_and_equality(self):
        e=dict(passed=True,reasons=[]);bearish_gap(e,dict(wma21_rsi=52,ema3_rsi=50),2)
        self.assertTrue(e['passed']);self.assertEqual(e['bearish_signal_gap'],2)
    def test_gap_below_missing_nan_rejected(self):
        for f in ({},dict(wma21_rsi=51.9,ema3_rsi=50),dict(wma21_rsi=float('nan'),ema3_rsi=50)):
            e=dict(passed=True,reasons=[]);bearish_gap(e,f,2);self.assertFalse(e['passed'])
    def test_factory_keeps_bullish_and_adds_bearish(self):
        factory=filtered_factory();parameters=inspect.signature(factory).parameters
        for name in ('signal_gap_min','full_wma_min','bearish_gap_min'):self.assertIn(name,parameters)
        self.assertIs(base.filtered_factory,ORIGINAL_FACTORY)
    def test_three_policies_keep_bullish_fixed(self):
        self.assertEqual([value for _,value in SPECS],[0,2,2.5])
    def test_existing_failure_is_not_overridden(self):
        e=dict(passed=False,reasons=['OTHER_FAILURE']);bearish_gap(e,dict(wma21_rsi=55,ema3_rsi=50),2)
        self.assertFalse(e['passed']);self.assertTrue(e['bearish_signal_gap_pass'])

def main():
    global CONTROL_ROOTS
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--bullish-control-root',type=Path,action='append')
    args,remaining=parser.parse_known_args()
    if args.bullish_control_root:CONTROL_ROOTS=args.bullish_control_root
    sys.argv=[sys.argv[0]]+remaining
    if '--sensitivity' in sys.argv:raise ValueError('USE_FIXED_THREE_POLICY_COMPARISON_NOT_SENSITIVITY')
    if '--test' in sys.argv:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        if not result.wasSuccessful():raise SystemExit(1)
        base.main();return
    base.MODEL='BULLISH2_WMA2_BEARISH_GAP_STATEFUL_V1'
    base.SPECS=[(name,2,2) for name,_ in SPECS]
    base.EXTRAS=tuple(name for name,_ in SPECS)
    base.RULE_TEXT=('Fixed bullish signal gap>=2 and full WMA magnitude>=2. Compare bearish signal gap disabled, >=2 and >=2.5. '
        'No extra bearish magnitude requirement. EMA10-touch waiting, follow-up checks, exits and cutoff retained. '
        'Signal gap also gates fully qualified opposite-watch replacement. Stateful research, gross NIFTY points without costs; no live changes.')
    base.extend_variants=extend_variants
    base.compact=compact
    base.checked_writer=checked_writer
    base.main()

if __name__=='__main__':main()
