"""Research only: bearish signal close<price EMA30, keeping EMA10 slope/touch.

Bullish gap>=2/full WMA magnitude>=2 fixed. All original exits retained.
Same replay CLI arguments as hilega_bullish_gap_magnitude_stateful.py.
"""
import inspect
import json
import linecache
import math
import sys
import unittest
from types import SimpleNamespace
import hilega_bullish_gap_magnitude_stateful as base

CONTROL='BULLISH_GAP2_FULL_WMA2'
TEST='BULL2_WMA2_BEAR_CLOSE_EMA30'
ORIGINAL_EXTEND=base.extend_variants
ORIGINAL_CHECK=base.research.frame_check
ORIGINAL_COMPACT=base.compact

def frame_check(side,frame,at,rule='FULL_CANDLE'):
    evidence=ORIGINAL_CHECK(side,frame,at,rule)
    if side!='BEARISH' or rule!='CLOSE_RSI40_60_SLOPE_COLOUR' or frame is None:return evidence
    value=frame.get('ema30')
    valid=value is not None and not isinstance(value,bool) and math.isfinite(float(value)) and float(value)>0
    passed=valid and float(frame['close'])<float(value)
    reasons=[reason for reason in evidence['reasons'] if reason!='BEARISH_CLOSE_NOT_BELOW_EMA10']
    if not valid:reasons.append('COMPLETED_PRICE_EMA30_MISSING_OR_INVALID')
    elif not passed:reasons.append('BEARISH_CLOSE_NOT_BELOW_EMA30')
    evidence.update(reasons=reasons,passed=not reasons,price_position_pass=passed,
        bearish_price_position_period=30,ema30=value,close_below_ema30=passed,
        slope_period=10,touch_period=10)
    return evidence

def ema30_frames(engine,day,raw,warm,dt):
    source=inspect.getsource(base.research.build_frames)
    if source.count('(2/11)')!=1:raise ValueError('EMA_FRAME_ALPHA_ANCHOR_MISMATCH')
    source=source.replace('(2/11)','(2/31)',1)
    namespace=dict(base.research.build_frames.__globals__)
    filename='<hilega-price-ema30-frames>'
    linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
    exec(compile(source,filename,'exec'),namespace)
    return namespace['build_frames'](engine,day,raw,warm,dt)

def extend_variants(original):
    controls=ORIGINAL_EXTEND(original);r=base.research
    def add(engine,baseline,old,new,Gate,NewGate,fresh,p,day,raw,warm,asof,wm,lock,threshold):
        variants=controls(engine,baseline,old,new,Gate,NewGate,fresh,p,day,raw,warm,asof,wm,lock,threshold)
        frames=r.attach_completed_rsi(r.build_frames(engine,day,raw,warm,p.dt),baseline,p.dt)
        slower=ema30_frames(engine,day,raw,warm,p.dt)
        if set(frames)!=set(slower):raise ValueError('EMA10_EMA30_FRAME_COVERAGE_MISMATCH')
        for at in frames:
            if frames[at]['close']!=slower[at]['close']:raise ValueError('EMA30_INPUT_CLOSE_MISMATCH')
            frames[at]['ema30']=slower[at]['ema10']
            frames[at]['previous_ema30']=slower[at]['previous_ema10']
        previous=r.frame_check
        try:
            r.frame_check=frame_check
            parent=r.direct_five_base(engine.WmaGapGate,no_expiry=True)
            watch=r.qualified_opposite_watch_gate(parent,frames,engine.direction,require_wma_permission=False,
                signal_rule='CLOSE_RSI40_60_SLOPE_COLOUR',until_opposite=True)
            class BullishGapWatch(watch):
                def qualifies(self,side,at):
                    if not super().qualifies(side,at):return False
                    if side!='BULLISH':return True
                    evidence=dict(passed=True,reasons=[]);base.apply_gap(evidence,frames.get(at),2)
                    return evidence['passed']
            gate=base.filtered_factory()(BullishGapWatch,frames,rule='CLOSE_RSI40_60_SLOPE_COLOUR',followup=True,
                continue_waiting=False,until_opposite=True,reset_reference_only=True,touch_wait=True,
                signal_gap_min=2,full_wma_min=2)
            replay=r.direct_fresh_replay(engine,fresh,retry_followup=True,until_opposite=True)
            value=p.simulate(SimpleNamespace(WmaGapGate=gate,replay=replay),day,raw,warm,asof,'CURRENT')
        finally:r.frame_check=previous
        value['research_entry_rules']=dict(variants[CONTROL]['research_entry_rules'],
            bearish_price_position_period=30,bearish_slope_period=10,failed_followup_touch_period=10,
            price_ema30_alpha=2/31,price_ema30_seed='FIRST_CLOSE_CONTINUOUS_ORIGINAL_WARMUP')
        variants[TEST]=value
        return variants
    return add

