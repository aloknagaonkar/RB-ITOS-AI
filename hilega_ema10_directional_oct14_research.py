"""14 October only: retained 5m policies with corrected directional price EMA10 exits.

Standalone research runner. Does not modify imported modules or live files.
"""
import argparse
import hashlib
import importlib
import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest

DAY = '2026-10-14'
VERSION = 'DIRECTIONAL_PRICE_EMA10_EXIT_V2'
KEYS = ('ORIGINAL_CURRENT_1M', 'RETAINED_5M_NO_PERSISTENCE',
        'RETAINED_5M_PLUS_EMA10_EXIT', 'RETAINED_5M_EMA10_WMA_LOCK',
        'RETAINED_5M_EMA10_WMA_EXCEPTION')
LABELS = ('Existing strategy', 'Retained 5m, no persistence', '+ corrected EMA10 exit',
          '+ WMA lock', '+ RSI/EMA exceptions')

def permits_exit(side, close, ema):
    if side not in ('BULLISH', 'BEARISH'): raise ValueError('INVALID_POSITION_DIRECTION')
    if any(isinstance(v, bool) or not math.isfinite(float(v)) or float(v) <= 0 for v in (close, ema)):
        raise ValueError('INVALID_PRICE_EMA')
    return close < ema if side == 'BULLISH' else close > ema

def directional_exit_gate(Base, frames):
    class DirectionalExit(Base):
        def close(self, event, at, price):
            if event.exit_reason == 'SESSION_CUTOFF_1455':
                self.policy_events.append(dict(event='EMA_EXIT_CUTOFF_OVERRIDE', time=at.isoformat(), direction=self.owner, price=price))
                return super().close(event, at, price)
            frame = frames.get(at)
            if frame is None: raise ValueError('EXACT_COMPLETED_EMA_FRAME_REQUIRED:' + at.isoformat())
            if abs(float(price)-frame['close']) > 1e-5: raise ValueError('EXIT_CLOSE_MISMATCH')
            allowed = permits_exit(self.owner, frame['close'], frame['ema10'])
            self.policy_events.append(dict(event='EMA_EXIT_CHECK', time=at.isoformat(), direction=self.owner,
                existing_exit_pass=True, close=frame['close'], ema10=frame['ema10'], ema_pass=allowed,
                rule=VERSION, candle_label=frame['candle_label']))
            if allowed: return super().close(event, at, price)
            return None
    return DirectionalExit

