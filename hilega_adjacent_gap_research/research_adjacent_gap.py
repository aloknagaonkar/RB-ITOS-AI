"""Research only: canonical + WMA>=.75 + actual adjacent-minute gap expansion.

Uses frozen trade/timeline artifacts as the control. Rebuilds prior minute
indicators from exact candles, including the minute before the first trace row.
Never imports a broker client or modifies strategy/audit/forward evidence.
"""
import argparse
import copy
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from scripts.validate_hilega_wma_delayed_confirmation import build_indicator_states, floor_5m, IST

def read_csv(path):
    with path.open(newline='') as handle:
        return list(csv.DictReader(handle))

def number(value):
    return None if value in ('', None) else float(value)

def gap(ema, wma, direction):
    return (ema - wma) * (1 if direction == 'BULLISH' else -1)

def passes(strength, current_gap, previous_gap):
    return strength >= .75 and current_gap > 0 and current_gap > previous_gap

def quantile(values, proportion):
    ordered = sorted(values); index = (len(ordered) - 1) * proportion
    lower = math.floor(index); upper = math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)

def summarize(rows, field, thresholds):
    accepted = [r for r in rows if r[field] is not None]
    denied = [r for r in rows if r[field] is None]
    gains = sum(r[field] for r in accepted if r[field] > 0)
    losses = -sum(r[field] for r in accepted if r[field] < 0)
    return {'signals': len(rows), 'entries': len(accepted), 'denied': len(denied),
        'winning_trades': sum(r[field] > 0 for r in accepted),
        'losing_trades': sum(r[field] < 0 for r in accepted),
        'gross_points_gained': gains, 'gross_points_lost': losses,
        'net_points': gains - losses, 'profit_factor': gains / losses if losses else None,
        'denied_canonical_winners': sum(r['canonical_points'] > 0 for r in denied),
        'denied_winner_points': sum(r['canonical_points'] for r in denied if r['canonical_points'] > 0),
        'denied_canonical_losers': sum(r['canonical_points'] < 0 for r in denied),
        'saved_denied_loss_points': -sum(r['canonical_points'] for r in denied if r['canonical_points'] < 0),
        'denied_plus20_mfe_setups': sum(r['canonical_mfe'] >= 20 for r in denied),
        'denied_top_decile_mfe_setups': sum(r['canonical_mfe'] >= thresholds[r['direction']] for r in denied)}

