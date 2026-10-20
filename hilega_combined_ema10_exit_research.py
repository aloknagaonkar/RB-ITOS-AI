"""Research-only stateful comparison: current combined versus EMA10 OR exits.
Uses the existing bullish gap2/WMA2 entry policy, with unchanged bearish entries.
"""
import inspect
import json
import linecache
import math
import sys
import unittest
from datetime import timedelta
from types import SimpleNamespace
import hilega_bullish_gap_magnitude_stateful as base

CONTROL='BULLISH_GAP2_FULL_WMA2'
VARIANTS=(('COMBINED_EMA10_EXIT_1_CLOSE',1),('COMBINED_EMA10_EXIT_2_CLOSES',2))
ORIGINAL_EXTEND=base.extend_variants
ORIGINAL_COMPACT=base.compact

def ema_exit_decision(g,at,original,frames,required):
    f=frames.get(at)
    if f is None or f.get('available_at')!=at.isoformat():raise ValueError('EXACT_COMPLETED_EMA_FRAME_REQUIRED')
    close,ema=f['close'],f['ema10']
    if any(isinstance(v,bool) or not math.isfinite(float(v)) for v in (close,ema)):raise ValueError('INVALID_EXIT_EMA')
    identity=(g.owner,g.active['time'])
    prior=getattr(g,'ema_exit_counter',None)
    adverse=close<ema if g.owner=='BULLISH' else close>ema
    if prior and prior['identity']==identity and prior['at']==at:
        count=prior['count']
    else:
        consecutive=prior and prior['identity']==identity and prior['at']==at-timedelta(minutes=5)
        count=(prior['count']+1 if consecutive else 1) if adverse else 0
        g.ema_exit_counter=dict(identity=identity,at=at,count=count)
    extra=count>=required
    g.policy_events.append(dict(event='EMA10_OR_EXIT_CHECK',time=at.isoformat(),direction=g.owner,
        entry_time=g.active['time'].isoformat(),close=close,ema10=ema,adverse_close=adverse,
        consecutive=count,required=required,existing_exit_pass=original,ema_exit_pass=extra,
        passed=bool(original or extra)))
    return bool(original or extra)

def replay_with_exit(engine,fresh,frames,required):
    original=base.research.direct_fresh_replay(engine,fresh,retry_followup=True,until_opposite=True)
    source=inspect.getsource(original)
    old='if dual_exit(side,new):'
    if source.count(old)!=1:raise ValueError('EXIT_REPLAY_ANCHOR_MISMATCH')
    source=source.replace(old,'if ema_exit_decision(g,at,dual_exit(side,new),ema_frames,ema_required):',1)
    old="exit_reason='BOTH_RSI9_EMA3_OPPOSITE_WMA21'"
    if source.count(old)!=1:raise ValueError('EXIT_REASON_ANCHOR_MISMATCH')
    source=source.replace(old,"exit_reason=('BOTH_RSI9_EMA3_OPPOSITE_WMA21' if dual_exit(side,new) else 'PRICE_EMA10_ADVERSE_CLOSES_'+str(ema_required))",1)
    namespace=dict(original.__globals__,ema_exit_decision=ema_exit_decision,ema_frames=frames,ema_required=required)
    filename='<hilega-combined-ema10-or-exit-'+str(required)+'>'
    linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
    exec(compile(source,filename,'exec'),namespace)
    return namespace['replay']

def extend_variants(original):
    controls=ORIGINAL_EXTEND(original)
    def add(engine,baseline,old,new,Gate,NewGate,fresh,p,day,raw,warm,asof,wm,lock,threshold):
        variants=controls(engine,baseline,old,new,Gate,NewGate,fresh,p,day,raw,warm,asof,wm,lock,threshold)
        r=base.research
        frames=r.attach_completed_rsi(r.build_frames(engine,day,raw,warm,p.dt),baseline,p.dt)
        for name,required in VARIANTS:
            parent=r.direct_five_base(engine.WmaGapGate,no_expiry=True)
            watch=r.qualified_opposite_watch_gate(parent,frames,engine.direction,require_wma_permission=False,
                signal_rule='CLOSE_RSI40_60_SLOPE_COLOUR',until_opposite=True)
            class GapWatch(watch):
                def qualifies(self,side,at):
                    if not super().qualifies(side,at):return False
                    if side!='BULLISH':return True
                    ev=dict(passed=True,reasons=[]);base.apply_gap(ev,frames.get(at),2)
                    return ev['passed']
            gate=base.filtered_factory()(GapWatch,frames,rule='CLOSE_RSI40_60_SLOPE_COLOUR',followup=True,
                continue_waiting=False,until_opposite=True,reset_reference_only=True,touch_wait=True,
                signal_gap_min=2,full_wma_min=2)
            replay=replay_with_exit(engine,fresh,frames,required)
            value=p.simulate(SimpleNamespace(WmaGapGate=gate,replay=replay),day,raw,warm,asof,'CURRENT')
            value['research_entry_rules']=dict(variants[CONTROL]['research_entry_rules'],
                exit_policy='ORIGINAL_DUAL_OR_DIRECTIONAL_PRICE_EMA10',adverse_closes_required=required)
            variants[name]=value
        return variants
    return add