class Checks(unittest.TestCase):
    def harness(self, side='BULLISH', close=99):
        at=datetime.fromisoformat('2026-10-14T12:40:00+05:30')
        class Base:
            def __init__(self): self.owner=side; self.active=True; self.policy_events=[]
            def close(self,event,at,price): self.owner='NONE'; self.active=None; return event
        gate=directional_exit_gate(Base,{at:dict(close=close,ema10=100,candle_label='12:35')})()
        return gate,at,SimpleNamespace(exit_reason='BOTH_RSI9_EMA3_OPPOSITE_WMA21')
    def test_bull_below_exits(self):
        g,t,e=self.harness(); self.assertIs(g.close(e,t,99),e)
    def test_bull_above_holds(self):
        g,t,e=self.harness(close=101); self.assertIsNone(g.close(e,t,101)); self.assertTrue(g.active)
    def test_bear_above_exits(self):
        g,t,e=self.harness('BEARISH',101); self.assertIs(g.close(e,t,101),e)
    def test_bear_below_holds(self):
        g,t,e=self.harness('BEARISH',99); self.assertIsNone(g.close(e,t,99))
    def test_equality_holds_both(self):
        for side in ('BULLISH','BEARISH'): self.assertFalse(permits_exit(side,100,100))
    def test_cutoff_bypasses_validation(self):
        g,t,e=self.harness(close=101); e.exit_reason='SESSION_CUTOFF_1455'
        self.assertIs(g.close(e,t+timedelta(minutes=5),101),e)
    def test_future_frame_cannot_authorize(self):
        g,t,e=self.harness()
        with self.assertRaises(ValueError): g.close(e,t-timedelta(minutes=5),99)
    def test_mismatched_close_rejected(self):
        g,t,e=self.harness()
        with self.assertRaises(ValueError): g.close(e,t,98)
    def test_invalid_values_rejected(self):
        for value in (float('nan'),float('inf'),0,True):
            with self.assertRaises(ValueError): permits_exit('BULLISH',value,100)
    def test_hold_does_not_latch_permission(self):
        g,t,e=self.harness(close=101); self.assertIsNone(g.close(e,t,101))
        self.assertEqual(g.owner,'BULLISH'); self.assertEqual(g.policy_events[-1]['existing_exit_pass'],True)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--test',action='store_true')
    ap.add_argument('--policy-module',default='hilega_retained_pending_day_research1')
    ap.add_argument('--stack-module')
    ap.add_argument('--research-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    ap.add_argument('--previous-root',type=Path,default=Path('data/research/hilega-retained-policy-last10-20261016'))
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-directional-ema10-20261014-v2'))
    args=ap.parse_args()
    if args.test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    import hilega_pending_confirmation_research as p
    import hilega_pending_previous10_research as stats
    import hilega_retained_policy_batch_research as batch
    import hilega_ema10_exit_day_research as ema
    import hilega_post_entry_wma_lock_today_research as lock
    import hilega_vwap_confirmed36_research as support
    from hilega_vwap_wait_alignment_research import source_data
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    retained=importlib.import_module(args.policy_module); stack=batch.load_stack(args.stack_module)
    if engine.RULES['version']!=p.VERSION: raise ValueError('ENGINE_VERSION_MISMATCH')
    parent=json.loads((args.research_root/'3-month/report.json').read_text())
    if parent['strategy_version']!=p.VERSION: raise ValueError('SOURCE_VERSION_MISMATCH')
    sessions,grouped=source_data(args.research_root,parent,support)
    asof=p.dt(DAY+'T14:55:00+05:30')
    raw=[r for r in grouped[DAY] if p.dt(r['timestamp'])<=asof]
    warm=[(d,grouped[d]) for d in sessions if d<DAY and grouped.get(d)][-30:]
    if len(warm)<20: raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
    prior=json.loads((args.previous_root/'report.json').read_text())
    if prior['status']!='COMPLETE' or prior['strategy_version']!=p.VERSION: raise ValueError('PREVIOUS_COMPLETE_REPORT_REQUIRED')
    digest=hashlib.sha256(json.dumps([raw,warm],sort_keys=True,default=str).encode()).hexdigest()
    if digest!=prior['provenance'][DAY]['raw_and_warm_sha256']: raise ValueError('PREVIOUS_INPUT_HASH_MISMATCH')
    original=p.simulate(engine,DAY,raw,warm,asof,'CURRENT')
    saved=json.loads((args.research_root/'replays'/(DAY+'.json')).read_text())
    if saved['session_date']!=DAY or saved['strategy_version']!=p.VERSION: raise ValueError('BASELINE_IDENTITY_MISMATCH')
    parity=stats.frozen_parity(saved,original)
    if parity['status']!='PASS': raise ValueError('BASELINE_PARITY_FAILED:'+json.dumps(parity))
    Base=retained.retained_gate(p.changed_gate(retained.five_gate_no_persistence(engine.WmaGapGate)),engine.direction)
    replay=retained.retained_replay(engine)
    frames=ema.ema_frames(engine,DAY,raw,warm,p.dt); wm=lock.completed_frames(original,p.dt)
    indicators={p.dt(r['checkpoint']):r['completed_5m_indicators'] for r in original['audit']
        if r.get('nifty_close') is not None and r.get('completed_5m_indicators') and p.dt(r['checkpoint']).minute%5==0}
    Ema=directional_exit_gate(Base,frames)
    gates=(Base,Ema,stack.retaining_lock_gate(Ema,engine.direction,wm,lock),
           stack.exception_lock_gate(Ema,engine.direction,wm,indicators,lock))
    results={KEYS[0]:original}
    for key,Gate in zip(KEYS[1:],gates):
        results[key]=p.simulate(SimpleNamespace(WmaGapGate=Gate,replay=replay),DAY,raw,warm,asof,'CURRENT')
        if any(p.dt(t['entry_time']).minute%5 for t in results[key]['trades']): raise ValueError('OFF_BOUNDARY_ENTRY')
    old={key:json.loads((args.previous_root/'sessions'/DAY/(key+'.json')).read_text()) for key in KEYS}
    for key in KEYS:
        stats.signature(results[key]['trades'])
        if key in KEYS[:2] and stats.frozen_parity(old[key],results[key])['status']!='PASS':
            raise ValueError('UNCHANGED_POLICY_PARITY_FAILED:'+key)
    warning=('Research only; gross NIFTY points, no fills/costs or live changes. Same frozen inputs as the prior report. '
        'Retained 5m/no persistence entries. Original dual exit AND close<price EMA10 for bullish, '
        'close>price EMA10 for bearish, on the same completed 5m boundary. Equality holds; no exit latch. '
        '14:55 cutoff overrides EMA. WMA locks retain vetoed candidates. Exceptions use RSI9 AND EMA3 of RSI '
        '>45 under bearish lock, <55 under bullish lock. This is the retained comparison, not the fresh-5m policy.')
    lines=['# Corrected directional EMA10 — '+DAY,'',warning,'','Baseline and unchanged-policy parity: PASS','',
        '| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    comparisons={key:stats.stats(results[key]['trades']) for key in KEYS}
    for key,label in zip(KEYS,LABELS):
        s=comparisons[key]; lines.append(f"| {label} | {s['trades']} | {s['points']:+.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','## Signal comparison','','A dash means no executed entry from that exact setup; it is not proof of a direct rejection. Times IST.','',
        '| Direction | Setup available | '+' | '.join(LABELS)+' |','|---|---|'+'---|'*5]
    identities=sorted({(t['direction'],t['signal_time']) for r in results.values() for t in r['trades']},key=lambda x:(x[1],x[0]))
    for side,signal in identities:
        cells=[]
        for key in KEYS:
            trades=[t for t in results[key]['trades'] if (t['direction'],t['signal_time'])==(side,signal)]
            cells.append('; '.join(batch.trade_cell(t) for t in trades) or '—')
        lines.append('| '+side+' | '+signal[11:16]+' | '+' | '.join(cells)+' |')
    lines+=['','## Old versus corrected EMA10','','| Policy | Old points | Corrected points | Change |','|---|---:|---:|---:|']
    for key,label in zip(KEYS,LABELS):
        before=stats.stats(old[key]['trades'])['points']; after=comparisons[key]['points']
        lines.append(f'| {label} | {before:+.2f} | {after:+.2f} | {after-before:+.2f} |')
    lines+=['','## Exit validation','','| Policy | Decision | Direction | Close | Price EMA10 | Action |','|---|---|---|---:|---:|---|']
    for key,label in zip(KEYS[2:],LABELS[2:]):
        for e in results[key]['policy_events']:
            if e['event']=='EMA_EXIT_CHECK': lines.append(f"| {label} | {e['time'][11:16]} | {e['direction']} | {e['close']:.2f} | {e['ema10']:.3f} | {'EXIT' if e['ema_pass'] else 'HOLD'} |")
            elif e['event']=='EMA_EXIT_CUTOFF_OVERRIDE': lines.append(f"| {label} | {e['time'][11:16]} | {e['direction']} | {e['price']:.2f} | — | CUTOFF EXIT |")
    report=dict(status='COMPLETE',session_date=DAY,exit_policy_version=VERSION,baseline_parity=parity,
        unchanged_policy_parity='PASS',input_sha256=digest,comparisons=comparisons,results=results,
        ema_frames={t.isoformat():v for t,v in frames.items()},warning=warning,orders_sent=False,observation_only=True)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    text='\n'.join(lines)+'\n'; (args.output/'summary.md').write_text(text)
    print(text); print('REPORT:',args.output/'report.json')

if __name__=='__main__': main()
