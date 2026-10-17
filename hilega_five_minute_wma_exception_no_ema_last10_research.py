"""Research: 5m confirmation with persistence + WMA lock/40-60 exceptions.
Original dual exits only; EMA10 exit and opposite reversal override disabled.
"""
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

MODEL='FIVE_MINUTE_PERSISTENCE_WMA_EXCEPTION_40_60_ORIGINAL_EXITS_V1'
OLD_ROOT=Path('data/research/hilega-existing-ema10-wma-exception-40-60-last10-20261016')
NEW_ROOT=Path('data/research/hilega-five-minute-wma-exception-no-ema-last10-20261016')

def combined_gate(engine,frames,wm,lock,corrected,threshold):
    import hilega_existing_ema10_wma_exception_40_60_last10_research as current
    import hilega_five_min_confirmation_research as five
    Five=five.five_gate(engine.WmaGapGate,continued=False)
    proxy=SimpleNamespace(WmaGapGate=Five,direction=engine.direction)
    # An explicit identity adapter disables the price EMA10 wrapper. Existing
    # close() remains intact; the outer lock wrapper cannot veto a normal exit.
    disabled_ema=SimpleNamespace(directional_exit_gate=lambda Base,unused:Base)
    return current.combined_gate(proxy,{},wm,lock,disabled_ema,threshold)

class Checks(unittest.TestCase):
    def gate(self):
        from datetime import datetime
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        import hilega_post_entry_wma_lock_today_research as lock
        import hilega_wma_threshold_only_oct14_research as threshold
        at=datetime.fromisoformat('2026-10-05T10:00:00+05:30')
        wm={at:dict(wma21=60,previous_wma21=61,available_at=at.isoformat(),rsi9=50,ema3=50)}
        Gate=combined_gate(engine,{},wm,lock,None,threshold)
        return Gate(opposite_switch=True),at,engine
    def test_original_exit_needs_no_ema_frame(self):
        g,at,e=self.gate();g.owner='BULLISH';g.active={'time':at,'price':100}
        event=e.StrategyEvent('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21',at,None,'ACTIVE','IDLE',exit_reason='BOTH_RSI9_EMA3_OPPOSITE_WMA21')
        closed=g.close(event,at,101)
        self.assertIsNotNone(closed);self.assertEqual(g.owner,'NONE');self.assertEqual(closed.points,1)
        self.assertFalse(any(row['event'].startswith('EMA_EXIT') for row in g.policy_events))
    def test_reversal_monitor_disabled(self):
        g,at,e=self.gate();self.assertFalse(hasattr(g,'can_monitor'))
        g.owner='BULLISH';g.active={'time':at,'price':100}
        event=e.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={})
        g.signal(event,at);self.assertNotIn('BEARISH',g.pending)
    def test_intermediate_minute_cannot_enter(self):
        from datetime import timedelta
        g,at,e=self.gate();g.owner='NONE'
        event=e.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={})
        g.signal(event,at)
        snap=SimpleNamespace(ready=True,rsi9=40,ema3_rsi=45,wma21_rsi=50)
        entries,checks=g.evaluate(minute=at,current=snap,reference=SimpleNamespace(ready=True,wma21_rsi=52),price=100)
        self.assertFalse(entries);self.assertFalse(checks);self.assertIsNone(g.pending['BEARISH']['armed_at'])

