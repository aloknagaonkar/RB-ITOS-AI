"""Offline comparison of ATM +/-2 or +/-5 frozen contracts at confirmed replay entry/exit.

No orders, fetching, or policy approval. Option minute OPEN is a pricing proxy.
A contract manifest must identify the historical nearest expiry and exact
contracts; without it every trade is retained as incomplete in coverage.
"""
from __future__ import annotations
import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from market_lab.historical_option_ohlc_adapter_v1 import choose_option_ohlc_session

ROLES = (-2, -1, 0, 1, 2)
STRATEGY = 'HILEGA_V2_ALIGNMENT_DUAL_EXIT'
REPLAY_MODEL = 'HILEGA_V2_ALIGNMENT_DUAL_EXIT_REPLAY_V1'


def minute(value, lag):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError('STRATEGY_TIMESTAMP_MUST_HAVE_TIMEZONE')
    return stamp.replace(second=0, microsecond=0) + timedelta(minutes=lag + int(bool(stamp.second or stamp.microsecond)))


def roles_for(wings):
    if wings not in (2, 5):raise ValueError('WINGS_MUST_BE_2_OR_5')
    return tuple(range(-wings,wings+1))


def incomplete_trade(day, trade, index, issue, *, wings=2):
    return [dict(session_date=day, trade_index=index, trade_id=trade.get('trade_id'),
                 direction=trade['direction'], role=role, status='INCOMPLETE', issue=issue,
                 strategy_entry_time=trade['entry_time'], strategy_exit_time=trade['exit_time']) for role in roles_for(wings)]


def validate_frozen(frozen, trade, day, *, wings=2):
    if frozen.get('strategy_entry_time') != trade['entry_time']:
        raise ValueError('MANIFEST_ENTRY_TIME_MISMATCH')
    if frozen.get('expiry') < day or frozen.get('nearest_expiry_verified') is not True:
        raise ValueError('NEAREST_EXPIRY_NOT_VERIFIED')
    side = 'CE' if trade['direction'] == 'BULLISH' else 'PE'
    contracts = frozen['contracts']
    if len(contracts) != len(roles_for(wings)) or {r['role'] for r in contracts} != set(roles_for(wings)):
        raise ValueError('EXACT_CANDIDATE_MANIFEST_REQUIRED')
    if len({r['instrument_key'] for r in contracts}) != 5:
        raise ValueError('DUPLICATE_MANIFEST_CONTRACT')
    atm = float(frozen['atm'])
    step = float(frozen['strike_interval'])
    # Same tie-to-lower ATM rule as the worker. The manifest uses historical
    # confirmed-entry spot, explicitly distinct from a delayed dispatch spot.
    entry_spot = float(trade['entry_price'])
    if step != 50 or atm != min((atm-step, atm, atm+step), key=lambda x: (abs(x-entry_spot), x)):
        raise ValueError('MANIFEST_ATM_MISMATCH')
    for r in contracts:
        if (r['option_type'] != side or r['expiry'] != frozen['expiry']
                or float(r['strike']) != atm + r['role'] * step
                or type(r['lot_size']) is not int or r['lot_size'] <= 0):
            raise ValueError('MANIFEST_CONTRACT_MISMATCH')
    return contracts


