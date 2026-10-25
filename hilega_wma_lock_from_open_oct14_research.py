"""Research only: Oct14 WMA lock can activate while flat, from first completed 5m.
Keeps rising/falling activation, corrected directional EMA10 and retained entries.
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

def open_lock_class(Parent):
    class OpenLock(Parent):
        def observe(self,at,wma,previous,active):
            release=((self.side=='BULLISH' and previous is not None and previous>=55 and wma<55)
                or (self.side=='BEARISH' and previous is not None and previous<=45 and wma>45))
            eligible='NONE'
            if not release and previous is not None:
                if wma>55 and wma>previous: eligible='BULLISH'
                elif wma<45 and wma<previous: eligible='BEARISH'
            before=len(self.events)
            super().observe(at,wma,previous,eligible)
            for event in self.events[before:]:
                event['active_direction']=active
                event['activation_basis']='COMPLETED_WMA_INDEPENDENT_OF_POSITION'
                event['reason']=event['reason'].replace('ACTIVE_BULLISH','FROM_OPEN_BULLISH').replace('ACTIVE_BEARISH','FROM_OPEN_BEARISH')
    return OpenLock

def lock_adapter(lock):
    Open=open_lock_class(lock.DirectionLock)
    def gate(Base,direction,frames):
        Parent=lock.lock_gate(Base,direction,frames)
        class OpenGate(Parent):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs); self.direction_lock=Open()
        return OpenGate
    return SimpleNamespace(lock_gate=gate)

class Checks(unittest.TestCase):
    def setUp(self):
        from datetime import datetime
        import hilega_post_entry_wma_lock_today_research as lock
        self.Open=open_lock_class(lock.DirectionLock)
        self.at=datetime.fromisoformat('2026-10-14T09:20:00+05:30')
    def test_flat_rising_above55_blocks_bear(self):
        g=self.Open();g.observe(self.at,60,59,'NONE');self.assertFalse(g.permits('BEARISH'))
    def test_flat_falling_below45_blocks_bull(self):
        g=self.Open();g.observe(self.at,40,41,'NONE');self.assertFalse(g.permits('BULLISH'))
    def test_high_but_falling_does_not_lock(self):
        g=self.Open();g.observe(self.at,80,82,'NONE');self.assertEqual(g.side,'NONE')
    def test_low_but_rising_does_not_lock(self):
        g=self.Open();g.observe(self.at,40,39,'NONE');self.assertEqual(g.side,'NONE')
    def test_middle_starts_none(self):
        g=self.Open();g.observe(self.at,50,49,'NONE');self.assertEqual(g.side,'NONE')
    def test_release_does_not_automatically_flip(self):
        g=self.Open();g.side='BULLISH';g.observe(self.at,40,60,'NONE');self.assertEqual(g.side,'NONE')
    def test_equality_no_activation(self):
        for current,previous in ((55,54),(45,46),(60,60)):
            g=self.Open();g.observe(self.at,current,previous,'NONE');self.assertEqual(g.side,'NONE')
    def test_repeated_boundary_idempotent(self):
        g=self.Open();g.observe(self.at,60,59,'NONE');g.observe(self.at,60,59,'NONE');self.assertEqual(len(g.events),1)

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--test',action='store_true')
    ap.add_argument('--policy-module',default='hilega_retained_pending_day_research1');ap.add_argument('--stack-module')
    ap.add_argument('--research-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    ap.add_argument('--previous-report',type=Path,default=Path('data/research/hilega-directional-ema10-20261014-v2/report.json'))
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-wma-lock-from-open-20261014'))
    a=ap.parse_args()
    import hilega_ema10_directional_oct14_research as corrected
    if a.test:
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (Checks,corrected.Checks))
        r=unittest.TextTestRunner(verbosity=2).run(suite);raise SystemExit(0 if r.wasSuccessful() else 1)
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    import hilega_pending_confirmation_research as p
    import hilega_pending_previous10_research as stats
    import hilega_retained_policy_batch_research as batch
    import hilega_post_entry_wma_lock_today_research as lock
    import hilega_ema10_exit_day_research as ema
    import hilega_vwap_confirmed36_research as support
    from hilega_vwap_wait_alignment_research import source_data
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    day=corrected.DAY;prior=json.loads(a.previous_report.read_text())
    if prior['status']!='COMPLETE' or prior['session_date']!=day or prior['exit_policy_version']!=corrected.VERSION:
        raise ValueError('CORRECTED_OCT14_REPORT_REQUIRED')
    if engine.RULES['version']!=p.VERSION:raise ValueError('ENGINE_VERSION_MISMATCH')
    parent=json.loads((a.research_root/'3-month/report.json').read_text())
    if parent['strategy_version']!=p.VERSION:raise ValueError('SOURCE_VERSION_MISMATCH')
    sessions,grouped=source_data(a.research_root,parent,support);asof=p.dt(day+'T14:55:00+05:30')
    raw=[r for r in grouped[day] if p.dt(r['timestamp'])<=asof]
    warm=[(d,grouped[d]) for d in sessions if d<day and grouped.get(d)][-30:]
    if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
    digest=hashlib.sha256(json.dumps([raw,warm],sort_keys=True,default=str).encode()).hexdigest()
    if digest!=prior['input_sha256']:raise ValueError('INPUT_HASH_MISMATCH')
    original=p.simulate(engine,day,raw,warm,asof,'CURRENT')
    if stats.frozen_parity(prior['results'][corrected.KEYS[0]],original)['status']!='PASS':raise ValueError('BASELINE_PARITY_FAILED')
    wm=lock.completed_frames(original,p.dt)
    first=min(wm);audit=next(r for r in original['audit'] if p.dt(r['checkpoint'])==first and r.get('completed_5m_indicators'))
    delta=audit['five_minute_changes']['wma21']
    if delta is None:raise ValueError('OPENING_PRIOR_COMPLETED_WMA_REQUIRED')
    wm[first]['previous_wma21']=wm[first]['wma21']-delta
    retained=importlib.import_module(a.policy_module);stack=batch.load_stack(a.stack_module)
    Base=retained.retained_gate(p.changed_gate(retained.five_gate_no_persistence(engine.WmaGapGate)),engine.direction)
    replay=retained.retained_replay(engine);frames=ema.ema_frames(engine,day,raw,warm,p.dt)
    Ema=corrected.directional_exit_gate(Base,frames)
    indicators={p.dt(r['checkpoint']):r['completed_5m_indicators'] for r in original['audit']
        if r.get('nifty_close') is not None and r.get('completed_5m_indicators') and p.dt(r['checkpoint']).minute%5==0}
    adapter=lock_adapter(lock)
    specs=[('FROM_OPEN_WMA_LOCK',stack.retaining_lock_gate(Ema,engine.direction,wm,adapter)),
           ('FROM_OPEN_WMA_EXCEPTION',stack.exception_lock_gate(Ema,engine.direction,wm,indicators,adapter))]
    results={k:prior['results'][k] for k in corrected.KEYS}
    for key,Gate in specs:
        results[key]=p.simulate(SimpleNamespace(WmaGapGate=Gate,replay=replay),day,raw,warm,asof,'CURRENT')
        stats.signature(results[key]['trades'])
    labels=list(corrected.LABELS)+['Lock from open','Lock from open + exceptions'];keys=list(corrected.KEYS)+[s[0] for s in specs]
    warning=('Research only; gross NIFTY points, no fills/costs/live changes. Retained 5m/no persistence; corrected directional price EMA10 exits. '
        'New lock can activate while flat: WMA>55 AND rising, or WMA<45 AND falling. '
        'Opening slope uses the saved prior completed-session WMA reference, not future data. '
        'Above55 but falling does NOT initially lock. Middle starts NONE. Strict reverse threshold cross releases to NONE; '
        'no opposite lock on that same release boundary. Same cutoff, entries and exceptions as corrected Oct14 study.')
    comparisons={k:stats.stats(results[k]['trades']) for k in keys}
    lines=['# Lock from market open — '+day,'',warning,'','Input hash and original baseline parity: PASS','',
        '| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for key,label in zip(keys,labels):
        s=comparisons[key];lines.append(f"| {label} | {s['trades']} | {s['points']:+.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','## Signal comparison','','Dash means no entry from that exact setup, not necessarily a direct veto. Times IST.','',
        '| Direction | Setup available | '+' | '.join(labels)+' |','|---|---|'+'---|'*len(keys)]
    identities=sorted({(t['direction'],t['signal_time']) for r in results.values() for t in r['trades']},key=lambda x:(x[1],x[0]))
    for side,signal in identities:
        cells=['; '.join(batch.trade_cell(t) for t in results[k]['trades'] if (t['direction'],t['signal_time'])==(side,signal)) or '—' for k in keys]
        lines.append('| '+side+' | '+signal[11:16]+' | '+' | '.join(cells)+' |')
    lines+=['','## From-open lock path (same path for both new policies)','','| Decision | Previous WMA | WMA | Slope | Before | After | Reason |','|---|---:|---:|---:|---|---|---|']
    monitor=open_lock_class(lock.DirectionLock)()
    for at,f in sorted(wm.items()):
        before=monitor.side;n=len(monitor.events);monitor.observe(at,f['wma21'],f['previous_wma21'],'NONE')
        reason=monitor.events[-1]['reason'] if len(monitor.events)>n else 'UNCHANGED'
        lines.append(f"| {at.strftime('%H:%M')} | {f['previous_wma21']:.3f} | {f['wma21']:.3f} | {f['wma21']-f['previous_wma21']:+.3f} | {before} | {monitor.side} | {reason} |")
    lines+=['','## Actual entry lock checks','','| Policy | Time | Direction | Lock | Allowed |','|---|---|---|---|---|']
    for key,_ in specs:
        for e in results[key]['policy_events']:
            if e['event']=='CONFIRMED_ENTRY_LOCK_CHECK':lines.append(f"| {key} | {e['time'][11:16]} | {e['direction']} | {e['lock']} | {e['allowed']} |")
    a.output.mkdir(parents=True,exist_ok=True)
    report=dict(status='COMPLETE',session_date=day,lock_policy='FROM_OPEN_POSITION_INDEPENDENT_SLOPE_REQUIRED_V1',
        input_sha256=digest,comparisons=comparisons,results=results,warning=warning,orders_sent=False,observation_only=True)
    (a.output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);print(text);print('REPORT:',a.output/'report.json')

if __name__=='__main__':main()
