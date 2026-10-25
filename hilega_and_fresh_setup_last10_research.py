"""Research only: AND40/60 + fresh eligible 5m setups, original 1m confirmation/exits.
Run from RB-ITOS-AI with the existing research helper modules. No orders/live edits.
"""
import inspect
import json
import linecache
from pathlib import Path
from types import SimpleNamespace
import unittest

MODEL='AND_40_60_FRESH_5M_SETUP_ORIGINAL_1M_CONFIRMATION_V1'
NEW_ROOT=Path('data/research/hilega-and-fresh-setup-last10-20261016')
OLD_ROOT=Path('data/research/hilega-existing-minute-wma-exception-no-ema-last10-20261016')
WARNING=('Research only; gross NIFTY points without option fills/costs. '
    'Fresh alternative setup eligibility at each completed 5m boundary removes ONLY the used-alignment-episode veto. '
    'Completed alignment, positive expanding minute gap, direction watch, flat position, no same-side pending and cutoff remain mandatory. '
    'Existing pending candidates are not refreshed or extended. Original 1m strength/persistence/gap confirmation and ten-minute expiry retained. '
    'WMA from-open lock >55 / <45; AND exception: bullish RSI9>40 AND EMA3-of-RSI>40 under bearish lock; '
    'bearish RSI9<60 AND EMA3-of-RSI<60 under bullish lock. Completed 5m inputs only. '
    'Original dual exits; EMA10 exit and reversal override disabled. '
    'Historical frozen reconstruction; Oct16 mixes recorded/API inputs. Baseline parity does not establish all historical live-minute parity. No live changes.')


def fresh_replay(engine):
    """New function/globals only: preserve original replay and gate implementations."""
    source=inspect.getsource(engine.replay)
    anchor='   if not aligned:episode[side]=False'
    if source.count(anchor)!=1:
        raise ValueError('FRESH_SETUP_SOURCE_ANCHOR_DIFFERS')
    source=source.replace(anchor,anchor+"\n   if bar:episode[side]=False  # Fresh eligibility, never refresh an existing pending candidate.",1)
    filename='<hilega-and-fresh-5m-replay>'
    linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
    namespace=dict(engine.replay.__globals__)
    exec(compile(source,filename,'exec'),namespace)
    return namespace['replay']


def combined_gate(engine,frames,wm,lock,corrected,threshold):
    import hilega_existing_minute_wma_exception_no_ema_last10_research as previous
    return previous.combined_gate(engine,{},wm,lock,corrected,threshold)


