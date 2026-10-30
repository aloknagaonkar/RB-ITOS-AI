"""Read-only audited historical vs captured-live comparison (no broker orders).

Only same-session, same-version, matching-market-data comparisons can PASS.
Restart/partial coverage is not silently promoted into parity evidence.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import json
import math
import os
from pathlib import Path
from typing import Any

from .hilega_milega_strategy_v1 import STRATEGY_ID
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

MODEL = 'HILEGA_MILEGA_REAL_SESSION_PARITY_V1'
CORE_STAGES = ('INDICATOR_CALCULATION', 'STRATEGY_DECISION_RESULT', 'STRATEGY_TRANSITION', 'SESSION_CUTOFF_SOURCE', 'UNDERLYING_5M_BUILD')
OPTION_STAGES = ('OPTION_CANDIDATE_SET', 'OPTION_CANDIDATE_MARKET_SNAPSHOT',
                 'OPTION_SHADOW_LIFECYCLE_START', 'OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY',
                 'OPTION_SHADOW_LIFECYCLE_UPDATE', 'OPTION_SHADOW_LIFECYCLE_EXIT',
                 'OPTION_SHADOW_LIFECYCLE_EXIT_RETRY')
# Only semantic fields, not poll time, sequence or mutable presentation metadata.
FIELDS = {
    'INDICATOR_CALCULATION': ('close', 'rsi9', 'ema3_rsi', 'wma21_rsi'),
    'STRATEGY_DECISION_RESULT': ('state_before', 'state_after', 'selected_route', 'route_a_eligible',
        'route_a_pass', 'route_a_fail_reasons', 'route_b_eligible', 'route_b_pass',
        'route_b_fail_reasons', 'route_b_suppressed_by_route_a_priority', 'events_emitted',
        'rsi_cross_ema_up', 'rsi_cross_wma_down', 'rsi_gt_50', 'rsi_gt_wma',
        'ema_gt_wma', 'rsi_rising', 'ema_rising', 'structural_exit_condition'),
    'STRATEGY_TRANSITION': ('event_type', 'entry_time', 'entry_price', 'exit_reason', 'points',
        'price', 'source', 'state_before', 'state_after', 'details'),
    'SESSION_CUTOFF_SOURCE': ('cutoff_timestamp', 'cutoff_open', 'events'),
    'UNDERLYING_5M_BUILD': ('bar_timestamp', 'open', 'high', 'low', 'close', 'events', 'state'),
    'OPTION_CANDIDATE_SET': ('signal_bar', 'signal_spot', 'expiry', 'atm', 'issue', 'status'),
    'OPTION_CANDIDATE_MARKET_SNAPSHOT': ('signal_bar', 'expiry', 'atm', 'status', 'issue'),
    'OPTION_SHADOW_LIFECYCLE_START': ('signal_bar', 'signal_boundary', 'expiry', 'atm', 'status', 'issue', 'legs'),
    'OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY': ('signal_bar', 'signal_boundary', 'expiry', 'atm', 'status', 'issue', 'legs'),
    'OPTION_SHADOW_LIFECYCLE_UPDATE': ('signal_bar', 'latest_completed_minute', 'status', 'legs'),
    'OPTION_SHADOW_LIFECYCLE_EXIT': ('signal_bar', 'exit_reason', 'exit_boundary', 'status', 'issue', 'legs'),
    'OPTION_SHADOW_LIFECYCLE_EXIT_RETRY': ('signal_bar', 'exit_reason', 'exit_boundary', 'status', 'issue', 'legs'),
}


def _load_and_verify(path: str | Path, session: str) -> tuple[list[dict], str | None, dict]:
    path = Path(path)
    if not path.is_file():
        return [], f'FILE_MISSING:{path}', {}
    store = ShadowStepAuditStoreV1(path)
    try:
        ok, problem = store.verify_chain()
        if not ok:
            return [], f'INVALID_HASH_CHAIN:{problem}', {}
        all_rows = store.read_all()
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        return [], f'INVALID_AUDIT:{type(exc).__name__}:{exc}', {}
    rows = []
    excluded = defaultdict(int)
    for r in all_rows:
        p = r.get('payload') or {}
        checkpoint = r.get('checkpoint') or p.get('signal_bar') or p.get('bar_timestamp') or p.get('cutoff_timestamp')
        if not (isinstance(checkpoint, str) and checkpoint.startswith(session)):
            excluded['different_session_or_no_checkpoint'] += 1
            continue
        if p.get('strategy_id', STRATEGY_ID) != STRATEGY_ID:
            excluded['different_strategy'] += 1
            continue
        rows.append(r)
    versions = sorted({str((r.get('payload') or {}).get('strategy_version'))
                       for r in rows if (r.get('payload') or {}).get('strategy_version')})
    return rows, None, {'versions': versions, 'records_in_session': len(rows), 'excluded': dict(excluded)}


def _key(record: dict, stage: str) -> tuple:
    p = record.get('payload') or {}
    checkpoint = record.get('checkpoint') or p.get('signal_bar') or p.get('bar_timestamp') or p.get('cutoff_timestamp')
    if stage == 'STRATEGY_TRANSITION':
        return (checkpoint, stage, p.get('event_type'))
    if stage in OPTION_STAGES:
        return (checkpoint, stage, p.get('signal_bar'), p.get('latest_completed_minute'),
                p.get('exit_boundary'), p.get('status'))
    return (checkpoint, stage)


def _project(record: dict, stage: str) -> dict:
    p = record.get('payload') or {}
    return {'status': record.get('status'),
            'payload': {field: p.get(field) for field in FIELDS[stage] if field in p}}


def _equal(a: Any, b: Any, tolerance: float = 1e-6) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return math.isclose(a, b, rel_tol=1e-10, abs_tol=tolerance)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y, tolerance) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k], tolerance) for k in a)
    return a == b


def _diff(a: Any, b: Any, prefix='', tolerance=1e-6) -> list[dict]:
    if _equal(a, b, tolerance):
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        result = []
        for k in sorted(a.keys() | b.keys()):
            key = f'{prefix}.{k}' if prefix else k
            if k not in a or k not in b:
                result.append({'field': key, 'historical': a.get(k, '<ABSENT>'), 'live': b.get(k, '<ABSENT>')})
            else:
                result.extend(_diff(a[k], b[k], key, tolerance))
        return result
    if isinstance(a, list) and isinstance(b, list):
        result = []
        for i in range(max(len(a), len(b))):
            if i >= len(a) or i >= len(b):
                result.append({'field': f'{prefix}[{i}]', 'historical': a[i] if i < len(a) else '<ABSENT>',
                               'live': b[i] if i < len(b) else '<ABSENT>'})
            else:
                result.extend(_diff(a[i], b[i], f'{prefix}[{i}]', tolerance))
        return result
    return [{'field': prefix, 'historical': a, 'live': b}]


def _index(rows: list[dict], stages: tuple[str, ...]) -> tuple[dict[tuple, dict], list[dict]]:
    index = {}
    conflicts = []
    for row in rows:
        stage = row.get('stage')
        if stage not in stages:
            continue
        key = _key(row, stage)
        normalized = _project(row, stage)
        if key in index and not _equal(index[key], normalized):
            conflicts.append({'checkpoint': key[0], 'stage': stage, 'reason': 'DIFFERING_DUPLICATE_RECORDS',
                              'previous': index[key], 'additional': normalized})
        else:
            index[key] = normalized
    return index, conflicts


def _compare(historical: list[dict], live: list[dict], stages: tuple[str, ...], tolerance: float) -> dict:
    hist, hc = _index(historical, stages)
    observed, lc = _index(live, stages)
    common = sorted(hist.keys() & observed.keys(), key=str)
    mismatches = []
    for key in common:
        differences = _diff(hist[key], observed[key], tolerance=tolerance)
        if differences:
            mismatches.append({'checkpoint': key[0], 'stage': key[1], 'event': key[2:], 'differences': differences})
    return {
        'historical_events': len(hist), 'live_events': len(observed),
        'compared_events': len(common),
        'missing_in_live': [{'key': list(k)} for k in sorted(hist.keys() - observed.keys(), key=str)],
        'missing_in_historical': [{'key': list(k)} for k in sorted(observed.keys() - hist.keys(), key=str)],
        'duplicate_conflicts': {'historical': hc, 'live': lc}, 'mismatches': mismatches,
    }


def compare_audit_files(*, historical_path: str | Path, live_path: str | Path,
                        session_date: str, tolerance: float = 1e-6,
                        historical_build_id: str | None = None,
                        live_build_id: str | None = None) -> dict:
    date.fromisoformat(session_date)
    history, h_error, h_meta = _load_and_verify(historical_path, session_date)
    live, l_error, l_meta = _load_and_verify(live_path, session_date)
    errors = [x for x in [h_error, l_error] if x]
    result = {'model': MODEL, 'session_date': session_date,
              'historical': h_meta, 'live': l_meta, 'preconditions': errors,
              'core': None, 'options': None, 'status': 'INSUFFICIENT_EVIDENCE'}
    if errors:
        return result
    hv, lv = h_meta['versions'], l_meta['versions']
    if len(hv) != 1 or len(lv) != 1 or hv != lv:
        result['preconditions'].append(f'VERSION_MISMATCH_OR_UNKNOWN:historical={hv},live={lv}')
        return result
    result['core'] = _compare(history, live, CORE_STAGES, tolerance)
    result['options'] = _compare(history, live, OPTION_STAGES, tolerance)
    c, o = result['core'], result['options']
    errors_found = bool(c['mismatches'] or o['mismatches'] or c['duplicate_conflicts']['historical']
                        or c['duplicate_conflicts']['live'] or o['duplicate_conflicts']['historical']
                        or o['duplicate_conflicts']['live'])
    # Partial coverage is not a PASS, even if every overlapping event matches.
    incomplete = bool(c['missing_in_live'] or c['missing_in_historical'] or o['missing_in_live']
                      or o['missing_in_historical'] or c['compared_events'] == 0)
    entries = [r for r in history if r.get('stage') == 'STRATEGY_TRANSITION'
               and str((r.get('payload') or {}).get('event_type', '')).startswith('ENTRY_')]
    if entries and (o['historical_events'] == 0 or o['live_events'] == 0):
        incomplete = True
        result['preconditions'].append('OPTION_EVIDENCE_MISSING_FOR_ENTRY')
    if not historical_build_id or not live_build_id or historical_build_id != live_build_id:
        incomplete = True
        result['preconditions'].append('BUILD_ID_UNVERIFIED_OR_DIFFERENT:historical=%s,live=%s'
                                       % (historical_build_id, live_build_id))
    result['status'] = 'FAIL' if errors_found else ('INSUFFICIENT_EVIDENCE' if incomplete else 'PASS')
    result['caveat'] = ('Audit parity requires equivalent market-data release timing, expiry contract identity, '
                        'capture version and live session coverage; old September 23 lifecycle bugs cannot '
                        'be counted as Phase 7C live validation.')
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Read-only real-session historical/live audit comparison')
    parser.add_argument('--session-date', required=True)
    parser.add_argument('--historical-audit', required=True, type=Path)
    parser.add_argument('--live-audit', default='data/live-observation/hilega-milega-v1/step-audit.jsonl', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--tolerance', type=float, default=1e-6)
    parser.add_argument('--historical-build-id', help='Provenance of historical replay code')
    parser.add_argument('--live-build-id', help='Captured live worker code provenance; never guess')
    args = parser.parse_args(argv)
    report = compare_audit_files(historical_path=args.historical_audit, live_path=args.live_audit,
                                 session_date=args.session_date, tolerance=args.tolerance,
                                 historical_build_id=args.historical_build_id, live_build_id=args.live_build_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'output': str(args.output),
                      'core': report['core'] and {k: report['core'][k] for k in ('compared_events', 'mismatches')},
                      'preconditions': report['preconditions']}, default=str, indent=2))
    return {'PASS': 0, 'FAIL': 1, 'INSUFFICIENT_EVIDENCE': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
