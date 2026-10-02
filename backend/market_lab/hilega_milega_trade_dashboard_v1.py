"""Read-only, shared historical/live Hilega ATM±2 shadow economics projector.

One independent hypothetical CE observation per strike, *not* a combined position.
Only a complete exact lifecycle EXIT contributes to realized premium-point totals.
Never converts premium points to rupees: there are no quantities, fills or fees.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

LIFECYCLE = {
    'OPTION_SHADOW_LIFECYCLE_START',
    'OPTION_SHADOW_LIFECYCLE_RESTORE',
    'OPTION_SHADOW_LIFECYCLE_UPDATE',
    'OPTION_SHADOW_LIFECYCLE_EXIT',
    'OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY',
    'OPTION_SHADOW_LIFECYCLE_EXIT_RETRY',
    'OPTION_SHADOW_PENDING_EXIT_RESTORE',
}
ROLES = (-2, -1, 0, 1, 2)


def project_shadow_dashboard(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic projection; identical inputs yield identical historical/live results."""
    records = list(rows)
    by_signal: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(records):
        stage = row.get('stage')
        if stage not in LIFECYCLE:
            continue
        payload = row.get('payload') or {}
        key = payload.get('signal_bar')
        if not key:
            continue
        event = by_signal.setdefault(key, {'signal_bar': key, 'events': []})
        event['events'].append((index, stage, row.get('status'), payload))

    trades = []
    for key in sorted(by_signal):
        events = by_signal[key]['events']
        starts = [e for e in events if e[1] in ('OPTION_SHADOW_LIFECYCLE_START', 'OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY') and e[3].get('status') == 'ACTIVE']
        restores = [e for e in events if e[1] == 'OPTION_SHADOW_LIFECYCLE_RESTORE' and e[3].get('status') == 'ACTIVE']
        entries = starts or restores
        entry = entries[0][3] if entries else None
        updates = [e for e in events if e[1] == 'OPTION_SHADOW_LIFECYCLE_UPDATE' and e[3].get('status') == 'ACTIVE']
        exits = [e for e in events if e[1] in ('OPTION_SHADOW_LIFECYCLE_EXIT', 'OPTION_SHADOW_LIFECYCLE_EXIT_RETRY') and e[3].get('status') == 'CLOSED']
        attempts = [e for e in events if e[1] in ('OPTION_SHADOW_LIFECYCLE_EXIT', 'OPTION_SHADOW_LIFECYCLE_EXIT_RETRY', 'OPTION_SHADOW_PENDING_EXIT_RESTORE')]
        pending = [e for e in attempts if e[3].get('status') == 'PENDING_EXACT_EXIT']
        # An attempted exit bounds the economic observation: later legacy
        # updates (including bad historical records) cannot inflate MFE/MAE.
        first_exit_index = min((e[0] for e in attempts), default=None)
        valid_updates = [e for e in updates if first_exit_index is None or e[0] < first_exit_index]
        last = exits[-1][3] if exits else (valid_updates[-1][3] if valid_updates else entry)
        failures = [e for e in events if e[3].get('status') not in ('ACTIVE', 'CLOSED')]
        if not entry:
            trades.append({
                'signal_bar': key, 'status': 'NO_EXACT_ENTRY', 'complete': False,
                'issue': failures[-1][3].get('issue') if failures else 'EXACT_ENTRY_NOT_AVAILABLE',
                'legs': [], 'source': None, 'expiry': None, 'atm': None,
            })
            continue
        entry_legs = {l.get('instrument_key'): l for l in entry.get('legs', [])}
        latest_legs = {l.get('instrument_key'): l for l in (last or {}).get('legs', [])}
        legs = []
        for instrument, original in sorted(entry_legs.items(), key=lambda item: (item[1].get('relation_to_atm', 99), str(item[0]))):
            latest = latest_legs.get(instrument, original)
            # Expose individual legs, never sum five hypothetical simultaneous choices.
            legs.append({
                'relation_to_atm': original.get('relation_to_atm'),
                'strike': original.get('strike'), 'instrument_key': instrument,
                'entry_timestamp': original.get('entry_timestamp'),
                'entry_open': original.get('entry_open'),
                'latest_completed_minute': latest.get('latest_completed_minute'),
                'latest_close': latest.get('latest_close'),
                'current_points': latest.get('current_points'),
                'current_return_pct': latest.get('current_return_pct'),
                'mfe_points': latest.get('mfe_points'), 'mfe_pct': latest.get('mfe_pct'),
                'mae_points': latest.get('mae_points'), 'mae_pct': latest.get('mae_pct'),
                'exit_timestamp': latest.get('exit_timestamp'), 'exit_open': latest.get('exit_open'),
                'realized_points': latest.get('realized_points'),
                'realized_return_pct': latest.get('realized_return_pct'),
            })
        attempted_exit = bool(attempts)
        complete_exit = bool(exits) and len(legs) == 5 and all(
            l['relation_to_atm'] in ROLES and
            l['entry_open'] is not None and l['exit_open'] is not None and
            l['realized_points'] is not None for l in legs
        ) and sorted(l['relation_to_atm'] for l in legs) == list(ROLES)
        trades.append({
            'signal_bar': key, 'signal_boundary': entry.get('signal_boundary'),
            'signal_spot': entry.get('signal_spot'), 'source': entry.get('source'),
            'expiry': entry.get('expiry'), 'atm': entry.get('atm'),
            'status': 'CLOSED' if complete_exit else ('PENDING_EXACT_EXIT' if pending else ('INCOMPLETE_EXIT' if attempted_exit else 'ACTIVE')),
            'complete': complete_exit, 'exit_reason': (exits[-1][3].get('exit_reason') if exits else (pending[-1][3].get('exit_reason') if pending else (last or {}).get('exit_reason'))),
            'issue': pending[-1][3].get('issue') if pending else (failures[-1][3].get('issue') if failures else None),
            'legs': legs, 'update_count': len(valid_updates),
            'pending_exit_boundary': pending[-1][3].get('pending_exit_boundary') if pending else None,
        })

    by_role: dict[int, dict[str, Any]] = {r: {
        'role': r, 'closed_count': 0, 'positive_count': 0,
        'total_realized_premium_points': 0.0, 'mean_return_pct': None,
        'open_count': 0, 'missing_count': 0,
    } for r in ROLES}
    returns: dict[int, list[float]] = defaultdict(list)
    for trade in trades:
        mapped = {l['relation_to_atm']: l for l in trade['legs']}
        for role, agg in by_role.items():
            leg = mapped.get(role)
            if trade['complete'] and leg and leg['realized_points'] is not None:
                agg['closed_count'] += 1
                points = float(leg['realized_points'])
                agg['total_realized_premium_points'] += points
                agg['positive_count'] += int(points > 0)
                if leg['realized_return_pct'] is not None:
                    returns[role].append(float(leg['realized_return_pct']))
            elif trade['status'] == 'ACTIVE' and leg:
                agg['open_count'] += 1
            else:
                agg['missing_count'] += 1
    for role, agg in by_role.items():
        agg['total_realized_premium_points'] = round(agg['total_realized_premium_points'], 4)
        agg['mean_return_pct'] = round(sum(returns[role]) / len(returns[role]), 4) if returns[role] else None
    return {
        'model': 'HILEGA_MILEGA_SHADOW_DASHBOARD_V1',
        'account_pnl_rupees': None, 'quantity': None, 'fees_included': False,
        'measurement': 'INDEPENDENT_SHADOW_PREMIUM_POINTS_PER_1_OPTION_UNIT',
        'warning': 'NOT EXECUTED P&L: ATM±2 are five independent hypothetical observations; no quantities, spreads, slippage or fees.',
        'trade_count': len(trades),
        'complete_closed_count': sum(t['complete'] for t in trades),
        'incomplete_count': sum(t['status'] in ('NO_EXACT_ENTRY', 'INCOMPLETE_EXIT') for t in trades),
        'pending_exit_count': sum(t['status'] == 'PENDING_EXACT_EXIT' for t in trades),
        'active_count': sum(t['status'] == 'ACTIVE' for t in trades),
        'by_role': [by_role[r] for r in ROLES],
        'trades': list(reversed(trades)),
    }