def compact(output,results,stats):
    ORIGINAL_COMPACT(output,results,stats)
    keys=(CONTROL,)+tuple(n for n,_ in VARIANTS)
    lines=['# Current combined versus directional EMA10 OR exits','',
        'Stateful research, gross NIFTY points before costs. Same entry logic in all variants; '
        'changed exits can change later signals and trades. Bull close<price EMA10; bear close>EMA10. '
        'Equality resets consecutive count. Existing dual exit and 14:55 cutoff always remain. '
        'Neither EMA10 exit delays an existing exit. No orders or live changes.','',
        '| Scope | Policy | Trades | Winning points | Losing points | Net points | Change vs current | Drawdown |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for scope in ('ALL','BULLISH','BEARISH'):
        selected=lambda key:[t for day in sorted(results) for t in results[day][key]['trades'] if scope=='ALL' or t['direction']==scope]
        current=stats.stats(selected(CONTROL))['points']
        for key in keys:
            s=stats.stats(selected(key))
            lines.append(f"| {scope} | {key} | {s['trades']} | {s['gross_winning_points']:+.2f} | {-s['gross_losing_points']:.2f} | {s['points']:+.2f} | {s['points']-current:+.2f} | {s['max_closed_trade_drawdown_points']:.2f} |")
    table=['# Actual signal and exit comparison','',
        'Match by direction and original setup. A dash is no execution from that setup, not proof of direct veto. '
        'Impact compares setup totals; changed entry paths are explicitly identified. Times IST.','',
        '| Date | Direction | Setup | Current combined | One-close EMA10 exit | Impact / status | Two-close EMA10 exit | Impact / status |',
        '|---|---|---|---|---|---|---|---|']
    def cell(ts):return '<br>'.join(f"{t['entry_time'][11:16]}–{t['exit_time'][11:16]} · {t['points']:+.2f} · {t.get('exit_reason','')}" for t in ts) or '—'
    def impact(control,test):
        if not control:return 'NEW TRADE PATH' if test else 'NO TRADE'
        if not test:return 'CURRENT TRADE NOT TAKEN; state changed'
        delta=sum(t['points'] for t in test)-sum(t['points'] for t in control)
        same=sorted(t['entry_time'] for t in control)==sorted(t['entry_time'] for t in test)
        status='IMPROVED' if delta>1e-5 else 'WORSENED' if delta<-1e-5 else 'UNCHANGED POINTS'
        return status+f' {delta:+.2f}'+('' if same else '; DIFFERENT ENTRY PATH')
    for day,variants in sorted(results.items()):
        identities={(t['direction'],t['signal_time']) for k in keys for t in variants[k]['trades']}
        for side,setup in sorted(identities,key=lambda x:(x[1],x[0])):
            ts=[[t for t in variants[k]['trades'] if t['direction']==side and t['signal_time']==setup] for k in keys]
            table.append('| '+' | '.join([day,side,setup[11:16],cell(ts[0]),cell(ts[1]),impact(ts[0],ts[1]),cell(ts[2]),impact(ts[0],ts[2])])+' |')
    (output/'ema10-exit-comparison.md').write_text('\n'.join(lines)+'\n')
    (output/'daily-signal-exit-impact.md').write_text('\n'.join(table)+'\n')
    (output/'ema10-exit-checks.json').write_text(json.dumps({d:{k:[e for e in v[k].get('policy_events',[]) if e.get('event')=='EMA10_OR_EXIT_CHECK'] for k,_ in VARIANTS} for d,v in results.items()},indent=2,default=str))
    print('\n'.join(lines));print('TRADE TABLE:',output/'daily-signal-exit-impact.md')

class Checks(unittest.TestCase):
    def setUp(self):
        from datetime import datetime
        self.at=datetime.fromisoformat('2026-10-01T10:20:00+05:30')
        self.g=SimpleNamespace(owner='BULLISH',active={'time':self.at-timedelta(minutes=15)},policy_events=[])
    def check(self,close=99,required=1,original=False,offset=0):
        at=self.at+timedelta(minutes=offset)
        return ema_exit_decision(self.g,at,original,{at:dict(close=close,ema10=100,available_at=at.isoformat())},required)
    def test_bullish_one_close(self):self.assertTrue(self.check())
    def test_bearish_one_close(self):self.g.owner='BEARISH';self.assertTrue(self.check(close=101))
    def test_two_consecutive(self):self.assertFalse(self.check(required=2));self.assertTrue(self.check(required=2,offset=5))
    def test_equality_resets(self):
        self.check(required=2);self.check(close=100,required=2,offset=5);self.assertFalse(self.check(required=2,offset=10))
    def test_existing_exit_does_not_wait(self):self.assertTrue(self.check(close=101,required=2,original=True))
    def test_duplicate_boundary_not_double_counted(self):self.check(required=2);self.assertFalse(self.check(required=2))
    def test_new_trade_resets(self):
        self.check(required=2);self.g.active={'time':self.at};self.assertFalse(self.check(required=2,offset=5))
    def test_missing_boundary_breaks_sequence(self):self.check(required=2);self.assertFalse(self.check(required=2,offset=10))
    def test_missing_frame_rejected(self):
        with self.assertRaises(ValueError):ema_exit_decision(self.g,self.at,False,{},1)

def main():
    if '--test' in sys.argv:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        if not result.wasSuccessful():raise SystemExit(1)
    base.extend_variants=extend_variants
    base.compact=compact
    base.MODEL='COMBINED_DIRECTIONAL_EMA10_OR_EXIT_STATEFUL_V1'
    base.RULE_TEXT+=' Additional variants change exits only: original dual OR one/two adverse completed price EMA10 closes.'
    base.research.POLICIES=base.research.POLICIES+tuple(n for n,_ in VARIANTS)
    base.main()

if __name__=='__main__':main()
