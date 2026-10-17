"""Offline research: existing dual exit AND NIFTY close above price EMA10.

Uses retained 5m entry confirmation without persistence. Applies ABOVE EMA10
literally to BOTH directions. Exit checks use completed 5m prices only; no latch:
both original exit and EMA condition must pass on the same decision boundary.
14:55 cutoff always overrides EMA. No API/orders/live changes.
"""
import argparse
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from datetime import timedelta

def ema_step(previous,close):
    if isinstance(close,bool) or not math.isfinite(float(close)) or float(close)<=0:raise ValueError('INVALID_CLOSE')
    return float(close) if previous is None else previous+(2/11)*(float(close)-previous)

def ema_frames(engine,day,raw,warm,dt):
    value=None;frames={};count=0
    for session,rows in list(warm)+[(day,raw)]:
        bars=engine.aggregate_exact_5m(engine.candles(rows),dt(session+'T00:00:00+05:30').date(),require_full_session=False)
        for bar in bars:
            available=bar.ts+timedelta(minutes=5)
            if session==day and available.strftime('%H:%M')>'14:55':continue
            value=ema_step(value,float(bar.close));count+=1
            if session==day:
                frames[available]=dict(ema10=value,close=float(bar.close),candle_label=bar.ts.isoformat(),available_at=available.isoformat(),seeded_bar_count=count)
    return frames

def exit_gate(Base,frames):
    class ExitValidated(Base):
        def close(self,event,at,price):
            if event.exit_reason=='SESSION_CUTOFF_1455':
                self.policy_events.append(dict(event='EMA_EXIT_CUTOFF_OVERRIDE',time=at.isoformat(),direction=self.owner,price=price))
                return super().close(event,at,price)
            frame=frames.get(at)
            if frame is None:raise ValueError('COMPLETED_PRICE_EMA_FRAME_REQUIRED:'+at.isoformat())
            if abs(float(price)-frame['close'])>1e-5:raise ValueError('EXIT_PRICE_COMPLETED_CLOSE_MISMATCH')
            allowed=frame['close']>frame['ema10']
            self.policy_events.append(dict(event='EMA_EXIT_CHECK',time=at.isoformat(),direction=self.owner,
                existing_exit_pass=True,close=frame['close'],ema10=frame['ema10'],ema_pass=allowed,
                comparison='CLOSE_STRICTLY_ABOVE_EMA10_FOR_BOTH_DIRECTIONS',candle_label=frame['candle_label']))
            if not allowed:return None
            return super().close(event,at,price)
    return ExitValidated

