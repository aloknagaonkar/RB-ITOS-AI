"""Pure, observation-only Midpoint B/E degraded-exit research projection.

This module reads an existing audit and exact five-contract tape. It does not
change the strategy lifecycle, send orders, or imply executable OHLC fills.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Iterable

CANONICAL = 'CANONICAL_UNDERLYING_PLUS20_PROOF_T10'
PREMIUM = 'PREMIUM_PLUS20_ENTRY_T10'


def _time(value: str) -> datetime:
    ts = datetime.fromisoformat(value)
    if ts.tzinfo is None:
        raise ValueError('AWARE_TIMESTAMP_REQUIRED')
    return ts


def _rows(frame_or_rows) -> list[dict[str, Any]]:
    if hasattr(frame_or_rows, 'to_dict'):
        return frame_or_rows.to_dict(orient='records')
    return list(frame_or_rows)


def _first(rows, kind):
    return next((r for r in rows if r.get('event_type') == kind), None)


def _points(entry, event):
    if event is None or event.get('underlying_price') is None:
        return None
    sign = 1 if entry['direction'] == 'BULLISH' else -1
    return sign * (float(event['underlying_price']) - float(entry['underlying_price']))


def _quote_index(quotes: Iterable[dict] | None):
    idx = {}
    for q in quotes or []:
        key = (q['instrument_key'], _time(q['timestamp']))
        if key in idx:
            raise ValueError('DUPLICATE_EXACT_QUOTE')
        idx[key] = q
    return idx


def _price(value):
    x = float(value)
    if not isfinite(x) or x <= 0:
        raise ValueError('INVALID_OPTION_PRICE')
    return x


def project(audit_events, tape: dict, *, quotes=None,
            entry_slippage_points: float = 0.0,
            exit_slippage_points: float = 0.0,
            round_trip_charges_points: float = 0.0) -> dict:
    """Produce independent canonical and per-leg premium gates, with no future leakage.

    Event timestamp labels a completed one-minute close. The first causal exit
    premium is the exact next option-minute OPEN. Bid/ask estimates require
    quotes at exact entry and exit timestamps; no OHLC-to-bid approximation.
    """
    costs = [entry_slippage_points, exit_slippage_points, round_trip_charges_points]
    if any(not isfinite(x) or x < 0 for x in costs):
        raise ValueError('NONNEGATIVE_FINITE_COSTS_REQUIRED')
    rows = sorted(_rows(audit_events), key=lambda r: _time(r['event_timestamp']))
    entry = next((r for r in rows if r.get('event_id') == tape.get('entry_event_id')
                  and r.get('event_type') in (
                      'A_ENTRY', 'B_ENTRY', 'E_ENTRY', 'B_REARM_ENTRY', 'E_REARM_ENTRY',
                      'PM_B_ENTRY', 'PM_E_ENTRY'
                  )), None)
    if entry is None or entry.get('family') not in ('B', 'E', 'PM_B', 'PM_E'):
        raise ValueError('MATCHED_MIDPOINT_ENTRY_REQUIRED')
    if tape.get('session_date') != entry.get('session_date'):
        raise ValueError('SESSION_MISMATCH')
    if tape.get('direction') != entry.get('direction'):
        raise ValueError('DIRECTION_MISMATCH')
    entry_ts = _time(entry['event_timestamp'])
    following_entry = next((_time(r['event_timestamp']) for r in rows
                            if _time(r['event_timestamp']) > entry_ts
                            and r.get('event_type') in (
                                'A_ENTRY', 'B_ENTRY', 'E_ENTRY',
                                'B_REARM_ENTRY', 'E_REARM_ENTRY',
                                'PM_B_ENTRY', 'PM_E_ENTRY'
                            )), None)
    later = [r for r in rows if _time(r['event_timestamp']) >= entry_ts
             and (following_entry is None or _time(r['event_timestamp']) < following_entry)
             and r.get('family') == entry['family'] and r.get('direction') == entry['direction']]
    terminal = _first(later, 'STRUCTURAL_TERMINAL')
    cap20 = _first(later, 'CAP20_RESCUE_TRIGGERED')
    baseline = min((r for r in (cap20, terminal) if r is not None),
                   key=lambda r: _time(r['event_timestamp']), default=None)
    limit = _time(baseline['event_timestamp']) if baseline else None
    segment = [r for r in later if limit is None or _time(r['event_timestamp']) <= limit]
    proof = _first(segment, 'PLUS20_PROOF')
    classifier = _first(segment, 'RUNNER_CLASSIFICATION')
    degraded = _first(segment, 'DEGRADED_STARTED')
    canonical_ok = (proof is not None and classifier is not None
                    and classifier.get('result') == 'RUNNER_STRENGTHENING'
                    and _time(classifier['event_timestamp']) == _time(proof['event_timestamp']) + timedelta(minutes=10)
                    and degraded is not None
                    and _time(degraded['event_timestamp']) > _time(classifier['event_timestamp']))
    legs = tape.get('legs', [])
    if len(legs) != 5 or {x.get('relation_to_atm') for x in legs} != {-2, -1, 0, 1, 2}:
        raise ValueError('FIVE_UNIQUE_ATM_LEGS_REQUIRED')
    expected_side = 'CE' if entry['direction'] == 'BULLISH' else 'PE'
    if any(x.get('side') != expected_side for x in legs):
        raise ValueError('OPTION_SIDE_MISMATCH')
    expected_exit = _time(degraded['event_timestamp']) + timedelta(minutes=1) if degraded else None
    entry_boundary = _time(tape['entry_boundary'])
    quote_by_key = _quote_index(quotes)
    result = {'model': 'MIDPOINT_DEGRADED_EXIT_CANDIDATE_V1',
              'session_date': entry['session_date'], 'entry_event_id': entry['event_id'],
              'family': entry['family'], 'direction': entry['direction'],
              'observation_only': True, 'execution_enabled': False,
              'paper_order_enabled': False, 'quantity': None,
              'canonical_gate': {'status': 'QUALIFIED' if canonical_ok else 'NOT_QUALIFIED',
                                 'proof_timestamp': proof.get('event_timestamp') if proof else None,
                                 'classifier_timestamp': classifier.get('event_timestamp') if classifier else None},
              'degraded_signal_timestamp': degraded.get('event_timestamp') if degraded else None,
              'DEGRADED_EXIT_TIMESTAMP': expected_exit.isoformat() if canonical_ok else None,
              'baseline_type': baseline.get('event_type') if baseline else None,
              'baseline_timestamp': baseline.get('event_timestamp') if baseline else None,
              'terminal_timestamp': terminal.get('event_timestamp') if terminal else None,
              'DEGRADED_PREMIUMS': [], 'legs': []}
    for leg in sorted(legs, key=lambda x: x['relation_to_atm']):
        key = leg['instrument_key']
        minutes = {}
        for m in leg.get('minutes', []):
            timestamp = _time(m['timestamp'])
            if timestamp in minutes:
                raise ValueError('DUPLICATE_EXACT_OPTION_MINUTE')
            minutes[timestamp] = m
        start = minutes.get(entry_boundary)
        buy = _price(start['open']) if start else None
        # Premium proof is per independent contract, using only option bars
        # completed by exactly entry+10. Entry bar starts at next-minute open.
        exact_entry_t10 = entry_ts + timedelta(minutes=10)
        at_t10 = _first(segment, 'RUNNER_CLASSIFICATION')
        strict_classifier = at_t10 is not None and _time(at_t10['event_timestamp']) == exact_entry_t10 and at_t10.get('result') == 'RUNNER_STRENGTHENING'
        peak = None
        if buy is not None:
            t = entry_boundary
            while t < exact_entry_t10:
                bar = minutes.get(t)
                if bar is None:
                    peak = None
                    break
                peak = max(peak or 0.0, _price(bar['high']) - buy)
                t += timedelta(minutes=1)
        premium_proof = peak is not None and peak >= 20.0
        strict_ok = strict_classifier and premium_proof and degraded is not None and _time(degraded['event_timestamp']) > exact_entry_t10
        # Two separate tracks: canonical underlying proof, and the user's
        # alternative premium/entry+10 specification. Never merge gates.
        tracks = {}
        for name, qualifies in ((CANONICAL, canonical_ok), (PREMIUM, strict_ok)):
            effective = degraded if qualifies else baseline
            at = _time(effective['event_timestamp']) + timedelta(minutes=1) if effective else None
            exit_bar = minutes.get(at) if at else None
            sell = _price(exit_bar['open']) if exit_bar else None
            raw = sell - buy if buy is not None and sell is not None else None
            entry_quote = quote_by_key.get((key, entry_boundary))
            exit_quote = quote_by_key.get((key, at)) if at else None
            realistic = None
            if entry_quote and exit_quote:
                ask, bid = _price(entry_quote['ask']), _price(exit_quote['bid'])
                realistic = bid - exit_slippage_points - (ask + entry_slippage_points) - round_trip_charges_points
            tracks[name] = {'qualified': bool(qualifies), 'signal_timestamp': effective.get('event_timestamp') if effective else None,
                            'exit_timestamp': at.isoformat() if at else None,
                            'status': 'AVAILABLE' if raw is not None else 'EXACT_MINUTE_UNAVAILABLE',
                            'exit_open_premium': sell, 'ohlc_pnl_points': raw,
                            'bid_ask_net_points': realistic}
        baseline_at = _time(baseline['event_timestamp']) + timedelta(minutes=1) if baseline else None
        terminal_at = _time(terminal['event_timestamp']) + timedelta(minutes=1) if terminal else None
        baseline_open = _price(minutes[baseline_at]['open']) if baseline_at in minutes else None
        terminal_open = _price(minutes[terminal_at]['open']) if terminal_at in minutes else None
        candidate_open = tracks[CANONICAL]['exit_open_premium'] if canonical_ok else None
        base_event = baseline
        base_points = _points(entry, base_event)
        terminal_points = _points(entry, terminal)
        candidate_points = _points(entry, degraded) if canonical_ok else None
        leg_result = {'relation_to_atm':leg['relation_to_atm'], 'instrument_key':key,
                      'entry_open_premium':buy, 'premium_plus20_by_entry_t10':premium_proof,
                      'premium_mfe_by_entry_t10':peak, 'premium_gate_classifier_exact':strict_classifier,
                      'tracks':tracks,
                      'COMP_CAP20_TERMINAL':{'candidate_underlying_points':candidate_points,
                          'cap20_or_terminal_underlying_points':base_points,
                          'terminal_underlying_points':terminal_points,
                          'delta_vs_cap20_or_terminal_points':candidate_points-base_points if candidate_points is not None and base_points is not None else None,
                          'delta_vs_terminal_points':candidate_points-terminal_points if candidate_points is not None and terminal_points is not None else None,
                          'candidate_exit_open_premium':candidate_open,
                          'baseline_exit_open_premium':baseline_open,
                          'terminal_exit_open_premium':terminal_open,
                          'candidate_delta_vs_baseline_premium_points':candidate_open-baseline_open if candidate_open is not None and baseline_open is not None else None,
                          'candidate_delta_vs_terminal_premium_points':candidate_open-terminal_open if candidate_open is not None and terminal_open is not None else None}}
        result['legs'].append(leg_result)
        result['DEGRADED_PREMIUMS'].append(tracks[CANONICAL]['exit_open_premium'] if canonical_ok else None)
    return result


def summarize(projections: Iterable[dict]) -> dict:
    """Mean completed-trade NIFTY impact, with unresolved trades excluded."""
    result = {}
    for family in ('B', 'E', 'B+E'):
        selected = [p for p in projections if family == 'B+E' or p['family'] == family]
        completed = [p for p in selected if p.get('baseline_timestamp') is not None]
        changed = [p for p in completed if p['canonical_gate']['status'] == 'QUALIFIED']
        deltas = [p['legs'][0]['COMP_CAP20_TERMINAL']['delta_vs_cap20_or_terminal_points'] for p in changed]
        deltas = [x for x in deltas if x is not None]
        result[family] = {'entries':len(selected), 'completed':len(completed),
                          'unresolved':len(selected)-len(completed),
                          'changed_exits':len(changed),
                          'mean_nifty_point_impact':sum(deltas)/len(completed) if completed and len(deltas)==len(changed) else None,
                          'mean_changed_trade_impact':sum(deltas)/len(deltas) if deltas else None}
    return result
