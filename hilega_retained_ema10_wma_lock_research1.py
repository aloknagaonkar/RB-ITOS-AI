"""Offline retained 5m/no-persistence + price EMA10 exit + post-entry WMA lock.

Locked candidates stay pending. A WMA veto is NOT an executed confirmation and
does not clear either pending direction. Only an allowed actual entry clears
the other pending contexts. No API calls, orders, services or live changes.
"""
import argparse
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from datetime import datetime,timedelta
import math

def lock_exception_allows(lock_side,entry_side,frame):
    """RSI9 and EMA3 OF RSI, not a price EMA. Strict current-side thresholds."""
    rsi,ema=frame['rsi9'],frame['ema3']
    if any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or not 0<=v<=100 for v in (rsi,ema)):
        raise ValueError('INVALID_RSI_EMA_EXCEPTION_INPUT')
    return ((lock_side=='BEARISH' and entry_side=='BULLISH' and rsi>55 and ema>55)
            or (lock_side=='BULLISH' and entry_side=='BEARISH' and rsi<45 and ema<45))

def retaining_lock_gate(Base,direction,frames,lock):
    Parent=lock.lock_gate(Base,direction,frames)
    class RetainingLock(Parent):
        def evaluate(self,**kwargs):
            before=copy.deepcopy(self.pending);event_start=len(self.policy_events)
            entries,checks=super().evaluate(**kwargs)
            if any(c.get('status')=='POST_ENTRY_WMA_LOCK_BLOCKED' for c in checks):
                # The inner confirmation gate provisionally accepted and cleared
                # pending contexts. Roll back that clearing because no entry was
                # permitted; keep freshly updated indicator history for next tick.
                self.pending=before
                for event in self.policy_events[event_start:]:
                    if event.get('event')=='ENTRY_CONFIRMED_OTHER_PENDING_CANCELLED':
                        event['event']='ENTRY_CHECKS_PASSED_BUT_WMA_LOCK_VETOED'
                        event['cancelled_pending']=[]
                self.policy_events.append(dict(event='LOCK_VETO_PENDING_RETAINED',
                    time=(kwargs['minute']+timedelta(minutes=1)).isoformat(),pending_directions=list(self.pending)))
            return entries,checks
    return RetainingLock

def exception_lock_gate(Base,direction,frames,indicators,lock):
    Parent=retaining_lock_gate(Base,direction,frames,lock)
    class ExceptionGate(Parent):
        def evaluate(self,**kwargs):
            at=kwargs['minute']+timedelta(minutes=1)
            normal_permits=self.direction_lock.permits
            def permits(side):
                if normal_permits(side):return True
                if at.minute%5:raise ValueError('LOCK_EXCEPTION_REQUIRES_COMPLETED_5M')
                frame=indicators.get(at)
                if frame is None:raise ValueError('COMPLETED_RSI_EMA_EXCEPTION_FRAME_REQUIRED')
                allowed=lock_exception_allows(self.direction_lock.side,side,frame)
                self.policy_events.append(dict(event='WMA_LOCK_EXCEPTION_CHECK',time=at.isoformat(),direction=side,
                    lock=self.direction_lock.side,rsi9=frame['rsi9'],ema3_rsi=frame['ema3'],allowed=allowed,
                    rule='RSI9_AND_EMA3_RSI_ABOVE_55' if side=='BULLISH' else 'RSI9_AND_EMA3_RSI_BELOW_45'))
                return allowed
            self.direction_lock.permits=permits
            try:return super().evaluate(**kwargs)
            finally:
                # Restore the normal bound method after this isolated decision.
                del self.direction_lock.permits
    return ExceptionGate

