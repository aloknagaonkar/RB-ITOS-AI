"""Offline historical day comparison: existing 1m versus 5m confirmation.

No WMA45/55 lock, opposite-switch changes, continued windows or API calls.
Requires the existing five-minute research gate and frozen monthly cache.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--date',default='2026-08-26')
    ap.add_argument('--research-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    ap.add_argument('--output',type=Path)
    ap.add_argument('--test',action='store_true');a=ap.parse_args()
    import hilega_five_min_confirmation_research as five
    if a.test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(five.Checks))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
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
    if a.date not in sessions or a.date not in grouped:raise ValueError('SESSION_DATA_REQUIRED')
    warm=[(d,grouped[d]) for d in sessions if d<a.date and grouped.get(d)][-30:]
    if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
    raw=[r for r in grouped[a.date] if p.dt(r['timestamp'])<=asof]
    frozen_path=a.research_root/'replays'/(a.date+'.json');saved=json.loads(frozen_path.read_text())
    if saved['session_date']!=a.date or saved['strategy_version']!=p.VERSION:raise ValueError('BASELINE_IDENTITY_MISMATCH')
    baseline=p.simulate(engine,a.date,raw,warm,asof,'CURRENT')
    parity=batch.frozen_parity(saved,baseline)
    if parity['status']!='PASS':raise ValueError('BASELINE_PARITY_NOT_PASS:'+json.dumps(parity))
    proxy=SimpleNamespace(WmaGapGate=five.five_gate(engine.WmaGapGate,continued=False),replay=engine.replay)
    changed=p.simulate(proxy,a.date,raw,warm,asof,'CURRENT')
    for t in changed['trades']:
        if p.dt(t['entry_time']).minute%5:raise ValueError('OFF_BOUNDARY_ENTRY')
    results=dict(CURRENT_1M=baseline,CURRENT_5M=changed)
    for r in results.values():batch.signature(r['trades'])
    output=a.output or Path('data/research/hilega-current-five-minute-'+a.date.replace('-',''))
    output.mkdir(parents=True,exist_ok=True)
    summary={k:batch.stats(r['trades']) for k,r in results.items()}
    report=dict(status='COMPLETE',session_date=a.date,strategy_version=p.VERSION,baseline_parity=parity,
        comparisons=summary,results=results,observation_only=True,orders_sent=False,
        baseline_sha256=hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
        input_sha256=hashlib.sha256(json.dumps([raw,warm],sort_keys=True,default=str).encode()).hexdigest(),warmup_sessions=len(warm),
        gate_sha256=hashlib.sha256(Path(five.__file__).read_bytes()).hexdigest(),
        rules='Only entry confirmation cadence changes from 1m to completed 5m. Confirmation persistence and gap expansion compare consecutive 5m readings. Existing setup generation retains minute gap inputs. Strength threshold, ten-minute pending window, direction watch, canonical cancellation, dual exits and 14:55 cutoff retained. No WMA45/55 lock.',
        warning='Frozen historical reconstruction. Gross NIFTY points, not option P&L; no fills/costs. Baseline parity establishes reproduction of the saved research baseline, not historical live execution. No live changes.')
    (output/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    lines=['# Current strategy: 1m versus 5m confirmation — '+a.date,'',report['rules'],'',report['warning'],'','Baseline parity: PASS','',
        '| Policy | Trades | Points | Winners | Losers | Drawdown |','|---|---:|---:|---:|---:|---:|']
    for k,s in summary.items():lines.append(f"| {k} | {s['trades']} | {s['points']:.2f} | {s['winners']} | {s['losers']} | {s['max_closed_trade_drawdown_points']:.2f} |")
    lines+=['','## Trade details','','| Policy | Direction | Setup | Entry | Exit | Points |','|---|---|---|---|---|---:|']
    for k,r in results.items():
        for t in r['trades']:lines.append(f"| {k} | {t['direction']} | {t['signal_time'][11:16]} | {t['entry_time'][11:16]} | {t['exit_time'][11:16]} | {t['points']:.2f} |")
    lines+=['','## Five-minute confirmation audit','','| Decision | Direction | Status | Reasons | Strength | Gap expansion |','|---|---|---|---|---:|---|']
    for row in changed['audit']:
        for c in row.get('checks') or []:
            lines.append(f"| {c['decision_timestamp'][11:16]} | {c['direction']} | {c['status']} | {', '.join(c['reasons']) or 'ALL PASSED'} | {c.get('directional_wma_strength')} | {c.get('gap_expanding_pass')} |")
    text='\n'.join(lines)+'\n';(output/'summary.md').write_text(text)
    with (output/'trades.csv').open('w',newline='') as handle:
        fields=['policy','direction','signal_time','entry_time','entry_price','exit_time','exit_price','points','exit_reason']
        writer=csv.DictWriter(handle,fields,extrasaction='ignore');writer.writeheader()
        for k,r in results.items():
            for t in r['trades']:writer.writerow(dict(t,policy=k))
    print(text);print('REPORT:',output/'report.json')

if __name__=='__main__':main()