class Checks(unittest.TestCase):
    def test_replay_is_isolated_and_keeps_other_setup_vetoes(self):
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        original=inspect.getsource(engine.replay)
        changed=inspect.getsource(fresh_replay(engine))
        self.assertEqual(inspect.getsource(engine.replay),original)
        for token in ('g.can_signal(side,at)','and aligned','and expanding',"side not in g.pending", "g.owner=='NONE'", "<'14:55'"):
            self.assertIn(token,changed)
        self.assertEqual(changed.replace("\n   if bar:episode[side]=False  # Fresh eligibility, never refresh an existing pending candidate.",''),original)

    def harness(self):
        from datetime import datetime
        from market_lab import hilega_v2_alignment_replay_v1 as engine
        import hilega_post_entry_wma_lock_today_research as lock
        import hilega_wma_threshold_only_oct14_research as threshold
        at=datetime.fromisoformat('2026-10-05T10:00:00+05:30')
        wm={at:dict(wma21=70,previous_wma21=71,rsi9=65,ema3=65,available_at=at.isoformat())}
        from datetime import timedelta
        later=at+timedelta(minutes=5)
        wm[later]=dict(wma21=69,previous_wma21=70,rsi9=55,ema3=55,available_at=later.isoformat())
        gate=combined_gate(engine,{},wm,lock,None,threshold)(opposite_switch=True)
        gate.update_lock(at)
        return gate,at,engine

    def signal(self,g,at,engine):
        ev=engine.StrategyEvent('ENTRY_BEARISH_ROUTE_B_STRUCTURAL',at,None,'IDLE','ARMED',details={})
        g.signal(ev,at)

    def evaluate(self,g,at,offset,ema=49):
        from datetime import timedelta
        snap=SimpleNamespace(ready=True,rsi9=ema-1,ema3_rsi=ema,wma21_rsi=50)
        return g.evaluate(minute=at+timedelta(minutes=offset),current=snap,
            reference=SimpleNamespace(ready=True,wma21_rsi=52),price=100)

    def test_blocked_candidate_consumed_then_new_setup_can_confirm(self):
        from datetime import timedelta
        g,at,engine=self.harness();self.signal(g,at,engine)
        for offset,ema in ((0,49),(1,49),(2,47)):
            entries,checks=self.evaluate(g,at,offset,ema)
        self.assertFalse(entries);self.assertEqual(g.owner,'NONE');self.assertNotIn('BEARISH',g.pending)
        self.assertTrue(any(e.get('outcome')=='BLOCKED_WMA_LOCK' for e in g.policy_events))
        fresh=at+timedelta(minutes=5);self.signal(g,fresh,engine)
        for offset,ema in ((5,49),(6,49),(7,47)):
            entries,checks=self.evaluate(g,at,offset,ema)
        self.assertEqual(len(entries),1);self.assertEqual(g.owner,'BEARISH')
        self.assertEqual(checks[0]['signal_available_at'],fresh.isoformat())
        self.assertEqual(checks[0]['decision_timestamp'][11:16],'10:08')
        self.assertEqual(g.direction_lock.side,'BULLISH')

    def test_new_setup_does_not_enter_on_permission_alone(self):
        from datetime import timedelta
        g,at,engine=self.harness();self.signal(g,at+timedelta(minutes=5),engine)
        entries,_=self.evaluate(g,at,5,49)
        self.assertFalse(entries);self.assertEqual(g.owner,'NONE')

    def test_expiry_remains_ten_minutes(self):
        g,at,engine=self.harness();self.signal(g,at,engine)
        entries,checks=self.evaluate(g,at,10,49)
        self.assertFalse(entries);self.assertNotIn('BEARISH',g.pending)
        self.assertIn('WINDOW_EXPIRED',checks[0]['reasons'])

    def test_and_not_or(self):
        from hilega_existing_ema10_wma_exception_40_60_last10_research import exception_allows
        self.assertFalse(exception_allows('BULLISH','BEARISH',59,65))
        self.assertTrue(exception_allows('BULLISH','BEARISH',59,59))
        self.assertFalse(exception_allows('BEARISH','BULLISH',45,39))


