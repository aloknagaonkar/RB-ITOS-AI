"""Same ten sessions: original 1m entries + directional EMA10 + WMA lock + RSI/EMA exception.
Research only; no broker requests, live changes, retained candidates or service control.
"""
import inspect
import json
import math
from pathlib import Path
import unittest
from datetime import timedelta

MODEL='EXISTING_1M_DIRECTIONAL_EMA10_THRESHOLD_WMA_RSI_EXCEPTION_V2'
OLD_ROOT=Path('data/research/hilega-existing-ema10-wma-combined-last10-20261016')
NEW_ROOT=Path('data/research/hilega-existing-ema10-wma-exception-last10-20261016')

def exception_allows(lock_side,entry_side,rsi,ema):
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=100 for v in (rsi,ema)):
        raise ValueError('INVALID_COMPLETED_RSI_EMA')
    return ((lock_side=='BEARISH' and entry_side=='BULLISH' and rsi>45 and ema>45)
        or (lock_side=='BULLISH' and entry_side=='BEARISH' and rsi<55 and ema<55))

def combined_gate(engine,frames,wm,lock,corrected,threshold):
    import hilega_existing_ema10_wma_combined_last10_research as base
    Parent=base.combined_gate(engine,frames,wm,lock,corrected,threshold)
    class WithException(Parent):
        def evaluate(self,**kwargs):
            at=kwargs['minute']+timedelta(minutes=1)
            boundary=at.replace(minute=at.minute-at.minute%5,second=0,microsecond=0)
            normal=self.direction_lock.permits
            def permits(side):
                if normal(side):return True
                frame=wm.get(boundary)
                if frame is None:raise ValueError('LATEST_COMPLETED_EXCEPTION_FRAME_REQUIRED')
                allowed=exception_allows(self.direction_lock.side,side,frame['rsi9'],frame['ema3'])
                self.policy_events.append(dict(event='COMBINED_RSI_EMA_EXCEPTION_CHECK',time=at.isoformat(),
                    setup_available=None,direction=side,lock=self.direction_lock.side,
                    indicator_available_at=boundary.isoformat(),rsi9=frame['rsi9'],ema3_rsi=frame['ema3'],allowed=allowed))
                return allowed
            self.direction_lock.permits=permits
            try:return super().evaluate(**kwargs)
            finally:del self.direction_lock.permits
    return WithException

class Checks(unittest.TestCase):
    def test_bull_requires_both_above45(self):
        self.assertTrue(exception_allows('BEARISH','BULLISH',46,46))
        self.assertFalse(exception_allows('BEARISH','BULLISH',60,44))
    def test_bear_requires_both_below55(self):
        self.assertTrue(exception_allows('BULLISH','BEARISH',54,54))
        self.assertFalse(exception_allows('BULLISH','BEARISH',40,56))
    def test_equal_threshold_rejected(self):
        self.assertFalse(exception_allows('BEARISH','BULLISH',45,46))
        self.assertFalse(exception_allows('BULLISH','BEARISH',54,55))
    def test_non_finite_rejected(self):
        with self.assertRaises(ValueError):exception_allows('BEARISH','BULLISH',float('nan'),60)
    def test_exception_preserves_lock_and_uses_completed_frame_for_minute_entry(self):
        from datetime import datetime
        import hilega_ema10_directional_oct14_research as corrected
        import hilega_wma_threshold_only_oct14_research as threshold
        import hilega_post_entry_wma_lock_today_research as lock
        from types import SimpleNamespace
        boundary=datetime.fromisoformat('2026-10-14T11:00:00+05:30');at=boundary+timedelta(minutes=2)
        class Base:
            def __init__(self):self.owner='NONE';self.active=None;self.pending={'BEARISH':{}}
            def evaluate(self,**kwargs):
                self.owner='BEARISH';self.active=True;self.pending.clear()
                return ['BEARISH'],[dict(status='ENTRY',reasons=[],direction='BEARISH',
                    signal_available_at=boundary.isoformat(),decision_timestamp=at.isoformat())]
        wm={boundary:dict(wma21=60,previous_wma21=61,rsi9=54,ema3=54,available_at=boundary.isoformat())}
        Gate=combined_gate(SimpleNamespace(WmaGapGate=Base,direction=lambda e:e),{},wm,lock,corrected,threshold)
        g=Gate();g.direction_lock.observe(boundary,60,61,'NONE')
        entries,_=g.evaluate(minute=at-timedelta(minutes=1))
        self.assertEqual(entries,['BEARISH']);self.assertEqual(g.direction_lock.side,'BULLISH')
        self.assertFalse(g.direction_lock.permits('BEARISH'));self.assertFalse(g.pending)
        event=next(e for e in g.policy_events if e['event']=='COMBINED_RSI_EMA_EXCEPTION_CHECK')
        self.assertEqual(event['indicator_available_at'],boundary.isoformat())

