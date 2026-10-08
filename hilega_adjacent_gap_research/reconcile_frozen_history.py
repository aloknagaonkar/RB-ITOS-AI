"""Test an omitted warmup date hypothesis without modifying any source cache.

Runs research only after ALL frozen trace prices and indicator states match.
The exclusion is a reproduction of a historical cohort, not a production fix.
"""
import argparse
import copy
import hashlib
import json
import math
import tempfile
from datetime import date, datetime
from pathlib import Path

from research_adjacent_gap import read_csv, run
from scripts.validate_hilega_wma_delayed_confirmation import build_indicator_states, IST

def validate(evidence, cache):
    rows = sorted(read_csv(evidence / 'candidate-timeline.csv'), key=lambda r: r['minute_timestamp'])
    dates = {r['session_date'] for r in rows}
    states, snapshots, minutes = build_indicator_states(cache, dates)
    lookup = {day: {c.timestamp.astimezone(IST): c for c in candles}
              for day, candles in minutes.items()}
    count = 0; last_match = None
    for row in rows:
        day = row['session_date']
        stamp = datetime.fromisoformat(row['minute_timestamp']).astimezone(IST)
        ref = datetime.fromisoformat(row['reference_5m_timestamp']).astimezone(IST)
        candle = lookup[day].get(stamp); base = states.get((day, ref))
        if candle is None or base is None:
            return {'matched': False, 'reason': 'MISSING_OBSERVATION', 'timestamp': stamp.isoformat()}
        now = copy.deepcopy(base).update(float(candle.close))
        before = snapshots[(day, ref)]
        fields = [('observed_close', candle.close), ('reference_rsi9', before.rsi9),
            ('reference_ema3_rsi', before.ema3_rsi), ('reference_wma21_rsi', before.wma21_rsi),
            ('provisional_rsi9', now.rsi9), ('provisional_ema3_rsi', now.ema3_rsi),
            ('provisional_wma21_rsi', now.wma21_rsi)]
        differences = []
        for key, actual in fields:
            expected = float(row[key])
            if actual is None or not math.isclose(float(actual), expected, abs_tol=1e-7, rel_tol=1e-9):
                differences.append({'field': key, 'current': actual, 'frozen': expected})
        if differences:
            return {'matched': False, 'verified_observations': count, 'last_match': last_match,
                'first_mismatch': stamp.isoformat(), 'trade_id': row['trade_id'], 'differences': differences}
        count += 1; last_match = stamp.isoformat()
        if count % 5000 == 0:
            print('Parity observations checked:', count, flush=True)
    return {'matched': True, 'verified_observations': count,
        'sessions': len(dates), 'last_match': last_match}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence-root', type=Path, default=Path('data/historical-evidence/hilega-wma-gap-490-v1'))
    parser.add_argument('--cache-root', type=Path, default=Path('data/historical-evidence/hilega-milega-underlying-cache-v1'))
    parser.add_argument('--test-omitted-date', default='2026-09-24')
    parser.add_argument('--output-root', type=Path, default=Path('data/historical-evidence/hilega-adjacent-gap-reconciled-490-v1'))
    parser.add_argument('--run-if-parity-matches', action='store_true')
    args = parser.parse_args()
    date.fromisoformat(args.test_omitted_date)
    if args.output_root.exists():
        raise SystemExit('STOP: output exists; choose a new --output-root')
    trades = read_csv(args.evidence_root / 'trade-results.csv')
    selected_dates = {r['session_date'] for r in trades}
    if args.test_omitted_date in selected_dates:
        raise SystemExit('STOP: proposed date contains frozen trades; it cannot be omitted as warmup')
    omitted = args.cache_root / (args.test_omitted_date + '.json')
    if not omitted.is_file():
        raise SystemExit('STOP: proposed omitted-date cache not found')
    print('Testing omitted warmup date:', args.test_omitted_date, flush=True)
    print('Source cache and frozen evidence remain unchanged.', flush=True)
    with tempfile.TemporaryDirectory(prefix='hilega-parity-') as tmp:
        cache = Path(tmp)
        paths = sorted(args.cache_root.glob('*.json'))
        fingerprints = []
        for path in paths:
            if path == omitted:
                continue
            # Research-only view; originals are never removed or rewritten.
            (cache / path.name).symlink_to(path.resolve())
            fingerprints.append({'name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        result = validate(args.evidence_root, cache)
        print(json.dumps({'history_parity': result}, indent=2), flush=True)
        if not result['matched']:
            raise SystemExit('STOP: omitted-date hypothesis did not reproduce frozen history. No strategy comparison published.')
        if not args.run_if_parity_matches:
            print('PASS: all control observations reproduced; no research output requested')
            return
        if len(selected_dates) != 490:
            raise SystemExit('STOP: frozen trade cohort is not 490 dates')
        run(args.evidence_root, cache, args.output_root, 490)
        provenance = {'model': 'FROZEN_HISTORY_REPRODUCTION_V1',
            'excluded_warmup_date': args.test_omitted_date,
            'excluded_cache_sha256': hashlib.sha256(omitted.read_bytes()).hexdigest(),
            'history_parity': result, 'cache_inputs': fingerprints,
            'exclusion_scope': 'This temporary historical reproduction only; not live or current full-data replay',
            'execution_enabled': False}
        (args.output_root / 'history-reconciliation.json').write_text(json.dumps(provenance, indent=2))
        report_path = args.output_root / 'report.json'
        report = json.loads(report_path.read_text())
        report['history_reconciliation'] = provenance
        report_path.write_text(json.dumps(report, indent=2))
        print('PASS: research published only after full frozen-observation parity')

if __name__ == '__main__':
    main()