def compare(output):
    import hilega_pending_previous10_research as stats
    import hilega_existing_ema10_wma_combined_last10_research as base
    report=json.loads((output/'report.json').read_text())
    if report['status']!='COMPLETE':return
    prior=json.loads((OLD_ROOT/'report.json').read_text())
    if prior['status']!='COMPLETE' or prior['model']!='EXISTING_1M_WMA_EXCEPTION_40_60_ORIGINAL_EXITS_V1':
        raise ValueError('COMPLETE_PREVIOUS_AND_REPORT_REQUIRED')
    labels=('Existing strategy','Previous AND','AND + fresh 5m setups')
    totals={label:[] for label in labels}
    lines=['# AND exception + fresh five-minute setup eligibility','',WARNING,'',
        '| Date | Existing points | Previous AND | Fresh setups + AND | Change vs AND |',
        '|---|---:|---:|---:|---:|']
    details=['# Signal-wise comparison','',WARNING,'',
        'Times IST. Cells are actual entry–exit and gross NIFTY points. BLOCKED means a recorded lock veto. '
        'A dash alone means no entry from that exact setup, not an explicit rejection. '
        'A blocked setup has no realized P&L. A later fresh setup is a different signal.','']
    for day in report['session_dates']:
        new=json.loads((output/'sessions'/(day+'.json')).read_text())
        old=json.loads((OLD_ROOT/'sessions'/(day+'.json')).read_text())
        if prior['provenance'][day]['input_sha256']!=report['provenance'][day]['input_sha256']:
            raise ValueError('PREVIOUS_AND_INPUT_HASH_MISMATCH')
        if stats.frozen_parity(old['EXISTING'],new['EXISTING'])['status']!='PASS':
            raise ValueError('PREVIOUS_AND_BASELINE_PARITY_FAILED')
        variants=(new['EXISTING'],old['COMBINED'],new['COMBINED'])
        if any(e['event'].startswith('EMA_EXIT') or e['event']=='CONFIRMED_OPPOSITE_EXIT_OVERRIDE' for e in new['COMBINED']['policy_events']):
            raise ValueError('DISABLED_FEATURE_USED')
        values=[stats.stats(v['trades'])['points'] for v in variants]
        lines.append(f'| {day} | {values[0]:+.2f} | {values[1]:+.2f} | {values[2]:+.2f} | {values[2]-values[1]:+.2f} |')
        for label,v in zip(labels,variants):totals[label].extend(v['trades'])
        decisions=[e for e in new['COMBINED']['policy_events'] if e['event']=='COMBINED_ENTRY_DECISION']
        identities={(t['direction'],t['signal_time']) for v in variants for t in v['trades']}
        identities.update((e['direction'],e['setup_available']) for e in decisions)
        details+=['','## '+day,'','| Direction | Setup available | Existing strategy | Previous AND | Fresh setups + AND | Decision / reason |',
            '|---|---|---|---|---|---|']
        for side,signal in sorted(identities,key=lambda x:(x[1],x[0])):
            cells=[base.cell([t for t in v['trades'] if (t['direction'],t['signal_time'])==(side,signal)]) for v in variants]
            matched=[e for e in decisions if (e['direction'],e['setup_available'])==(side,signal)]
            reason='; '.join(('PASS' if e['outcome']=='PASS' else 'BLOCKED: '+e['lock']+' lock; AND exception failed')+' at '+e['time'][11:16] for e in matched) or 'NO ENTRY from this setup; inspect setup/confirmation audit'
            details.append('| '+side+' | '+signal[11:16]+' | '+' | '.join(cells)+' | '+reason+' |')
        details+=['','### Fresh setup prerequisites (failed checks)','','| Boundary | Direction | Failed prerequisites |','|---|---|---|']
        for row in new['COMBINED']['setup_diagnostics']:
            details.append('| '+row['time'][11:16]+' | '+row['direction']+' | '+(', '.join(row['failed']) or 'ALL PASS')+' |')
    summary={label:stats.stats(trades) for label,trades in totals.items()}
    lines+=['','| Policy | Trades | Winning points | Losing points | Net points | Winners | Losers | Drawdown |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for label,s in summary.items():
        lines.append(f"| {label} | {s['trades']} | {s['gross_winning_points']:+.2f} | {-s['gross_losing_points']:.2f} | {s['points']:+.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    report.update(fresh_setup_comparison=summary,disabled_features_verified=True)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/'fresh-setup-comparison.md').write_text('\n'.join(lines)+'\n')
    (output/'daily-signal-comparison.md').write_text('\n'.join(details)+'\n')
    print('\n'.join(lines));print('SIGNAL TABLE:',output/'daily-signal-comparison.md')


def main():
    import hilega_existing_ema10_wma_combined_last10_research as base
    import hilega_existing_ema10_wma_exception_40_60_last10_research as exception
    import hilega_existing_minute_wma_exception_no_ema_last10_research as restored
    source=inspect.getsource(base.main)
    changes={
        'data/research/hilega-existing-ema10-wma-combined-last10-20261016':str(NEW_ROOT),
        'Checks,corrected.Checks,threshold.Checks':'Checks,restored.Checks,exception.Checks,threshold.Checks',
        'frames=ema.ema_frames(engine,day,raw,warm,p.dt)':'frames={}',
        "replay=engine.replay),day,raw,warm,asof,'CURRENT')":"replay=fresh_replay(engine)),day,raw,warm,asof,'CURRENT')",
        'wm=lock.completed_frames(baseline,p.dt);first=min(wm)':
            "wm=lock.completed_frames(baseline,p.dt)\n            for audit_row in baseline['audit']:\n                boundary=p.dt(audit_row['checkpoint'])\n                if boundary in wm and audit_row.get('completed_5m_indicators') and audit_row.get('nifty_close') is not None:\n                    wm[boundary].update(rsi9=audit_row['completed_5m_indicators']['rsi9'],ema3=audit_row['completed_5m_indicators']['ema3'])\n            first=min(wm)",
        'Existing strategy + corrected EMA10 + threshold WMA lock — ten sessions':'AND exceptions + fresh 5m setups; original 1m confirmation — ten sessions',
    }
    for old,new in changes.items():
        if source.count(old)!=1:raise ValueError('BASE_RUNNER_SOURCE_DIFFERS:'+old)
        source=source.replace(old,new,1)
    begin=source.index("    warning=('Research only:")
    end=source.index('\n    summary=',begin)
    source=source[:begin]+'    warning=WARNING'+source[end:]
    namespace=dict(vars(base),MODEL=MODEL,Checks=Checks,restored=restored,exception=exception,
        fresh_replay=fresh_replay,combined_gate=combined_gate,WARNING=WARNING)
    exec(compile(source,'<and-fresh-setup-batch>','exec'),namespace)
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
