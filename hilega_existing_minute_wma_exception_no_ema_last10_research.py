"""Research: restore original 1m confirmation; original exits; WMA lock and 40/60 exception.
EMA10 exit and opposite reversal override remain disabled. No live changes/orders.
"""
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

MODEL='EXISTING_1M_WMA_EXCEPTION_40_60_ORIGINAL_EXITS_V1'
OLD_ROOT=Path('data/research/hilega-five-minute-wma-exception-no-ema-last10-20261016')
NEW_ROOT=Path('data/research/hilega-existing-minute-wma-exception-no-ema-last10-20261016')

def combined_gate(engine,frames,wm,lock,corrected,threshold):
    import hilega_existing_ema10_wma_exception_40_60_last10_research as current
    disabled_ema=SimpleNamespace(directional_exit_gate=lambda Base,unused:Base)
    # Original gate, without a cadence or pending-lifecycle wrapper.
    return current.combined_gate(engine,{},wm,lock,disabled_ema,threshold)

class Checks(unittest.TestCase):
    def harness(self):
        from datetime import datetime
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        import hilega_post_entry_wma_lock_today_research as lock
        import hilega_wma_threshold_only_oct14_research as threshold
        at=datetime.fromisoformat('2026-10-05T10:00:00+05:30')
        wm={at:dict(wma21=50,previous_wma21=51,available_at=at.isoformat(),rsi9=45,ema3=46)}
        Gate=combined_gate(engine,{},wm,lock,None,threshold)
        return Gate(opposite_switch=True),at,engine
    def test_original_exit_has_no_ema_veto(self):
        g,at,e=self.harness();g.owner='BULLISH';g.active={'time':at,'price':100}
        event=e.StrategyEvent('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21',at,None,'ACTIVE','IDLE',exit_reason='BOTH_RSI9_EMA3_OPPOSITE_WMA21')
        self.assertIsNotNone(g.close(event,at,101));self.assertEqual(g.owner,'NONE')
        self.assertFalse(any(row['event'].startswith('EMA_EXIT') for row in g.policy_events))
    def test_no_opposite_monitor_override(self):
        g,at,e=self.harness();self.assertFalse(hasattr(g,'can_monitor'))
        g.owner='BULLISH';g.active={'time':at,'price':100}
        event=e.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={})
        g.signal(event,at);self.assertNotIn('BEARISH',g.pending)
    def test_confirmed_entry_can_execute_between_five_minute_boundaries(self):
        from datetime import timedelta
        g,at,e=self.harness()
        event=e.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={})
        g.signal(event,at)
        reference=SimpleNamespace(ready=True,wma21_rsi=52)
        for minutes,ema in ((0,49),(1,49),(2,47)):
            minute=at+timedelta(minutes=minutes)
            snap=SimpleNamespace(ready=True,rsi9=ema-1,ema3_rsi=ema,wma21_rsi=50)
            entries,checks=g.evaluate(minute=minute,current=snap,reference=reference,price=100)
        self.assertEqual(g.owner,'BEARISH');self.assertEqual(len(entries),1)
        self.assertEqual(checks[0]['decision_timestamp'][11:16],'10:03')

