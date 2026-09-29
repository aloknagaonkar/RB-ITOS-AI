#!/usr/bin/env python3
"""Read-only Sep 29 Midpoint exit forensic; exact option open after a close signal."""
import json
from datetime import datetime, timedelta
from pathlib import Path

DAY = '2026-09-29'
ROOT = Path('data/live-observation/midpoint-strategy-v1')
audit_path = ROOT / 'audit.jsonl'
tape_path = ROOT / 'option-observation' / f'{DAY}.json'
if not audit_path.exists() or not tape_path.exists():
    raise SystemExit('STOP: Midpoint audit and exact option tape required')
rows = [json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
rows = [r for r in rows if r.get('session_date') == DAY]
tapes = json.loads(tape_path.read_text())['tapes']
entries = [r for r in rows if r.get('event_type') in ('B_ENTRY', 'E_ENTRY')]
if len(entries) != 1 or len(tapes) != 1 or tapes[0].get('entry_event_id') != entries[0]['event_id']:
    raise SystemExit('STOP: expected one entry and matching tape; no ambiguous comparison')
entry = entries[0]
tape = tapes[0]
entry_price = float(entry['underlying_price'])
direction = entry['direction']
legs = tape['legs']
if len(legs) != 5 or len({l['instrument_key'] for l in legs}) != 5:
    raise SystemExit('STOP: five unique option contracts required')


def points(spot):
    return float(spot) - entry_price if direction == 'BULLISH' else entry_price - float(spot)


def fmt(value):
    return 'NA' if value is None else f'{value:+.2f}'


def option_exit(event):
    when = datetime.fromisoformat(event['event_timestamp']) + timedelta(minutes=1)
    outcome = []
    for leg in legs:
        by_time = {m['timestamp']: m for m in leg['minutes']}
        entry_bar = by_time.get(tape['entry_boundary'])
        exit_bar = by_time.get(when.isoformat())
        if entry_bar is None or exit_bar is None:
            outcome.append((leg['relation_to_atm'], None, None, 'EXACT_MINUTE_UNAVAILABLE'))
        else:
            buy, sell = float(entry_bar['open']), float(exit_bar['open'])
            outcome.append((leg['relation_to_atm'], sell, sell-buy, None))
    return when.isoformat(), outcome

print('MIDPOINT EXIT FORENSIC', DAY, 'family', entry['family'], direction)
print('Entry', entry['event_timestamp'], 'NIFTY', entry_price, 'option boundary', tape['entry_boundary'])
interesting = {'PLUS20_PROOF', 'RUNNER_CLASSIFICATION', 'DEGRADED_STARTED',
               'DEGRADED_TARGET_RECOVERED', 'CAP20_RESCUE_TRIGGERED',
               'STRUCTURAL_TERMINAL'}
cap_checks = [r for r in rows if r.get('event_type') == 'CAP20_CHECK'
              and r['event_timestamp'] >= entry['event_timestamp']]
eligible = [r for r in cap_checks if r.get('evidence', {}).get('condition_age_ge_10')
            and r.get('evidence', {}).get('condition_rebreak')]
print('CAP20 checks:', len(cap_checks), 'first age/rebreak eligible:',
      eligible[0]['event_timestamp'] if eligible else 'NONE')
for r in eligible[:3]:
    print('  CAP20', r['event_timestamp'], r.get('reason'),
          'directional points', r.get('directional_points'),
          json.dumps(r.get('evidence', {}), sort_keys=True))
for r in rows:
    if r.get('event_type') not in interesting or r['event_timestamp'] < entry['event_timestamp']:
        continue
    ts = r['event_timestamp']
    print('\nEVENT', ts, r['event_type'], 'reason', r.get('reason'),
          'NIFTY', r.get('underlying_price'),
          'directional close', fmt(points(r['underlying_price'])) if r.get('underlying_price') is not None else 'NA')
    if r['event_type'] in {'DEGRADED_STARTED', 'DEGRADED_TARGET_RECOVERED', 'STRUCTURAL_TERMINAL'}:
        exit_at, outcomes = option_exit(r)
        print('Hypothetical next option-minute OPEN', exit_at)
        for relative, exit_premium, pnl, issue in sorted(outcomes):
            print('  ATM%+d PE' % relative, 'exit', exit_premium, 'premium P&L', fmt(pnl), issue or '')
print('\nNo orders, quantity or charges. Earlier exits are counterfactual, not strategy events.')
