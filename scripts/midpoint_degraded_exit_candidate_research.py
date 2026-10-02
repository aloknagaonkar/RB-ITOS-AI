#!/usr/bin/env python3
"""Materialize read-only B/E degraded-exit research beside the live audit.

PYTHONPATH=backend python scripts/midpoint_degraded_exit_candidate_research.py \
  --session-date 2026-09-29
"""
from __future__ import annotations
import argparse,csv,json
from datetime import date
from pathlib import Path

from market_lab.midpoint_strategy.degraded_exit_candidate import project, summarize
from market_lab.midpoint_strategy.replay import load_audit_jsonl

ROOT=Path('data/live-observation/midpoint-strategy-v1')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-date',required=True,type=date.fromisoformat)
    parser.add_argument('--quotes-csv',type=Path,help='Optional exact timestamp,instrument_key,bid,ask rows')
    parser.add_argument('--entry-slippage-points',type=float,default=0.0)
    parser.add_argument('--exit-slippage-points',type=float,default=0.0)
    parser.add_argument('--round-trip-charges-points',type=float,default=0.0)
    args=parser.parse_args()
    day=args.session_date.isoformat()
    tape_path=ROOT/'option-observation'/f'{day}.json'
    if not tape_path.is_file():raise SystemExit(f'STOP exact five-contract option tape unavailable: {tape_path}')
    rows=[r for r in load_audit_jsonl(ROOT/'audit.jsonl') if r.get('session_date')==day]
    if not rows:raise SystemExit('STOP no audit for session')
    if any(r.get('observation_only') is not True or r.get('execution_enabled') is not False
           or r.get('paper_order_enabled') is not False or r.get('quantity') is not None for r in rows):
        raise SystemExit('STOP audit safety mismatch')
    quotes=None
    if args.quotes_csv:
        with args.quotes_csv.open(newline='') as fh:quotes=list(csv.DictReader(fh))
    tapes=json.loads(tape_path.read_text())['tapes']
    results=[project(rows,tape,quotes=quotes,
                     entry_slippage_points=args.entry_slippage_points,
                     exit_slippage_points=args.exit_slippage_points,
                     round_trip_charges_points=args.round_trip_charges_points) for tape in tapes]
    payload={'model':'MIDPOINT_DEGRADED_EXIT_RESEARCH_SESSION_V1','session_date':day,
             'observation_only':True,'execution_enabled':False,'paper_order_enabled':False,
             'quantity':None,'summary':summarize(results),'trades':results}
    out=ROOT/'research'/f'degraded-exit-candidate-{day}.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(payload,indent=2,sort_keys=True))
    tmp.replace(out)
    print('Saved',len(results),'trade projection(s):',out)
    for r in results:
        print(r['family'],r['direction'],'canonical',r['canonical_gate']['status'],
              'signal',r['degraded_signal_timestamp'],'exact exit',r['DEGRADED_EXIT_TIMESTAMP'])
        print('premiums:',r['DEGRADED_PREMIUMS'])
        print('premium/entry+10 qualified legs:',sum(x['tracks']['PREMIUM_PLUS20_ENTRY_T10']['qualified'] for x in r['legs']))
        print('delta underlying vs CAP20/terminal:',r['legs'][0]['COMP_CAP20_TERMINAL']['delta_vs_cap20_or_terminal_points'])
    print('No orders, execution, paper orders, or quantity. OHLC OPEN is not a bid fill.')

if __name__=='__main__':main()
