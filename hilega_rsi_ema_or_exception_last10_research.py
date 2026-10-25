"""Research: original 1m confirmation/exits, threshold WMA lock, RSI/EMA OR exception.
No new setup-generation rule; no EMA10 exit or reversal override. No live changes.
"""
import inspect
import json
import math
from pathlib import Path
from types import FunctionType,SimpleNamespace
import unittest

MODEL='EXISTING_1M_WMA_OR_EXCEPTION_40_60_ORIGINAL_EXITS_V2'
OLD_ROOT=Path('data/research/hilega-existing-minute-wma-exception-no-ema-last10-20261016')
NEW_ROOT=Path('data/research/hilega-rsi-ema-or-exception-last10-20261016')

def or_exception_allows(lock_side,entry_side,rsi,ema):
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=100 for v in (rsi,ema)):
        raise ValueError('INVALID_COMPLETED_RSI_EMA')
    return ((lock_side=='BEARISH' and entry_side=='BULLISH' and (rsi>40 or ema>40))
        or (lock_side=='BULLISH' and entry_side=='BEARISH' and (rsi<60 or ema<60)))

def combined_gate(engine,frames,wm,lock,corrected,threshold):
    import hilega_existing_ema10_wma_exception_40_60_last10_research as current
    # Clone function globals so prior AND policies are never modified.
    namespace=dict(current.combined_gate.__globals__,exception_allows=or_exception_allows)
    factory=FunctionType(current.combined_gate.__code__,namespace,current.combined_gate.__name__,
                         current.combined_gate.__defaults__,current.combined_gate.__closure__)
    disabled_ema=SimpleNamespace(directional_exit_gate=lambda Base,unused:Base)
    return factory(engine,{},wm,lock,disabled_ema,threshold)

class Checks(unittest.TestCase):
    def test_bull_rsi_alone_passes(self):self.assertTrue(or_exception_allows('BEARISH','BULLISH',41,39))
    def test_bull_ema_alone_passes(self):self.assertTrue(or_exception_allows('BEARISH','BULLISH',39,41))
    def test_bear_rsi_alone_passes(self):self.assertTrue(or_exception_allows('BULLISH','BEARISH',59,61))
    def test_bear_ema_alone_passes(self):self.assertTrue(or_exception_allows('BULLISH','BEARISH',61,59))
    def test_neither_passes_blocks(self):
        self.assertFalse(or_exception_allows('BEARISH','BULLISH',39,39))
        self.assertFalse(or_exception_allows('BULLISH','BEARISH',61,61))
    def test_equality_alone_not_enough(self):
        self.assertFalse(or_exception_allows('BEARISH','BULLISH',40,40))
        self.assertFalse(or_exception_allows('BULLISH','BEARISH',60,60))
    def test_invalid_indicator_rejected(self):
        with self.assertRaises(ValueError):or_exception_allows('BEARISH','BULLISH',50,float('nan'))
    def test_previous_and_policy_unchanged(self):
        import hilega_existing_ema10_wma_exception_40_60_last10_research as current
        self.assertFalse(current.exception_allows('BULLISH','BEARISH',59,61))
    def test_composed_gate_allows_one_indicator_and_preserves_lock(self):
        from datetime import datetime,timedelta
        import hilega_post_entry_wma_lock_today_research as lock
        import hilega_wma_threshold_only_oct14_research as threshold
        at=datetime.fromisoformat('2026-10-05T10:00:00+05:30')
        class Base:
            def __init__(self):self.owner='NONE';self.active=None;self.pending={}
            def evaluate(self,**kwargs):
                self.owner='BEARISH';self.active=True
                return ['BEARISH'],[dict(status='ENTRY',reasons=[],direction='BEARISH',signal_available_at=at.isoformat(),decision_timestamp=at.isoformat())]
        wm={at:dict(wma21=70,previous_wma21=71,rsi9=59,ema3=65,available_at=at.isoformat())}
        Gate=combined_gate(SimpleNamespace(WmaGapGate=Base,direction=lambda e:e),{},wm,lock,None,threshold)
        g=Gate();entries,_=g.evaluate(minute=at-timedelta(minutes=1))
        self.assertEqual(entries,['BEARISH']);self.assertEqual(g.direction_lock.side,'BULLISH')
        self.assertFalse(g.direction_lock.permits('BEARISH'))