class Checks(unittest.TestCase):
    def harness(self,close,ema,side='BULLISH'):
        from datetime import datetime
        at=datetime.fromisoformat('2026-08-26T11:00:00+05:30')
        class Base:
            def __init__(self):self.owner=side;self.active=True;self.policy_events=[]
            def close(self,event,at,price):self.owner='NONE';self.active=None;return event
        g=exit_gate(Base,{at:dict(close=close,ema10=ema,candle_label='10:55')})()
        return g,at,SimpleNamespace(exit_reason='BOTH_RSI9_EMA3_OPPOSITE_WMA21')
    def test_above_allows_existing_exit(self):
        g,at,event=self.harness(101,100);self.assertIs(g.close(event,at,101),event)
    def test_below_defers_exit(self):
        g,at,event=self.harness(99,100);self.assertIsNone(g.close(event,at,99));self.assertEqual(g.owner,'BULLISH')
    def test_equality_defers(self):
        g,at,event=self.harness(100,100);self.assertIsNone(g.close(event,at,100))
    def test_bearish_uses_literal_above_rule(self):
        g,at,event=self.harness(101,100,'BEARISH');self.assertIs(g.close(event,at,101),event)
    def test_cutoff_overrides_below_ema(self):
        g,at,event=self.harness(99,100);event.exit_reason='SESSION_CUTOFF_1455'
        self.assertIs(g.close(event,at+timedelta(hours=1),99),event)
    def test_future_frame_not_used(self):
        g,at,event=self.harness(101,100)
        with self.assertRaises(ValueError):g.close(event,at-timedelta(minutes=5),101)
    def test_ema_seed_and_alpha(self):
        self.assertEqual(ema_step(None,100),100);self.assertAlmostEqual(ema_step(100,111),102)
    def test_invalid_price_rejected(self):
        with self.assertRaises(ValueError):ema_step(100,float('nan'))

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--date',default='2026-08-26')
    ap.add_argument('--policy-module',help='Updated retained policy module, e.g. hilega_retained_pending_day_research1')
    ap.add_argument('--research-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    ap.add_argument('--output',type=Path);ap.add_argument('--test',action='store_true');a=ap.parse_args()
    if a.test:
        r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks));raise SystemExit(0 if r.wasSuccessful() else 1)
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    names=[a.policy_module] if a.policy_module else ['hilega_retained_pending_day_research1','hilega_retained_pending_day_research']
    retained=None
    for name in names:
        if not Path(name+'.py').exists():continue
        module=importlib.import_module(name)
        if hasattr(module,'five_gate_no_persistence'):retained=module;break
    if retained is None:raise ValueError('UPDATED_RETAINED_POLICY_WITH_NO_PERSISTENCE_REQUIRED')
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
    if parity['status']!='PASS':raise ValueError('BASELINE_PARITY_NOT_PASS:'+json.dumps(parity))
    Gate=retained.retained_gate(p.changed_gate(retained.five_gate_no_persistence(engine.WmaGapGate)),engine.direction)
    replay=retained.retained_replay(engine);frames=ema_frames(engine,a.date,raw,warm,p.dt)
    baseline=p.simulate(SimpleNamespace(WmaGapGate=Gate,replay=replay),a.date,raw,warm,asof,'CURRENT')
    changed=p.simulate(SimpleNamespace(WmaGapGate=exit_gate(Gate,frames),replay=replay),a.date,raw,warm,asof,'CURRENT')
    # Verify the selected entry-policy baseline against the prior saved result.
    prior_path=Path('data/research/hilega-retained-pending-no-persistence-'+a.date.replace('-',''))/'report.json'
    if not prior_path.exists():raise ValueError('PREVIOUS_NO_PERSISTENCE_REPORT_REQUIRED:'+str(prior_path))
    prior=json.loads(prior_path.read_text())['results']['RETAINED_5M_NO_PERSISTENCE']
    retained_parity=batch.frozen_parity(prior,baseline)
    if retained_parity['status']!='PASS':raise ValueError('RETAINED_BASELINE_PARITY_NOT_PASS:'+json.dumps(retained_parity))
    results=dict(ORIGINAL_CURRENT_1M=original,RETAINED_5M_NO_PERSISTENCE=baseline,RETAINED_5M_PLUS_EMA10_EXIT=changed)
    for r in results.values():batch.signature(r['trades'])
    output=a.output or Path('data/research/hilega-ema10-exit-'+a.date.replace('-',''));output.mkdir(parents=True,exist_ok=True)
    warning='Gross NIFTY points, no option fills/costs. Frozen historical reconstruction. Price EMA10 uses alpha 2/11, first-close seed, continuous completed 5m closes over the same prior warmup sessions (minimum20, up to30). Literal close>EMA10 for both trade directions. No latch: both existing exit and EMA validation must pass together; cutoff bypasses EMA. Delayed exits can change subsequent entries. No live changes.'
    report=dict(status='COMPLETE',session_date=a.date,baseline_parity=parity,retained_baseline_parity=retained_parity,
        comparisons={k:batch.stats(r['trades']) for k,r in results.items()},results=results,
        ema_frames={at.isoformat():v for at,v in frames.items()},warning=warning,observation_only=True,orders_sent=False,
        policy_module=retained.__name__,policy_sha256=hashlib.sha256(Path(retained.__file__).read_bytes()).hexdigest(),
        input_sha256=hashlib.sha256(json.dumps([raw,warm],sort_keys=True,default=str).encode()).hexdigest())
    (output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    lines=['# EMA10 exit validation — '+a.date,'',warning,'','Original and retained baseline parity: PASS','',
        '| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for k,s in report['comparisons'].items():lines.append(f"| {k} | {s['trades']} | {s['points']:.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','| Policy | Direction | Setup | Entry | Exit | Points |','|---|---|---|---|---|---:|']
    for k,r in results.items():
        for t in r['trades']:lines.append(f"| {k} | {t['direction']} | {t['signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['points']:.2f} |")
    lines+=['','## Existing exit attempts and EMA validation','','| Decision | Direction | Close | Price EMA10 | Outcome |','|---|---|---:|---:|---|']
    for e in changed['policy_events']:
        if e['event']=='EMA_EXIT_CHECK':lines.append(f"| {e['time'][11:16]} | {e['direction']} | {e['close']:.2f} | {e['ema10']:.3f} | {'EXIT' if e['ema_pass'] else 'HOLD'} |")
        elif e['event']=='EMA_EXIT_CUTOFF_OVERRIDE':lines.append(f"| {e['time'][11:16]} | {e['direction']} | {e['price']:.2f} | — | CUTOFF EXIT |")
    text='\n'.join(lines)+'\n';(output/'summary.md').write_text(text);print(text);print('REPORT:',output/'report.json')

if __name__=='__main__':main()