def compare_trade(trade, session, *, lag_minutes, trade_index, frozen,
                  round_trip_cost_rupees, slippage_points_per_side, wings=2):
    if trade['direction'] not in {'BULLISH', 'BEARISH'}:
        raise ValueError('UNKNOWN_DIRECTION')
    contracts = validate_frozen(frozen, trade, session.session_date, wings=wings)
    if session.expiry != frozen['expiry']:
        raise ValueError('CACHE_EXPIRY_MISMATCH')
    entry_at = minute(trade['entry_time'], lag_minutes)
    exit_at = minute(trade['exit_time'], lag_minutes)
    series = defaultdict(dict)
    duplicates = set()
    for c in session.rows:
        if c.expiry != frozen['expiry'] or c.session_date != session.session_date:
            continue
        key = (c.instrument_key, c.side, float(c.strike))
        if c.timestamp in series[key]:
            duplicates.add((key, c.timestamp))
        series[key][c.timestamp] = c
    results = []
    for contract in sorted(contracts, key=lambda r: r['role']):
        base = dict(session_date=session.session_date, trade_index=trade_index, trade_id=trade.get('trade_id'),
                    direction=trade['direction'], **contract,
                    strategy_entry_time=trade['entry_time'], strategy_exit_time=trade['exit_time'],
                    strategy_exit_reason=trade.get('exit_reason'), entry_spot=trade['entry_price'],
                    atm=frozen['atm'], universe_basis='FROZEN_CONFIRMED_ENTRY_NEAREST_EXPIRY',
                    research_entry_time=entry_at.isoformat(), research_exit_time=exit_at.isoformat())
        key = (contract['instrument_key'], contract['option_type'], float(contract['strike']))
        candles = series[key]
        expected = [entry_at + timedelta(minutes=n) for n in range(int((exit_at-entry_at).total_seconds()//60)+1)]
        issue = None
        if exit_at <= entry_at:
            issue = 'NONPOSITIVE_HOLDING_PERIOD'
        elif any(ts not in candles for ts in expected):
            issue = 'MISSING_EXACT_CONTRACT_MINUTE'
        elif any((key, ts) in duplicates for ts in expected):
            issue = 'DUPLICATE_OPTION_MINUTE'
        elif any(not all(math.isfinite(float(v)) for v in (candles[ts].open, candles[ts].high, candles[ts].low, candles[ts].close))
                 or not 0 < candles[ts].low <= min(candles[ts].open, candles[ts].close)
                 or max(candles[ts].open, candles[ts].close) > candles[ts].high for ts in expected):
            issue = 'INVALID_OPTION_PRICE'
        if issue:
            results.append(dict(base, status='INCOMPLETE', issue=issue))
            continue
        entry, exit_row = candles[entry_at], candles[exit_at]
        window = [candles[ts] for ts in expected[:-1]]
        points = float(exit_row.open-entry.open)
        quantity = contract['lot_size']
        costs = round_trip_cost_rupees + 2 * slippage_points_per_side * quantity
        net = points * quantity - costs
        results.append(dict(base, status='AVAILABLE', issue=None,
                            entry_open=entry.open, exit_open=exit_row.open, quantity=quantity,
                            gross_points=points, gross_rupees=points*quantity,
                            gross_return_pct=100*points/entry.open, scenario_cost_rupees=costs,
                            net_rupees=net, net_points=net/quantity,
                            net_return_pct=100*net/(entry.open*quantity),
                            mfe_points=max(0.0, max(c.high for c in window)-entry.open),
                            mae_points=min(0.0, min(c.low for c in window)-entry.open),
                            entry_volume=entry.volume, exit_volume=exit_row.volume))
    return results


def summarize(rows, *, train_through='2026-07-13', wings=2):
    grouped, complete_roles = defaultdict(list), defaultdict(set)
    for r in rows:
        if r['status'] == 'AVAILABLE':
            complete_roles[(r['session_date'], r['trade_index'])].add(r['role'])
        split = 'TRAIN' if r['session_date'] <= train_through else 'VALIDATION'
        grouped[(split, r['direction'], r['role'])].append(r)
    common_keys = {key for key, roles in complete_roles.items() if roles == set(roles_for(wings))}
    out = []
    for (split, direction, role), group in sorted(grouped.items()):
        available = [r for r in group if r['status'] == 'AVAILABLE']
        common = [r for r in available if (r['session_date'], r['trade_index']) in common_keys]
        def mean(field, values):
            return sum(r[field] for r in values)/len(values) if values else None
        out.append(dict(split=split, direction=direction, role=role, expected_trades=len(group),
                        complete=len(available), coverage_pct=100*len(available)/len(group),
                        incomplete_reasons=dict(Counter(r['issue'] for r in group if r['status'] != 'AVAILABLE')),
                        common_five_complete_trades=len(common) if wings==2 else None,
                        common_complete_trades=len(common), expected_roles=list(roles_for(wings)), common_coverage_pct=100*len(common)/len(group),
                        available_mean_gross_points=mean('gross_points', available),
                        common_mean_gross_points=mean('gross_points', common),
                        common_mean_net_rupees=mean('net_rupees', common),
                        common_mean_net_return_pct=mean('net_return_pct', common),
                        common_mean_mae_points=mean('mae_points', common),
                        common_worst_mae_points=min((r['mae_points'] for r in common), default=None),
                        common_mean_mfe_points=mean('mfe_points', common),
                        common_net_wins=sum(r['net_rupees'] > 0 for r in common),
                        common_net_losses=sum(r['net_rupees'] < 0 for r in common)))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replay-root', type=Path, default=Path('data/historical-evidence/hilega-v2-alignment-dual-exit-v1'))
    p.add_argument('--data-root', type=Path, default=Path('data'))
    p.add_argument('--contract-manifest', type=Path)
    p.add_argument('--wings',type=int,default=2,choices=(2,5))
    p.add_argument('--lag-minutes', type=int, default=1, choices=(0, 1))
    p.add_argument('--from-date', default='2026-04-15')
    p.add_argument('--through-date', default='2026-10-13')
    p.add_argument('--train-through', default='2026-07-13')
    p.add_argument('--expected-version', default='five-minute-setup-1.2.0-pending-switch')
    p.add_argument('--round-trip-cost-rupees', type=float, required=True)
    p.add_argument('--slippage-points-per-side', type=float, required=True)
    args = p.parse_args()
    if any(not math.isfinite(x) or x < 0 for x in (args.round_trip_cost_rupees, args.slippage_points_per_side)):
        p.error('Cost assumptions must be finite and nonnegative')
    manifest = json.loads(args.contract_manifest.read_text()) if args.contract_manifest else {}
    paths = [path for path in sorted(args.replay_root.glob('????-??-??.json')) if args.from_date <= path.stem <= args.through_date]
    if not paths:
        p.error('No replay files in requested range; refusing an empty successful report')
    rows, days = [], []
    for path in paths:
        day, replay = path.stem, json.loads(path.read_text())
        if replay.get('model') != REPLAY_MODEL or replay.get('strategy_id') != REPLAY_MODEL or replay.get('session_date') != day:
            raise ValueError(f'REPLAY_IDENTITY_MISMATCH:{path}')
        if replay.get('strategy_version') != args.expected_version:
            raise ValueError(f'REPLAY_VERSION_MISMATCH:{path}')
        trades = replay.get('trades') or []
        days.append(dict(session_date=day, expected_trades=len(trades)))
        for index, trade in enumerate(trades, 1):
            frozen = manifest.get(day, {}).get(str(index))
            if not frozen:
                rows.extend(incomplete_trade(day, trade, index, 'FROZEN_CONTRACT_MANIFEST_MISSING', wings=args.wings))
                continue
            try:
                validate_frozen(frozen, trade, day, wings=args.wings)
                session = choose_option_ohlc_session(day, expected_expiry=frozen['expiry'], data_root=args.data_root)
                result = compare_trade(trade, session, lag_minutes=args.lag_minutes, trade_index=index,
                                       frozen=frozen, round_trip_cost_rupees=args.round_trip_cost_rupees,
                                       slippage_points_per_side=args.slippage_points_per_side, wings=args.wings)
            except Exception as exc:
                result = incomplete_trade(day, trade, index, 'CONTRACT_OR_CACHE_UNAVAILABLE:'+type(exc).__name__, wings=args.wings)
            rows.extend(result)
    print(json.dumps(dict(model='HILEGA_STRIKE_COMPARISON_RESEARCH_V3', strategy_id=STRATEGY,
                          selection_approved=False, order_enabled=False,
                          wings=args.wings, candidate_count=len(roles_for(args.wings)), expected_strategy_version=args.expected_version, train_through=args.train_through,
                          price_semantics=f'EXACT_MINUTE_OPEN_{args.lag_minutes}M_LAG_NOT_FILL',
                          cost_assumptions=dict(round_trip_cost_rupees=args.round_trip_cost_rupees,
                                                slippage_points_per_side=args.slippage_points_per_side),
                          warning='Scenario net prices exclude any costs not included in supplied assumptions. No fresh untouched holdout is claimed. Missing replay dates are not exchange-calendar coverage.',
                          days=days, expected_trade_count=sum(d['expected_trades'] for d in days),
                          summary=summarize(rows, train_through=args.train_through, wings=args.wings), legs=rows), indent=2))


if __name__ == '__main__':
    main()