def compare(output):
    import hilega_pending_previous10_research as stats
    import hilega_existing_ema10_wma_combined_last10_research as base
    report=json.loads((output/'report.json').read_text());prior=json.loads((OLD_ROOT/'report.json').read_text())
    if report['status']!='COMPLETE':return
    if prior['status']!='COMPLETE' or prior['model']!='EXISTING_1M_WMA_EXCEPTION_40_60_ORIGINAL_EXITS_V1':raise ValueError('PREVIOUS_AND_REPORT_REQUIRED')
    labels=('Existing strategy','Combined AND exception','Combined OR exception');totals={label:[] for label in labels}
    lines=['# RSI/EMA exception: AND versus OR','',
        'Research only; gross NIFTY points, no fills/costs/live changes. Existing 1m entries/persistence, ten-minute window and original exits unchanged. WMA lock from open 55/45. OR applies only to exception permission: bullish RSI9>40 OR EMA3-of-RSI>40; bearish RSI9<60 OR EMA3-of-RSI<60. Both values must remain valid. No fresh-signal generation or candidate-retention change. No EMA10 exit or reversal override.','',
        '| Date | Existing points | AND points | OR points | Change vs AND |','|---|---:|---:|---:|---:|']
    details=['# Daily signal comparison — OR exception','','Times IST. Cells show entry–exit and gross NIFTY points. Dash means no executed entry from that exact setup, not automatic proof of veto.','']
    for day in report['session_dates']:
        new=json.loads((output/'sessions'/(day+'.json')).read_text());old=json.loads((OLD_ROOT/'sessions'/(day+'.json')).read_text())
        if prior['provenance'][day]['input_sha256']!=report['provenance'][day]['input_sha256']:raise ValueError('INPUT_HASH_MISMATCH')
        if stats.frozen_parity(old['EXISTING'],new['EXISTING'])['status']!='PASS':raise ValueError('BASELINE_PARITY_MISMATCH')
        variants=(new['EXISTING'],old['COMBINED'],new['COMBINED']);values=[stats.stats(r['trades'])['points'] for r in variants]
        lines.append(f'| {day} | {values[0]:+.2f} | {values[1]:+.2f} | {values[2]:+.2f} | {values[2]-values[1]:+.2f} |')
        for label,r in zip(labels,variants):totals[label].extend(r['trades'])
        details+=['','## '+day,'','| Direction | Setup available | '+' | '.join(labels)+' |','|---|---|---|---|---|']
        identities=sorted({(t['direction'],t['signal_time']) for r in variants for t in r['trades']},key=lambda x:(x[1],x[0]))
        for side,signal in identities:
            cells=[base.cell([t for t in r['trades'] if (t['direction'],t['signal_time'])==(side,signal)]) for r in variants]
            details.append('| '+side+' | '+signal[11:16]+' | '+' | '.join(cells)+' |')
        details+=['','### OR exception decisions','','| Time | Direction | Lock | Latest completed 5m | RSI9 | EMA3 of RSI9 | Allowed |','|---|---|---|---|---:|---:|---|']
        for e in new['COMBINED']['policy_events']:
            if e['event']=='COMBINED_RSI_EMA_EXCEPTION_CHECK':details.append(f"| {e['time'][11:16]} | {e['direction']} | {e['lock']} | {e['indicator_available_at'][11:16]} | {e['rsi9']:.3f} | {e['ema3_rsi']:.3f} | {e['allowed']} |")
    summary={label:stats.stats(trades) for label,trades in totals.items()};report['and_or_comparison']=summary
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines+=['','| Policy | Trades | Winning points | Losing points | Net points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for label,s in summary.items():lines.append(f"| {label} | {s['trades']} | {s['gross_winning_points']:+.2f} | {-s['gross_losing_points']:.2f} | {s['points']:+.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    (output/'and-or-comparison.md').write_text('\n'.join(lines+details)+'\n');print('\n'.join(lines+details))

def main():
    import hilega_existing_minute_wma_exception_no_ema_last10_research as restored
    source=inspect.getsource(restored.main)
    old="'Checks,exception.Checks,threshold.Checks'"
    if source.count(old)!=1:raise ValueError('RESTORED_TEST_SUITE_SOURCE_DIFFERS')
    source=source.replace(old,"'Checks,threshold.Checks'",1)
    # Apply the warning replacement only to the newly generated isolated main,
    # after its original source-anchor checks. Imported previous code is intact.
    anchor="    exec(compile(source,'<restored-minute-batch>','exec'),namespace)"
    if source.count(anchor)!=1:raise ValueError('RESTORED_MAIN_SOURCE_DIFFERS')
    replacement="    source=source.replace('completed RSI9 and EMA3 both>40 for bullish under bearish lock, both<60 for bearish under bullish lock.', 'completed RSI9 OR EMA3 >40 for bullish under bearish lock; RSI9 OR EMA3 <60 for bearish under bullish lock.')\n"+anchor
    source=source.replace(anchor,replacement,1)
    namespace=dict(vars(restored));namespace.update(MODEL=MODEL,NEW_ROOT=NEW_ROOT,Checks=Checks,restored=restored,combined_gate=combined_gate,compare=compare)
    # The inner isolated main's globals also need the preserved old test module.
    source=source.replace('namespace.update(MODEL=MODEL,NEW_ROOT=NEW_ROOT,Checks=Checks,combined_gate=combined_gate,compare=compare)',
        'namespace.update(MODEL=MODEL,NEW_ROOT=NEW_ROOT,Checks=Checks,restored=restored,combined_gate=combined_gate,compare=compare)')
    exec(compile(source,'<or-exception-runner>','exec'),namespace);namespace['main']()

if __name__=='__main__':main()