def compare(output):
    import hilega_pending_previous10_research as stats
    import hilega_existing_ema10_wma_combined_last10_research as base
    report=json.loads((output/'report.json').read_text());old=json.loads((OLD_ROOT/'report.json').read_text())
    if report['status']!='COMPLETE':return
    if old['status']!='COMPLETE' or old['model']!='EXISTING_1M_DIRECTIONAL_EMA10_THRESHOLD_WMA_RSI_EXCEPTION_40_60_V3':raise ValueError('PREVIOUS_40_60_REPORT_REQUIRED')
    labels=('Existing strategy','Previous 1m + EMA10 + WMA/exception','New 5m + WMA/exception; original exits')
    totals={label:[] for label in labels}
    lines=['# Five-minute confirmation; EMA10 and reversal override disabled','',
        'Research only; gross NIFTY points, no fills/costs. Persistence and original ten-minute window retained. This changes confirmation cadence and exit validation together; it does not isolate either effect.','',
        '| Date | Existing points | Previous combined points | New strategy points | Change vs previous |','|---|---:|---:|---:|---:|']
    details=['# Daily signal comparison','','Times IST. Cell: entry–exit · NIFTY points. Exact direction/setup identities; dash means no executed entry, not automatic proof of rejection. Explicit veto details remain in daily-signal-comparison.md.','']
    for day in report['session_dates']:
        new=json.loads((output/'sessions'/(day+'.json')).read_text());prior=json.loads((OLD_ROOT/'sessions'/(day+'.json')).read_text())
        if old['provenance'][day]['input_sha256']!=report['provenance'][day]['input_sha256']:raise ValueError('PREVIOUS_INPUT_HASH_MISMATCH')
        variants=(new['EXISTING'],prior['COMBINED'],new['COMBINED']);points=[stats.stats(r['trades'])['points'] for r in variants]
        for t in new['COMBINED']['trades']:
            from datetime import datetime
            at=datetime.fromisoformat(t['entry_time'])
            if at.minute%5 or at.second or at.microsecond:raise ValueError('OFF_FIVE_MINUTE_ENTRY')
        if any(e['event'].startswith('EMA_EXIT') or e['event']=='CONFIRMED_OPPOSITE_EXIT_OVERRIDE' for e in new['COMBINED']['policy_events']):raise ValueError('DISABLED_FEATURE_USED')
        lines.append(f'| {day} | {points[0]:+.2f} | {points[1]:+.2f} | {points[2]:+.2f} | {points[2]-points[1]:+.2f} |')
        for label,r in zip(labels,variants):totals[label].extend(r['trades'])
        details+=['','## '+day,'','| Direction | Setup available | '+' | '.join(labels)+' |','|---|---|---|---|---|']
        identities=sorted({(t['direction'],t['signal_time']) for r in variants for t in r['trades']},key=lambda x:(x[1],x[0]))
        for side,signal in identities:
            cells=[base.cell([t for t in r['trades'] if (t['direction'],t['signal_time'])==(side,signal)]) for r in variants]
            details.append('| '+side+' | '+signal[11:16]+' | '+' | '.join(cells)+' |')
    summary={key:stats.stats(value) for key,value in totals.items()};report['three_policy_comparison']=summary
    report['disabled_features_verified']=True
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines+=['','| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for key,s in summary.items():lines.append(f"| {key} | {s['trades']} | {s['points']:+.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    (output/'cadence-comparison.md').write_text('\n'.join(lines+details)+'\n');print('\n'.join(lines+details))

def main():
    import hilega_existing_ema10_wma_combined_last10_research as base
    import hilega_five_min_confirmation_research as five
    import hilega_existing_ema10_wma_exception_40_60_last10_research as exception
    source=inspect.getsource(base.main)
    changes={
        'frames=ema.ema_frames(engine,day,raw,warm,p.dt)':'frames={}  # Price EMA10 disabled; no EMA10 calculation required.',
        'data/research/hilega-existing-ema10-wma-combined-last10-20261016':str(NEW_ROOT),
        'Checks,corrected.Checks,threshold.Checks':'Checks,five.Checks,exception.Checks,threshold.Checks',
        'Existing strategy + corrected EMA10 + threshold WMA lock — ten sessions':'Five-minute confirmation + WMA lock / exceptions; original exits — ten sessions',
        'COMBINED uses EXISTING 1m confirmation, persistence, ten-minute expiry, direction watch and canonical cancellation.':
            'COMBINED uses completed 5m confirmation with persistence and gap expansion compared across consecutive completed 5m readings. Existing setup generation keeps minute-gap inputs. Ten-minute expiry, direction watch and canonical cancellation retained.',
        'Existing dual exit AND bullish close<price EMA10 / bearish close>price EMA10, same completed 5m boundary; no latch; 14:55 override.':
            'Original dual exit and 14:55 cutoff only. EMA10 exit DISABLED; opposite reversal override DISABLED.',
        'no unlimited retention, no RSI/EMA exception.':
            'no unlimited retention. RSI/EMA exception enabled: completed RSI9 and EMA3 both>40 for bullish under bearish lock, both<60 for bearish under bullish lock. Lock veto consumes confirmation.',
        'wm=lock.completed_frames(baseline,p.dt);first=min(wm)':
            "wm=lock.completed_frames(baseline,p.dt)\n            for audit_row in baseline['audit']:\n                boundary=p.dt(audit_row['checkpoint'])\n                if boundary in wm and audit_row.get('completed_5m_indicators') and audit_row.get('nifty_close') is not None:\n                    wm[boundary].update(rsi9=audit_row['completed_5m_indicators']['rsi9'],ema3=audit_row['completed_5m_indicators']['ema3'])\n            first=min(wm)",
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('BASE_RUNNER_SOURCE_DIFFERS:'+old)
        source=source.replace(old,new,1)
    namespace=dict(vars(base));namespace.update(MODEL=MODEL,Checks=Checks,five=five,exception=exception,combined_gate=combined_gate)
    exec(compile(source,'<five-minute-original-exit-batch>','exec'),namespace)
    import sys
    try:namespace['main']()
    except SystemExit as exc:
        if exc.code not in (0,None) or '--test' in sys.argv:raise
    output=NEW_ROOT
    for i,arg in enumerate(sys.argv):
        if arg=='--output':output=Path(sys.argv[i+1])
        elif arg.startswith('--output='):output=Path(arg.split('=',1)[1])
    compare(output)

if __name__=='__main__':main()