def compare(output):
    import hilega_pending_previous10_research as stats
    import hilega_existing_ema10_wma_combined_last10_research as base
    report=json.loads((output/'report.json').read_text());prior=json.loads((OLD_ROOT/'report.json').read_text())
    if report['status']!='COMPLETE':return
    if prior['status']!='COMPLETE' or prior['model']!='FIVE_MINUTE_PERSISTENCE_WMA_EXCEPTION_40_60_ORIGINAL_EXITS_V1':raise ValueError('PREVIOUS_5M_REPORT_REQUIRED')
    labels=('Existing strategy','Previous 5m, original exits','Restored 1m, original exits')
    totals={label:[] for label in labels}
    lines=['# Restored existing 1m confirmation — same ten sessions','',
        'Research only; gross NIFTY points, no fills/costs. WMA from-open lock 55/45 and RSI/EMA exception >40 / <60 retained. Original dual exits; no EMA10 veto or reversal override. Same ten-minute pending window. Previous 5m versus restored 1m isolates confirmation cadence, including persistence/gap sampling.','',
        '| Date | Existing points | Previous 5m points | Restored 1m points | Change vs 5m |','|---|---:|---:|---:|---:|']
    details=['# Signal comparison — restore 1m confirmation','','Times IST. Cell: entry–exit · NIFTY points. Exact direction/setup identities; dash means no executed entry, not automatically a WMA block. See daily-signal-comparison.md for explicit decisions.','']
    for day in report['session_dates']:
        new=json.loads((output/'sessions'/(day+'.json')).read_text());old=json.loads((OLD_ROOT/'sessions'/(day+'.json')).read_text())
        if prior['provenance'][day]['input_sha256']!=report['provenance'][day]['input_sha256']:raise ValueError('PREVIOUS_INPUT_HASH_MISMATCH')
        if stats.frozen_parity(old['EXISTING'],new['EXISTING'])['status']!='PASS':raise ValueError('BASELINE_PARITY_MISMATCH')
        if any(e['event'].startswith('EMA_EXIT') or e['event']=='CONFIRMED_OPPOSITE_EXIT_OVERRIDE' for e in new['COMBINED']['policy_events']):raise ValueError('DISABLED_FEATURE_USED')
        variants=(new['EXISTING'],old['COMBINED'],new['COMBINED']);values=[stats.stats(r['trades'])['points'] for r in variants]
        lines.append(f'| {day} | {values[0]:+.2f} | {values[1]:+.2f} | {values[2]:+.2f} | {values[2]-values[1]:+.2f} |')
        for label,value in zip(labels,variants):totals[label].extend(value['trades'])
        details+=['','## '+day,'','| Direction | Setup available | '+' | '.join(labels)+' |','|---|---|---|---|---|']
        identities=sorted({(t['direction'],t['signal_time']) for r in variants for t in r['trades']},key=lambda x:(x[1],x[0]))
        for side,signal in identities:
            cells=[base.cell([t for t in r['trades'] if (t['direction'],t['signal_time'])==(side,signal)]) for r in variants]
            details.append('| '+side+' | '+signal[11:16]+' | '+' | '.join(cells)+' |')
    summary={key:stats.stats(value) for key,value in totals.items()};report['cadence_comparison']=summary
    report['disabled_features_verified']=True
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines+=['','| Policy | Trades | Winning points | Losing points | Net points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for key,s in summary.items():lines.append(f"| {key} | {s['trades']} | {s['gross_winning_points']:+.2f} | {-s['gross_losing_points']:.2f} | {s['points']:+.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    (output/'restored-minute-comparison.md').write_text('\n'.join(lines+details)+'\n');print('\n'.join(lines+details))

def main():
    import hilega_five_minute_wma_exception_no_ema_last10_research as previous
    source=inspect.getsource(previous.main)
    changes={
        'Checks,five.Checks,exception.Checks,threshold.Checks':'Checks,exception.Checks,threshold.Checks',
        'Five-minute confirmation + WMA lock / exceptions; original exits — ten sessions':'Existing 1m confirmation + WMA lock / exceptions; original exits — ten sessions',
        'COMBINED uses completed 5m confirmation with persistence and gap expansion compared across consecutive completed 5m readings. Existing setup generation keeps minute-gap inputs. Ten-minute expiry, direction watch and canonical cancellation retained.':
            'COMBINED uses ORIGINAL 1m confirmation, persistence and minute-gap expansion. Ten-minute expiry, direction watch and canonical cancellation retained.',
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('PREVIOUS_RUNNER_SOURCE_DIFFERS:'+old)
        source=source.replace(old,new,1)
    namespace=dict(vars(previous));namespace.update(MODEL=MODEL,NEW_ROOT=NEW_ROOT,Checks=Checks,combined_gate=combined_gate,compare=compare)
    exec(compile(source,'<restored-minute-batch>','exec'),namespace)
    namespace['main']()

if __name__=='__main__':main()