def append_comparison(output):
    import hilega_pending_previous10_research as stats
    import hilega_existing_ema10_wma_combined_last10_research as base
    report=json.loads((output/'report.json').read_text());old=json.loads((OLD_ROOT/'report.json').read_text())
    days=report['session_dates']
    if report['status']!='COMPLETE':return
    labels=('Existing strategy','Combined without exception','Combined + RSI/EMA exception')
    totals={'EXISTING':[],'WITHOUT_EXCEPTION':[],'WITH_EXCEPTION':[]};daily=[]
    lines=['','## Three-policy comparison','','| Date | Existing points | Combined without exception | Combined + exception | Exception change |','|---|---:|---:|---:|---:|']
    details=['# Signal comparison: adding the RSI/EMA exception','','Times IST; cells show entry–exit and gross NIFTY points. Exact direction/setup identities are matched. Dash is no executed entry, not automatic proof of a veto.','']
    for day in days:
        new=json.loads((output/'sessions'/(day+'.json')).read_text())
        previous=json.loads((OLD_ROOT/'sessions'/(day+'.json')).read_text())
        if stats.frozen_parity(previous['EXISTING'],new['EXISTING'])['status']!='PASS':raise ValueError('PRIOR_EXISTING_PARITY_FAILED:'+day)
        variants=(new['EXISTING'],previous['COMBINED'],new['COMBINED'])
        values=[stats.stats(r['trades'])['points'] for r in variants]
        for key,value in zip(totals,variants):totals[key].extend(value['trades'])
        lines.append(f'| {day} | {values[0]:+.2f} | {values[1]:+.2f} | {values[2]:+.2f} | {values[2]-values[1]:+.2f} |')
        daily.append(dict(session_date=day,existing=values[0],without_exception=values[1],with_exception=values[2]))
        details+=['','## '+day,'','| Direction | Setup available | '+' | '.join(labels)+' |','|---|---|---|---|---|']
        identities=sorted({(t['direction'],t['signal_time']) for r in variants for t in r['trades']},key=lambda x:(x[1],x[0]))
        for side,signal in identities:
            cells=[base.cell([t for t in r['trades'] if (t['direction'],t['signal_time'])==(side,signal)]) for r in variants]
            details.append('| '+side+' | '+signal[11:16]+' | '+' | '.join(cells)+' |')
        details+=['','### Exception checks','','| Decision | Latest completed 5m | Direction | Lock | RSI9 | EMA3 of RSI9 | Allowed |','|---|---|---|---|---:|---:|---|']
        for e in new['COMBINED']['policy_events']:
            if e['event']=='COMBINED_RSI_EMA_EXCEPTION_CHECK':details.append(f"| {e['time'][11:16]} | {e['indicator_available_at'][11:16]} | {e['direction']} | {e['lock']} | {e['rsi9']:.3f} | {e['ema3_rsi']:.3f} | {e['allowed']} |")
    report['three_policy_comparison']={key:stats.stats(trades) for key,trades in totals.items()};report['daily_three_policy']=daily
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    lines+=['','| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for label,s in zip(labels,report['three_policy_comparison'].values()):lines.append(f"| {label} | {s['trades']} | {s['points']:+.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    with (output/'summary.md').open('a') as f:f.write('\n'.join(lines)+'\n')
    (output/'three-policy-signal-comparison.md').write_text('\n'.join(details)+'\n')
    print('\n'.join(lines));print('\n'.join(details))

def main():
    import hilega_existing_ema10_wma_combined_last10_research as base
    source=inspect.getsource(base.main)
    changes={
        str(OLD_ROOT):str(NEW_ROOT),
        'Existing strategy + corrected EMA10 + threshold WMA lock — ten sessions':'Existing strategy + corrected EMA10 + WMA lock + RSI/EMA exception — ten sessions',
        'no unlimited retention, no RSI/EMA exception.':'no unlimited retention. Exception: bullish under bearish lock requires completed RSI9>45 AND EMA3 of RSI>45; bearish under bullish lock requires both<55. Uses latest completed 5m indicators for each original 1m confirmation. Entry veto bypass only; lock unchanged.',
        'Checks,corrected.Checks,threshold.Checks':'Checks,base.Checks,corrected.Checks,threshold.Checks',
        "wm=lock.completed_frames(baseline,p.dt);first=min(wm)":
            "wm=lock.completed_frames(baseline,p.dt)\n            for audit_row in baseline['audit']:\n                boundary=p.dt(audit_row['checkpoint'])\n                if boundary in wm and audit_row.get('completed_5m_indicators') and audit_row.get('nifty_close') is not None:\n                    wm[boundary].update(rsi9=audit_row['completed_5m_indicators']['rsi9'],ema3=audit_row['completed_5m_indicators']['ema3'])\n            first=min(wm)",
        "if digest!=prior['provenance'][day]['raw_and_warm_sha256']:raise ValueError('BASELINE_INPUT_HASH_MISMATCH')":
            "if digest!=prior['provenance'][day]['raw_and_warm_sha256']:raise ValueError('BASELINE_INPUT_HASH_MISMATCH')\n            prior_combined=json.loads((OLD_ROOT/'report.json').read_text())\n            if prior_combined['status']!='COMPLETE' or prior_combined['model']!=base.MODEL or digest!=prior_combined['provenance'][day]['input_sha256']:raise ValueError('PRIOR_COMBINED_IDENTITY_OR_INPUT_MISMATCH')",
    }
    for old,new in changes.items():
        if old not in source:raise ValueError('COMBINED_RUNNER_SOURCE_DIFFERS:'+old)
        source=source.replace(old,new)
    # Execute a copy with an isolated globals dictionary; imported base stays unchanged.
    namespace=dict(vars(base));namespace.update(base=base,MODEL=MODEL,OLD_ROOT=OLD_ROOT,Checks=Checks,combined_gate=combined_gate)
    exec(compile(source,'<combined-rsi-ema-exception>','exec'),namespace)
    import sys
    testing='--test' in sys.argv
    try:namespace['main']()
    except SystemExit as exc:
        if exc.code not in (0,None) or testing:raise
    output=NEW_ROOT
    if '--output' in sys.argv:output=Path(sys.argv[sys.argv.index('--output')+1])
    else:
        for arg in sys.argv:
            if arg.startswith('--output='):output=Path(arg.split('=',1)[1])
    append_comparison(output)

if __name__=='__main__':main()