def compact(output,results,stats):
    ORIGINAL_COMPACT(output,results,stats)
    keys=('EXISTING','FRESH_AND','FRESH_AND_EMA10_ENTRY','EXISTING_BASELINE_2',CONTROL,TEST)
    lines=['# Bearish EMA30 position: signal comparison','',
        'Only bearish signal price position changes: close<EMA30 replaces close<EMA10. '
        'EMA10 falling remains required; failed-followup retention still uses EMA10 touch. '
        'Bullish 2/2 filters, all other signal/follow-up checks, exits and cutoff retained. '
        'EMA30 uses completed 5m closes, alpha 2/31, first-close seed and the original continuous warmup (minimum20 sessions). '
        'Gross NIFTY points before costs. Dash means no execution from that exact setup, not necessarily direct veto.','',
        '| Date | Direction | Setup available | Existing | Fresh AND | EMA10-touch | Baseline 2 | Current bullish 2/2 | + bearish EMA30 position |',
        '|---|---|---|---|---|---|---|---|---|']
    def cell(trades):return '<br>'.join(f"{t['entry_time'][11:16]}–{t['exit_time'][11:16]} · {t['points']:+.2f}" for t in trades) or '—'
    for day,variants in sorted(results.items()):
        ids={(t['direction'],t['signal_time']) for key in keys for t in variants[key]['trades']}
        for side,setup in sorted(ids,key=lambda v:(v[1],v[0])):
            cells=[cell([t for t in variants[key]['trades'] if t['direction']==side and t['signal_time']==setup]) for key in keys]
            lines.append('| '+' | '.join([day,side,setup[11:16]]+cells)+' |')
    (output/'daily-signal-comparison.md').write_text('\n'.join(lines)+'\n')
    values=['# Explicit bearish EMA30 signal checks','',
        '| Date | Setup | Decision | Close | Price EMA10 | Price EMA30 | EMA30 position passed | EMA10 slope | Overall passed | Reasons |',
        '|---|---|---|---:|---:|---:|---|---:|---|---|']
    for day,variants in sorted(results.items()):
        for e in variants[TEST].get('policy_events',[]):
            if e.get('direction')!='BEARISH' or 'bearish_price_position_period' not in e:continue
            values.append('| '+' | '.join(map(str,[day,str(e.get('setup_available',''))[11:16],e['time'][11:16],
                e.get('close'),e.get('ema10'),e.get('ema30'),e.get('close_below_ema30'),e.get('ema10_slope'),e.get('passed'),', '.join(e.get('reasons',[]))]))+' |')
    (output/'bearish-ema30-validation.md').write_text('\n'.join(values)+'\n')
    for name in ('daily-signal-comparison.md','bearish-ema30-validation.md'):print('REPORT:',output/name)

class Checks(unittest.TestCase):
    def frame(self,**kw):
        return dict(dict(open=103,high=104,low=99,close=100,ema10=99,previous_ema10=100,
            ema30=101,available_at='2026-10-14T10:00:00+05:30',rsi_available_at='2026-10-14T10:00:00+05:30',
            previous_rsi9=55,rsi9=50),**kw)
    def check(self,**kw):return frame_check('BEARISH',self.frame(**kw),base.datetime.fromisoformat('2026-10-14T10:00:00+05:30'),rule='CLOSE_RSI40_60_SLOPE_COLOUR')
    def test_below30_can_pass_when_above10(self):self.assertTrue(self.check()['passed'])
    def test_above30_fails_when_below10(self):
        e=self.check(ema30=99,ema10=101,previous_ema10=102)
        self.assertFalse(e['passed']);self.assertIn('BEARISH_CLOSE_NOT_BELOW_EMA30',e['reasons'])
    def test_ema30_equality_fails(self):self.assertFalse(self.check(ema30=100)['passed'])
    def test_ema10_slope_remains_required(self):
        self.assertIn('EMA10_NOT_FALLING',self.check(previous_ema10=98)['reasons'])
    def test_colour_and_rsi_remain_required(self):
        self.assertFalse(self.check(open=99)['passed']);self.assertFalse(self.check(previous_rsi9=49)['passed'])
    def test_touch_still_uses_ema10(self):
        f=self.frame(low=99,high=104,ema10=98,ema30=101)
        self.assertFalse(base.research.ema10_touch(f,base.datetime.fromisoformat(f['available_at'])))
    def test_missing_ema30_fails(self):self.assertFalse(self.check(ema30=None)['passed'])
    def test_bullish_check_unchanged(self):
        at=base.datetime.fromisoformat('2026-10-14T10:00:00+05:30');f=self.frame()
        self.assertEqual(frame_check('BULLISH',f,at,'CLOSE_RSI40_60_SLOPE_COLOUR'),ORIGINAL_CHECK('BULLISH',f,at,'CLOSE_RSI40_60_SLOPE_COLOUR'))

def main():
    if '--sensitivity' in sys.argv:raise ValueError('SENSITIVITY_NOT_SUPPORTED')
    if '--test' in sys.argv:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        if not result.wasSuccessful():raise SystemExit(1)
        base.main();return
    base.MODEL='BEARISH_EMA30_POSITION_BULLISH2_2_STATEFUL_V1'
    # The original extension generates only the unchanged bullish 2/2 control.
    base.SPECS=[(CONTROL,2,2)]
    base.EXTRAS=(CONTROL,TEST)
    base.RULE_TEXT=('Bearish signal close<price EMA30 only; EMA10 falling and EMA10-touch waiting retained. '
        'Bullish gap>=2/full WMA magnitude>=2 fixed. EMA30 alpha2/31, original completed5m warmup. '
        'No bearish gap/magnitude addition, no exit changes. Stateful research, gross NIFTY points, costs excluded; no live changes.')
    base.extend_variants=extend_variants;base.compact=compact
    base.main()

if __name__=='__main__':main()