class Checks(unittest.TestCase):
    def test_exception_bullish_requires_both_above55(self):
        self.assertTrue(lock_exception_allows('BEARISH','BULLISH',dict(rsi9=60,ema3=56)))
        self.assertFalse(lock_exception_allows('BEARISH','BULLISH',dict(rsi9=60,ema3=54)))
    def test_exception_bearish_requires_both_below45(self):
        self.assertTrue(lock_exception_allows('BULLISH','BEARISH',dict(rsi9=40,ema3=44)))
        self.assertFalse(lock_exception_allows('BULLISH','BEARISH',dict(rsi9=40,ema3=46)))
    def test_exception_equality_not_allowed(self):
        self.assertFalse(lock_exception_allows('BEARISH','BULLISH',dict(rsi9=55,ema3=56)))
        self.assertFalse(lock_exception_allows('BULLISH','BEARISH',dict(rsi9=44,ema3=45)))
    def test_exception_invalid_indicator_rejected(self):
        with self.assertRaises(ValueError):lock_exception_allows('BEARISH','BULLISH',dict(rsi9=float('nan'),ema3=60))
    def test_exception_entry_preserves_lock_and_clears_pending(self):
        import hilega_post_entry_wma_lock_today_research as lock
        at=datetime.fromisoformat('2026-08-26T14:15:00+05:30')
        class Base:
            def __init__(self):self.owner='NONE';self.active=None;self.pending={'BULLISH':{}};self.policy_events=[]
            def evaluate(self,**kwargs):
                self.owner='BULLISH';self.active=True;self.pending.clear()
                return ['BULLISH'],[dict(status='ENTRY',reasons=[])]
        Gate=exception_lock_gate(Base,lambda e:e,{at:dict(wma21=40,previous_wma21=39,available_at=at.isoformat())},
                                 {at:dict(rsi9=60,ema3=56)},lock)
        g=Gate();g.direction_lock.side='BEARISH'
        entries,checks=g.evaluate(minute=at-timedelta(minutes=1))
        self.assertEqual(entries,['BULLISH']);self.assertFalse(g.pending);self.assertEqual(g.direction_lock.side,'BEARISH')
        self.assertFalse(g.direction_lock.permits('BULLISH'))
    def harness(self,close,ema,wma=60,previous=59):
        import hilega_ema10_exit_day_research as exits
        import hilega_post_entry_wma_lock_today_research as lock
        at=datetime.fromisoformat('2026-08-26T11:00:00+05:30')
        class Base:
            def __init__(self):self.owner='BULLISH';self.active=True;self.pending={};self.policy_events=[]
            def close(self,event,at,price):self.owner='NONE';self.active=None;return event
        Exit=exits.exit_gate(Base,{at:dict(close=close,ema10=ema,candle_label='10:55')})
        Gate=retaining_lock_gate(Exit,lambda e:e,{at:dict(wma21=wma,previous_wma21=previous,available_at=at.isoformat())},lock)
        return Gate(),at,SimpleNamespace(exit_reason='BOTH_RSI9_EMA3_OPPOSITE_WMA21')
    def test_ema_hold_preserves_position_and_arms_lock(self):
        g,at,event=self.harness(99,100);self.assertIsNone(g.close(event,at,99))
        self.assertEqual(g.owner,'BULLISH');self.assertEqual(g.direction_lock.side,'BULLISH')
    def test_allowed_exit_preserves_lock_after_position_closed(self):
        g,at,event=self.harness(101,100);self.assertIs(g.close(event,at,101),event)
        self.assertEqual(g.owner,'NONE');self.assertEqual(g.direction_lock.side,'BULLISH')
    def test_cutoff_bypasses_ema_even_with_lock(self):
        g,at,event=self.harness(99,100);event.exit_reason='SESSION_CUTOFF_1455'
        self.assertIs(g.close(event,at,99),event);self.assertEqual(g.owner,'NONE')
    def test_lock_veto_restores_both_pending_candidates(self):
        import hilega_post_entry_wma_lock_today_research as lock
        at=datetime.fromisoformat('2026-08-26T11:00:00+05:30')
        class Base:
            def __init__(self):
                self.owner='NONE';self.active=None;self.pending={'BEARISH':{'available':at-timedelta(minutes=30)},'BULLISH':{'available':at}};self.policy_events=[]
            def evaluate(self,**kwargs):
                self.pending.clear();self.owner='BEARISH';self.active=True
                self.policy_events.append(dict(event='ENTRY_CONFIRMED_OTHER_PENDING_CANCELLED'))
                return ['BEARISH'],[dict(status='ENTRY',reasons=[])]
        Gate=retaining_lock_gate(Base,lambda e:e,{at:dict(wma21=60,previous_wma21=61,available_at=at.isoformat())},lock)
        g=Gate();g.direction_lock.side='BULLISH';before=copy.deepcopy(g.pending)
        entries,checks=g.evaluate(minute=at-timedelta(minutes=1))
        self.assertFalse(entries);self.assertEqual(g.pending,before);self.assertEqual(g.owner,'NONE')
        self.assertEqual(checks[0]['status'],'POST_ENTRY_WMA_LOCK_BLOCKED')

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--date',default='2026-08-26')
    ap.add_argument('--policy-module',default='hilega_retained_pending_day_research1')
    ap.add_argument('--research-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    ap.add_argument('--output',type=Path);ap.add_argument('--test',action='store_true');a=ap.parse_args()
    import hilega_ema10_exit_day_research as exits
    import hilega_post_entry_wma_lock_today_research as lock
    if a.test:
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (Checks,exits.Checks,lock.Checks))
        r=unittest.TextTestRunner(verbosity=2).run(suite);raise SystemExit(0 if r.wasSuccessful() else 1)
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    retained=importlib.import_module(a.policy_module)
    if not hasattr(retained,'five_gate_no_persistence'):raise ValueError('UPDATED_RETAINED_POLICY_REQUIRED')
    import hilega_pending_confirmation_research as p
    import hilega_pending_previous10_research as batch
    import hilega_vwap_confirmed36_research as support
    from hilega_vwap_wait_alignment_research import source_data
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    if engine.RULES['version']!=p.VERSION:raise ValueError('ENGINE_VERSION_MISMATCH')
    asof=p.dt(a.date+'T14:55:00+05:30')
    if asof>p.datetime.now(p.IST):raise ValueError('SESSION_NOT_COMPLETE')
    parent=json.loads((a.research_root/'3-month/report.json').read_text())
    if parent['strategy_version']!=p.VERSION:raise ValueError('SOURCE_VERSION_MISMATCH')
    sessions,grouped=source_data(a.research_root,parent,support)
    raw=grouped[a.date];warm=[(d,grouped[d]) for d in sessions if d<a.date and grouped.get(d)][-30:]
    if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
    saved_path=a.research_root/'replays'/(a.date+'.json');saved=json.loads(saved_path.read_text())
    if saved['session_date']!=a.date or saved['strategy_version']!=p.VERSION:raise ValueError('BASELINE_IDENTITY_MISMATCH')
    original=p.simulate(engine,a.date,raw,warm,asof,'CURRENT');parity=batch.frozen_parity(saved,original)
    if parity['status']!='PASS':raise ValueError('ORIGINAL_BASELINE_PARITY_NOT_PASS:'+json.dumps(parity))
    Base=retained.retained_gate(p.changed_gate(retained.five_gate_no_persistence(engine.WmaGapGate)),engine.direction)
    replay=retained.retained_replay(engine)
    em=exits.ema_frames(engine,a.date,raw,warm,p.dt);wm=lock.completed_frames(original,p.dt)
    Ema=exits.exit_gate(Base,em)
    indicators={p.dt(r['checkpoint']):r['completed_5m_indicators'] for r in original['audit']
                if r.get('nifty_close') is not None and r.get('completed_5m_indicators') and p.dt(r['checkpoint']).minute%5==0}
    specs=[('RETAINED_5M_NO_PERSISTENCE',Base),('RETAINED_5M_PLUS_EMA10_EXIT',Ema),
           ('RETAINED_5M_EMA10_WMA_LOCK',retaining_lock_gate(Ema,engine.direction,wm,lock)),
           ('RETAINED_5M_EMA10_WMA_EXCEPTION',exception_lock_gate(Ema,engine.direction,wm,indicators,lock))]
    results={'ORIGINAL_CURRENT_1M':original}
    for name,Gate in specs:
        results[name]=p.simulate(SimpleNamespace(WmaGapGate=Gate,replay=replay),a.date,raw,warm,asof,'CURRENT')
        batch.signature(results[name]['trades'])
    prior_path=Path('data/research/hilega-ema10-exit-'+a.date.replace('-',''))/'report.json'
    if not prior_path.exists():raise ValueError('PREVIOUS_EMA10_REPORT_REQUIRED:'+str(prior_path))
    prior=json.loads(prior_path.read_text());verified={}
    for name in ('RETAINED_5M_NO_PERSISTENCE','RETAINED_5M_PLUS_EMA10_EXIT'):
        verified[name]=batch.frozen_parity(prior['results'][name],results[name])
        if verified[name]['status']!='PASS':raise ValueError('PREVIOUS_POLICY_PARITY_NOT_PASS:'+name+':'+json.dumps(verified[name]))
    previous_stack=Path('data/research/hilega-retained-ema10-wma-lock-'+a.date.replace('-',''))/'report.json'
    if not previous_stack.exists():raise ValueError('PREVIOUS_WMA_LOCK_REPORT_REQUIRED:'+str(previous_stack))
    old_stack=json.loads(previous_stack.read_text())
    verified['RETAINED_5M_EMA10_WMA_LOCK']=batch.frozen_parity(old_stack['results']['RETAINED_5M_EMA10_WMA_LOCK'],results['RETAINED_5M_EMA10_WMA_LOCK'])
    if verified['RETAINED_5M_EMA10_WMA_LOCK']['status']!='PASS':raise ValueError('PREVIOUS_WMA_LOCK_PARITY_NOT_PASS')
    b=results['RETAINED_5M_PLUS_EMA10_EXIT']['trades'];n=results['RETAINED_5M_EMA10_WMA_LOCK']['trades']
    if b and (not n or any(b[0][k]!=n[0][k] for k in ('direction','entry_time','entry_price'))):raise ValueError('FIRST_NORMAL_ENTRY_CHANGED')
    output=a.output or Path('data/research/hilega-retained-ema10-wma-exception-'+a.date.replace('-',''));output.mkdir(parents=True,exist_ok=True)
    rules='Retained candidates, completed 5m confirmation, no persistence. Existing dual exit AND NIFTY close>price EMA10 for both directions on the same completed boundary; 14:55 cutoff override. Post-entry bullish lock requires active bullish position, rising WMA21 of RSI>55; bearish lock requires active bearish position, falling WMA<45. Locks survive exit; release on cross below55/above45 respectively, then NONE. No automatic opposite lock. WMA veto retains both pending candidates with fresh validation at each later boundary. EXCEPTION variant additionally permits bullish entry under bearish lock when completed RSI9>55 AND EMA3 of RSI>55; bearish entry under bullish lock when RSI9<45 AND EMA3 of RSI<45. These are current completed values, not a requirement for simultaneous fresh crosses. All normal entry checks must pass. Exception bypasses entry veto only and does not clear the lock. Price EMA10 is distinct from EMA3 of RSI. No EMA30.'
    report=dict(status='COMPLETE',session_date=a.date,baseline_parity=parity,prior_policy_parity=verified,
        comparisons={k:batch.stats(v['trades']) for k,v in results.items()},results=results,rules=rules,
        observation_only=True,orders_sent=False,warning='Frozen historical research, gross NIFTY points, no option fills/costs. Delayed exits and vetoed entries can change future strategy state. No live changes.',
        source_sha256={str(Path(m.__file__)):hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in (retained,exits,lock,engine)},
        input_sha256=hashlib.sha256(json.dumps([raw,warm],sort_keys=True,default=str).encode()).hexdigest())
    (output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    lines=['# Retained 5m + EMA10 exit + WMA lock exception — '+a.date,'',rules,'',report['warning'],'','All baseline parity checks: PASS','',
        '| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for k,s in report['comparisons'].items():lines.append(f"| {k} | {s['trades']} | {s['points']:.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','| Policy | Direction | Setup | Entry | Exit | Points |','|---|---|---|---|---|---:|']
    for k,r in results.items():
        for t in r['trades']:lines.append(f"| {k} | {t['direction']} | {t['signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['points']:.2f} |")
    events=results['RETAINED_5M_EMA10_WMA_EXCEPTION']['policy_events']
    lines+=['','## Lock changes','','| Time | Before | After | Active | WMA | Reason |','|---|---|---|---|---:|---|']
    for e in events:
        if e['event']=='POST_ENTRY_LOCK_CHANGE':lines.append(f"| {e['time'][11:16]} | {e['before']} | {e['after']} | {e['active_direction']} | {e['wma21']:.3f} | {e['reason']} |")
    lines+=['','## Confirmed candidate lock decisions','','| Time | Direction | WMA | Lock | Allowed |','|---|---|---:|---|---|']
    for e in events:
        if e['event']=='CONFIRMED_ENTRY_LOCK_CHECK':lines.append(f"| {e['time'][11:16]} | {e['direction']} | {e['wma21']:.3f} | {e['lock']} | {e['allowed']} |")
    lines+=['','## Completed RSI/EMA lock exceptions','','| Time | Direction | Lock | RSI9 | EMA3 of RSI | Allowed |','|---|---|---|---:|---:|---|']
    for e in events:
        if e['event']=='WMA_LOCK_EXCEPTION_CHECK':lines.append(f"| {e['time'][11:16]} | {e['direction']} | {e['lock']} | {e['rsi9']:.3f} | {e['ema3_rsi']:.3f} | {e['allowed']} |")
    lines+=['','## EMA10 exit checks','','| Time | Direction | Close | EMA10 | Action |','|---|---|---:|---:|---|']
    for e in events:
        if e['event']=='EMA_EXIT_CHECK':lines.append(f"| {e['time'][11:16]} | {e['direction']} | {e['close']:.2f} | {e['ema10']:.3f} | {'EXIT' if e['ema_pass'] else 'HOLD'} |")
        elif e['event']=='EMA_EXIT_CUTOFF_OVERRIDE':lines.append(f"| {e['time'][11:16]} | {e['direction']} | {e['price']:.2f} | — | CUTOFF EXIT |")
    text='\n'.join(lines)+'\n';(output/'summary.md').write_text(text);print(text);print('REPORT:',output/'report.json')

if __name__=='__main__':main()