def run(evidence, cache, output, expected_sessions):
    if output.exists():
        raise ValueError('Output exists; choose a new output directory to preserve earlier research')
    trades_path = evidence / 'trade-results.csv'
    timeline_path = evidence / 'candidate-timeline.csv'
    trades = read_csv(trades_path); timeline = read_csv(timeline_path)
    dates = sorted({t['session_date'] for t in trades})
    if len(dates) != expected_sessions:
        raise ValueError(f'Expected {expected_sessions} trade sessions, found {len(dates)}; do not label an incomplete run 490 sessions')
    grouped = defaultdict(list)
    for row in timeline:
        grouped[row['trade_id']].append(row)
    states, _, minutes = build_indicator_states(cache, set(dates))
    by_minute = {day: {c.timestamp.astimezone(IST).replace(second=0, microsecond=0): c for c in rows}
        for day, rows in minutes.items()}

    def observe(day, stamp):
        candle = by_minute[day].get(stamp)
        reference = floor_5m(stamp) - timedelta(minutes=5)
        base = states.get((day, reference))
        if candle is None or base is None:
            return None
        snap = copy.deepcopy(base).update(float(candle.close))
        if snap.ema3_rsi is None or snap.wma21_rsi is None:
            return None
        return {'timestamp': stamp.isoformat(), 'ema3': float(snap.ema3_rsi),
            'wma21': float(snap.wma21_rsi), 'rsi9': snap.rsi9,
            'close': float(candle.close), 'reference_5m_timestamp': reference.isoformat()}

    comparisons = []; checks = []; missing_comparisons = 0; verified = 0
    for trade in trades:
        day = trade['session_date']; direction = trade['direction']
        trace = sorted(grouped[trade['trade_id']], key=lambda r: r['minute_timestamp'])
        if not trace:
            raise ValueError('No control timeline for trade: ' + trade['trade_id'])
        chosen = None
        for row in trace:
            if str(row['within_confirmation_window']).lower() not in {'true', '1'}:
                continue
            stamp = datetime.fromisoformat(row['minute_timestamp']).astimezone(IST)
            current = observe(day, stamp)
            previous = observe(day, stamp - timedelta(minutes=1))
            if current is None or previous is None:
                missing_comparisons += 1
                checks.append({'trade_id': trade['trade_id'], 'timestamp': stamp.isoformat(),
                    'status': 'DATA_UNAVAILABLE_WAIT', 'previous_timestamp': (stamp - timedelta(minutes=1)).isoformat()})
                continue
            # Prove reconstructed warmup/indicator values match the frozen control.
            for name, source in [('ema3', 'provisional_ema3_rsi'), ('wma21', 'provisional_wma21_rsi')]:
                if not math.isclose(current[name], float(row[source]), abs_tol=1e-7, rel_tol=1e-9):
                    raise ValueError(f'Indicator parity mismatch {trade["trade_id"]} {stamp} {name}; research stopped')
            verified += 1
            current_gap = gap(current['ema3'], current['wma21'], direction)
            previous_gap = gap(previous['ema3'], previous['wma21'], direction)
            strength = float(row['directional_wma_change'])
            passed = passes(strength, current_gap, previous_gap)
            check = {'trade_id': trade['trade_id'], 'session_date': day, 'direction': direction,
                'signal_timestamp': trade['entry_timestamp'], 'current': current, 'previous': previous,
                'directional_wma_strength': strength, 'previous_gap': previous_gap,
                'current_gap': current_gap, 'gap_delta': current_gap - previous_gap,
                'wma_pass': strength >= .75, 'positive_gap_pass': current_gap > 0,
                'expansion_pass': current_gap > previous_gap,
                'passed': passed, 'status': 'ENTRY' if passed else 'WAIT'}
            checks.append(check)
            if passed:
                chosen = check
                break
        sign = 1 if direction == 'BULLISH' else -1
        points = None if chosen is None else sign * (float(trade['exit_price']) - chosen['current']['close'])
        comparisons.append({'trade_id': trade['trade_id'], 'session_date': day, 'direction': direction,
            'signal_timestamp': trade['entry_timestamp'], 'canonical_entry_price': float(trade['entry_price']),
            'exit_timestamp': trade['exit_timestamp'], 'exit_price': float(trade['exit_price']),
            'exit_event': trade.get('exit_event'), 'canonical_points': float(trade['canonical_points']),
            'canonical_mfe': float(trade['mfe_points']),
            'control_entry_timestamp': trade.get('candidate_entry_timestamp'),
            'control_entry_price': number(trade.get('candidate_entry_price')),
            'control_points': number(trade.get('candidate_points')),
            'candidate_entry_timestamp': None if chosen is None else chosen['current']['timestamp'],
            'candidate_entry_price': None if chosen is None else chosen['current']['close'],
            'candidate_points': points, 'entry_check': chosen})
    development_dates = dates[:480] if len(dates) == 490 else dates
    thresholds = {direction: quantile([r['canonical_mfe'] for r in comparisons
        if r['direction'] == direction and r['session_date'] in development_dates], .9)
        for direction in ['BULLISH', 'BEARISH']}
    headline = []; daily = []
    cohorts = [('ALL_DEVELOPMENT_EVIDENCE', comparisons)]
    if len(dates) == 490:
        cohorts += [('DEVELOPMENT_480', [r for r in comparisons if r['session_date'] in dates[:480]]),
            ('PREVIOUSLY_OBSERVED_10', [r for r in comparisons if r['session_date'] in dates[480:]])]
        cohorts += [(f'DEVELOPMENT_BLOCK_{i+1}', [r for r in comparisons if r['session_date'] in dates[i*160:(i+1)*160]]) for i in range(3)]
    for cohort, selected in cohorts:
        for direction in ['ALL', 'BULLISH', 'BEARISH']:
            subset = selected if direction == 'ALL' else [r for r in selected if r['direction'] == direction]
            for field, policy in [('control_points', 'CURRENT_WAITING_RULE'), ('candidate_points', 'ACTUAL_PREVIOUS_MINUTE_GAP')]:
                headline.append({'cohort': cohort, 'direction': direction, 'policy': policy, **summarize(subset, field, thresholds)})
    for day in dates:
        for direction in ['ALL', 'BULLISH', 'BEARISH']:
            subset = [r for r in comparisons if r['session_date'] == day and (direction == 'ALL' or r['direction'] == direction)]
            daily.append({'session_date': day, 'direction': direction,
                'control': summarize(subset, 'control_points', thresholds),
                'candidate': summarize(subset, 'candidate_points', thresholds)})
    report = {'model': 'ACTUAL_ADJACENT_MINUTE_GAP_RESEARCH_V1', 'sessions': len(dates),
        'dates': dates, 'frozen_input_sha256': hashlib.sha256(trades_path.read_bytes()).hexdigest(),
        'verified_indicator_comparisons': verified, 'missing_comparisons': missing_comparisons,
        'top_decile_mfe_thresholds': thresholds, 'headline': headline, 'daily': daily,
        'trades': comparisons, 'minute_checks': checks, 'execution_enabled': False,
        'warning': 'Development research only. Prior minute reconstructed from its own completed close, without future candles. No EMA continuation/alignment gate. Original confirmation window and canonical exit retained. Missing comparison means WAIT. Denied-MFE counts measure denied setups, not post-entry MFE retention; fees, option P&L, and broker fill modelling excluded.'}
    output.mkdir(parents=True)
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    for row in headline:
        print(json.dumps(row))
    print('Output:', output / 'report.json')

def self_test():
    assert passes(.75, 6.5, 6.0)
    assert not passes(.74, 6.5, 6.0)
    assert not passes(.8, 6.5, 6.5)
    assert not passes(.8, 6.5, 7.0)
    assert not passes(.8, -.1, -.2)
    assert gap(40, 47, 'BEARISH') == 7
    assert quantile([0, 10], .9) == 9
    print('PASS: directional threshold, positive gap, expansion, equality and bearish sign checks')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence-root', type=Path, default=Path('data/historical-evidence/hilega-wma-gap-490-v1'))
    parser.add_argument('--cache-root', type=Path, default=Path('data/historical-evidence/hilega-milega-underlying-cache-v1'))
    parser.add_argument('--output-root', type=Path, default=Path('data/historical-evidence/hilega-actual-adjacent-gap-490-v1'))
    parser.add_argument('--expected-sessions', type=int, default=490)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        run(args.evidence_root, args.cache_root, args.output_root, args.expected_sessions)
