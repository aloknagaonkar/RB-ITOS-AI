#!/usr/bin/env python3
"""Read-only multi-session B/E exit comparison using current coordinator replay.

Run from repository root with PYTHONPATH=backend. Historical option premiums
are reported only when an exact five-contract tape already exists on disk.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from market_lab.midpoint_strategy.degraded_exit_candidate import project

from midpoint_v57_full_historical_be_lifecycle_replay import (
    CANON, V52, V55, import_module, replay_session,
)

ROOT = Path('data/live-observation/midpoint-strategy-v1')


def dt(event):
    return datetime.fromisoformat(event['event_timestamp'])


def points(entry, exit_event):
    if exit_event is None:
        return None
    factor = 1 if entry['direction'] == 'BULLISH' else -1
    return factor * (float(exit_event['underlying_price']) - float(entry['underlying_price']))


def compare_events(events, block):
    """One result per entry. No option price is fabricated from index candles."""
    entries = [i for i, e in enumerate(events) if e.get('event_type') in ('B_ENTRY', 'E_ENTRY')]
    out = []
    for sequence, start in enumerate(entries):
        end = entries[sequence + 1] if sequence + 1 < len(entries) else len(events)
        segment = events[start:end]
        entry = segment[0]
        def first(kind):
            return next((e for e in segment if e.get('event_type') == kind), None)
        proof = first('PLUS20_PROOF')
        classifier = first('RUNNER_CLASSIFICATION')
        degraded = first('DEGRADED_STARTED')
        exits = [e for e in segment if e.get('event_type') in ('CAP20_RESCUE_TRIGGERED', 'STRUCTURAL_TERMINAL')]
        baseline = min(exits, key=dt) if exits else None
        qualifies = bool(proof and classifier and degraded and
                         classifier.get('result') == 'RUNNER_STRENGTHENING' and
                         dt(classifier) == dt(proof) + timedelta(minutes=10) and
                         dt(degraded) > dt(classifier) and
                         (baseline is None or dt(degraded) <= dt(baseline)))
        base_points = points(entry, baseline)
        candidate = degraded if qualifies else baseline
        candidate_points = points(entry, candidate)
        out.append({
            'block':block, 'session_date':entry['session_date'],
            'entry_event_id':entry['event_id'], 'entry_timestamp':entry['event_timestamp'],
            'family':entry['family'], 'direction':entry['direction'],
            'qualified':qualifies, 'proof_timestamp':proof['event_timestamp'] if proof else None,
            'classifier_timestamp':classifier['event_timestamp'] if classifier else None,
            'degraded_timestamp':degraded['event_timestamp'] if degraded else None,
            'baseline_type':baseline['event_type'] if baseline else None,
            'baseline_timestamp':baseline['event_timestamp'] if baseline else None,
            'candidate_timestamp':candidate['event_timestamp'] if candidate else None,
            'baseline_nifty_points':base_points, 'candidate_nifty_points':candidate_points,
            'delta_nifty_points':candidate_points-base_points if candidate_points is not None and base_points is not None else None,
            'option_status':'EXACT_FIVE_CONTRACT_TAPE_UNAVAILABLE',
            'option_projection':None,
        })
    return out


def summarize(rows):
    summary = {}
    for family in ('B', 'E', 'B+E'):
        selected = [r for r in rows if family == 'B+E' or r['family'] == family]
        complete = [r for r in selected if r['baseline_nifty_points'] is not None]
        deltas = [r['delta_nifty_points'] for r in complete]
        qualified = [r for r in complete if r['qualified']]
        summary[family] = {
            'entries':len(selected), 'completed':len(complete),
            'unresolved':len(selected)-len(complete), 'changed_exits':len(qualified),
            'baseline_mean_nifty_points':sum(r['baseline_nifty_points'] for r in complete)/len(complete) if complete else None,
            'candidate_mean_nifty_points':sum(r['candidate_nifty_points'] for r in complete)/len(complete) if complete else None,
            'mean_nifty_point_impact':sum(deltas)/len(complete) if complete else None,
            'improved':sum(r['delta_nifty_points'] > 0 for r in qualified),
            'harmed':sum(r['delta_nifty_points'] < 0 for r in qualified),
            'five_leg_option_complete':sum(r['option_status'] == 'AVAILABLE' for r in selected),
        }
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', help='First session YYYY-MM-DD (inclusive)')
    parser.add_argument('--end', help='Last session YYYY-MM-DD (inclusive)')
    parser.add_argument('--output', type=Path, default=Path('data/historical-evidence/midpoint-degraded-exit-multiday.json'))
    args=parser.parse_args()
    v55=import_module(V55,'v55_candidate_multiday')
    v52=import_module(V52,'v52_candidate_multiday')
    canon=import_module(CANON,'canon_candidate_multiday')
    results=[]
    sessions=0
    for block in v52.BLOCKS:
        underlying, futures, _=v55.load_block(block,v52,canon)
        for day in sorted(set(underlying).intersection(futures)):
            if (args.start and day < args.start) or (args.end and day > args.end):
                continue
            sessions += 1
            events, _, _=replay_session(day,underlying[day],futures[day])
            trades=compare_events(events,block['name'])
            tape_path=ROOT/'option-observation'/f'{day}.json'
            if tape_path.is_file():
                tapes=json.loads(tape_path.read_text()).get('tapes',[])
                by_id={t['entry_event_id']:t for t in tapes}
                for row in trades:
                    tape=by_id.get(row['entry_event_id'])
                    if tape is not None:
                        projection=project(events,tape)
                        row['option_projection']=projection
                        row['option_status']='AVAILABLE' if all(
                            leg['tracks']['CANONICAL_UNDERLYING_PLUS20_PROOF_T10']['status']=='AVAILABLE'
                            for leg in projection['legs']) else 'EXACT_OPTION_MINUTE_UNAVAILABLE'
            results.extend(trades)
    payload={'model':'MIDPOINT_DEGRADED_EXIT_MULTIDAY_RESEARCH_V1',
             'observation_only':True,'execution_enabled':False,
             'paper_order_enabled':False,'quantity':None,
             'sessions':sessions,'summary':summarize(results),'trades':results}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temporary=args.output.with_suffix(args.output.suffix+'.tmp')
    temporary.write_text(json.dumps(payload,indent=2))
    temporary.replace(args.output)
    print('Sessions:',sessions,'entries:',len(results),'output:',args.output)
    for family, value in payload['summary'].items():
        print(family,value)
    print('Underlying replay comparison; exact option fills, spreads and charges unavailable unless sourced separately.')

if __name__=='__main__':main()
