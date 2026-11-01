from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from unittest.mock import Mock, patch

import pytest

import fixture_cycle_api as api
from fixture_cycle_history import RETIREMENTS
from fixture_reference_retirement_candidate import ACTIVE
from test_fixture_third_retirement_candidate import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle,
    closed, history, reentry, second, ready, position, completed,
    third, third_ready, third_position, third_completed,
    retire as retire_legacy,
)
from test_hilega_application_preparation_v1 import append, BULL
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign

BEAR = 'ENTRY_BEARISH_ROUTE_B_STRUCTURAL'


def resign(row):
    row.pop('signature', None)
    row['signature'] = sign(row, PIN)
    return row


@pytest.fixture
def cycle_base(third_completed):
    position, snapshot, _ = third_completed
    retire_legacy(third_completed)
    case = position['case']
    return dict(
        setup=case['setup'], mod=case['mod'], at=position['now'],
        health_at=case['now'], account=deepcopy(snapshot),
        cash=deepcopy(case['captures']['cash']),
        market=deepcopy(case['captures']['market']))


def shifted(value, delta):
    if isinstance(value, dict):
        return {k: shifted(v, delta) for k, v in value.items()}
    if isinstance(value, list):
        return [shifted(v, delta) for v in value]
    if isinstance(value, str):
        try:
            at = datetime.fromisoformat(value)
            if at.tzinfo is not None:
                return (at+delta).isoformat()
        except ValueError:
            pass
    return value


def market_capture(state, now):
    value = deepcopy(state['market'])
    value.update(started_at=now.isoformat(), completed_at=now.isoformat(),
                 session_date=now.date().isoformat())
    for quote in value['quotes'].values():
        for field in ('timestamp', 'last_trade_time'):
            if field in quote:
                quote[field] = (int(now.timestamp()*1000)
                                if isinstance(quote[field], (int, float))
                                else now.isoformat())
    return resign(value)


def current_capture(state, now):
    snapshot = deepcopy(state['account'])
    old_ids = {o['order_id'] for o in snapshot['orders']}
    requests = {r['order_id']: r for r in state['setup']['execution'].requests()
                if r.get('order_id')}
    transport = state['mod'].FixtureTransport(state['setup']['execution'])
    for order in transport.orders():
        oid = order['order_id']
        if oid in old_ids:
            continue
        request = requests[oid]
        snapshot['orders'].append(dict(
            order_id=oid, instrument=order['instrument'], product=order['product'],
            side=order['side'], quantity=order['quantity'], filled=order['filled'],
            pending=(order['quantity']-order['filled']
                     if order['status'] in {'OPEN', 'PARTIAL'} else 0),
            status=order['status'], source_status=order['status'].lower(),
            placed_at=request['signal_at']))
        if order['filled']:
            snapshot['trades'].append(dict(
                order_id=oid, trade_id='cycle-fill-'+oid,
                instrument=order['instrument'], product=order['product'],
                side=order['side'], quantity=order['filled'],
                price=str(request['draft']['body']['price']), filled_at=now.isoformat()))
    quantities = {(p['instrument'], p['product']): 0 for p in snapshot['positions']}
    for trade in snapshot['trades']:
        key = trade['instrument'], trade['product']
        quantities[key] = quantities.get(key, 0) + (
            trade['quantity'] if trade['side'] == 'BUY' else -trade['quantity'])
    snapshot['positions'] = [dict(instrument=k[0], product=k[1], quantity=q)
                             for k, q in quantities.items()]
    snapshot.update(generated_at=now.isoformat(), completed_at=now.isoformat(),
                    session_date=now.date().isoformat(),
                    snapshot_id='cycle-'+str(len(snapshot['orders']))+'-'+now.isoformat())
    return resign(snapshot)


def prepare_next(state, *, direction='BULLISH', checkpoint=lambda stage: None):
    setup = state['setup']
    now = state['at']+timedelta(minutes=5)
    setup['e']['clock'][0] = now
    account = deepcopy(state['account'])
    account.update(generated_at=now.isoformat(), completed_at=now.isoformat(),
                   session_date=now.date().isoformat(), snapshot_id='entry-'+now.isoformat())
    resign(account)
    cash = deepcopy(state['cash'])
    cash.update(started_at=now.isoformat(), completed_at=now.isoformat(),
                session_date=now.date().isoformat(), snapshot_id='cash-'+now.isoformat())
    if 'generated_at' in cash:
        cash['generated_at'] = now.isoformat()
    # Cash diagnostics retain their validated schema; only account rows are copied.
    for key in ('orders', 'trades', 'positions'):
        cash[key] = deepcopy(account[key])
    resign(cash)
    captures = dict(account=account, cash=cash, market=market_capture(state, now))
    with setup['e']['store'].db() as db:
        control = json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        control.update(mode='ARMED', version=control['version']+1, reconciled=True,
                       resumed_at=(now-timedelta(seconds=1)).isoformat(),
                       last_reconciled_at=now.isoformat())
        db.execute('UPDATE control SET data=? WHERE id=1', (json.dumps(control),))
        health = shifted(json.loads(db.execute(
            'SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0]),
            now-state['health_at'])
        db.execute('UPDATE sim_bridge_health SET data=? WHERE id=1', (json.dumps(health),))
    state['health_at'] = now
    append(setup['e']['path'], [BULL if direction == 'BULLISH' else BEAR], at=now.isoformat())
    sequence = len(setup['e']['path'].read_text().splitlines())
    args = dict(
        journal=setup['e']['path'], sequence=sequence,
        account_capture=captures['account'], cash_capture=captures['cash'],
        market_bundle=captures['market'], expected_version=control['version'],
        bridge_run_id=health['run_id'], fee_buffer_paise=10000,
        clock=lambda: now)
    result = api.prepare(setup['e']['store'], setup['execution'].path, PIN,
                         checkpoint=checkpoint, **args)
    return dict(state=state, now=now, key=result['request_id'], captures=captures,
                prepare_args=args, preparation=result)


def buy(case, *, provider=None, clock=None, **kwargs):
    state = case['state']
    return api.buy(
        state['setup']['e']['store'], state['setup']['execution'], PIN,
        adapter_module=state['mod'], request_id=case['key'],
        capture_provider=provider if provider is not None else (
            lambda: deepcopy(case['captures'])),
        clock=clock if clock is not None else (lambda: case['now']), **kwargs)


def filled_entry(case):
    buy(case)
    state = case['state']
    parent = next(r for r in state['setup']['execution'].requests()
                  if r['request_id'] == case['key'])
    state['mod'].FixtureTransport(state['setup']['execution']).fill(
        parent['order_id'], parent['draft']['body']['quantity'])
    now = case['now']+timedelta(minutes=5)
    state['setup']['e']['clock'][0] = now
    name = ('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'
            if parent['direction'] == 'BULLISH'
            else 'STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21')
    path = state['setup']['e']['path']
    append(path, [name], at=now.isoformat())
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    last = rows[-1]
    last['payload']['event_details'][0]['entry_time'] = parent['signal_at']
    last.pop('record_hash')
    last['record_hash'] = hashlib.sha256(json.dumps(
        last, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        default=str).encode()).hexdigest()
    path.write_text('\n'.join(json.dumps(row) for row in rows)+'\n')
    return dict(case=case, now=now, sequence=len(rows))


def sell(exit_case, *, provider=None, clock=None, **kwargs):
    case = exit_case['case']
    state = case['state']
    return api.sell(
        state['setup']['e']['store'], state['setup']['execution'], PIN,
        adapter_module=state['mod'], entry_id=case['key'],
        journal=state['setup']['e']['path'], sequence=exit_case['sequence'],
        capture_provider=provider if provider is not None else (lambda: dict(
            account=current_capture(state, exit_case['now']),
            market=market_capture(state, exit_case['now']))),
        clock=clock if clock is not None else (lambda: exit_case['now']), **kwargs)


def closed_cycle(state, *, direction='BULLISH'):
    case = prepare_next(state, direction=direction)
    exit_case = filled_entry(case)
    sent = sell(exit_case)
    request = next(r for r in state['setup']['execution'].requests()
                   if r['request_id'] == sent['exit_id'])
    state['mod'].FixtureTransport(state['setup']['execution']).fill(
        request['order_id'], request['draft']['body']['quantity'])
    snapshot = current_capture(state, exit_case['now'])
    closeout = api.closeout(
        state['setup']['e']['store'], state['setup']['execution'], PIN,
        entry_id=case['key'], journal=state['setup']['e']['path'],
        sequence=exit_case['sequence'], capture_provider=lambda: deepcopy(snapshot),
        clock=lambda: exit_case['now'])
    return dict(case=case, exit_case=exit_case, snapshot=snapshot, closeout=closeout)


def retire(closed, *, checkpoint=lambda stage: None):
    case = closed['case']
    state = case['state']
    result = api.retire(
        state['setup']['e']['store'], state['setup']['execution'].path,
        deepcopy(closed['snapshot']), PIN, entry_id=case['key'],
        clock=lambda: closed['exit_case']['now'], checkpoint=checkpoint)
    state['account'] = deepcopy(closed['snapshot'])
    state['at'] = closed['exit_case']['now']
    return result


def current_history(state):
    with state['setup']['e']['store'].db() as db:
        return api.history(db, PIN)[0]


def test_same_api_completes_fourth_cycle(cycle_base):
    state = cycle_base
    assert current_history(state)['cycle_count'] == 3
    closed = closed_cycle(state)
    result = retire(closed)
    view = current_history(state)
    assert view['cycle_count'] == 4
    assert len(view['snapshot']['orders']) == 8
    assert all(p['quantity'] == 0 for p in view['snapshot']['positions'])
    assert result['next_entry_admission_assessed'] is False
    assert result['production_execution_enabled'] is False


def test_same_api_completes_ten_total_cycles(cycle_base):
    state = cycle_base
    for index in range(4, 11):
        closed = closed_cycle(state, direction='BULLISH' if index % 2 else 'BEARISH')
        retire(closed)
        view = current_history(state)
        assert view['cycle_count'] == index
        assert len(view['retired_entry_ids']) == len(set(view['retired_entry_ids'])) == index
        assert len(view['snapshot']['orders']) == 2*index
        assert len({o['order_id'] for o in view['snapshot']['orders']}) == 2*index
        assert not any(p['quantity'] for p in view['snapshot']['positions'])
    with state['setup']['e']['store'].db() as db:
        assert db.execute('SELECT COUNT(*) FROM '+RETIREMENTS).fetchone()[0] == 7
        for table in ACTIVE:
            assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 0


def test_generic_buy_delayed_recovery_does_not_capture_or_send(cycle_base):
    case = prepare_next(cycle_base)
    buy(case)
    provider = Mock(side_effect=AssertionError('No recovery capture'))
    with patch.object(cycle_base['mod'].FixtureTransport, 'send',
                      side_effect=AssertionError('No repeat BUY')):
        result = buy(case, provider=provider, clock=lambda: case['now']+timedelta(hours=2))
    assert result['recovery_only'] is True
    provider.assert_not_called()


def test_generic_lost_buy_stays_unknown_and_retains_hold(cycle_base):
    case = prepare_next(cycle_base)
    assert buy(case, timeout_after=True)['adapter_result']['state'] == 'UNKNOWN'
    provider = Mock(side_effect=AssertionError('No uncertain capture'))
    with patch.object(cycle_base['mod'].FixtureTransport, 'send',
                      side_effect=AssertionError('No uncertain BUY retry')):
        assert buy(case, provider=provider)['recovery_only'] is True
    provider.assert_not_called()
    with cycle_base['setup']['e']['store'].db() as db:
        assert db.execute('SELECT 1 FROM preparation_cash_reservations WHERE id=?',
                          (case['key'],)).fetchone() is not None
    assert current_history(cycle_base)['cycle_count'] == 3


def test_generic_lost_sell_never_resubmits(cycle_base):
    exit_case = filled_entry(prepare_next(cycle_base))
    first = sell(exit_case, timeout_after=True)
    assert first['adapter_result']['state'] == 'UNKNOWN'
    provider = Mock(side_effect=AssertionError('No uncertain exit capture'))
    with patch.object(cycle_base['mod'].FixtureTransport, 'send',
                      side_effect=AssertionError('No uncertain SELL retry')):
        recovered = sell(exit_case, provider=provider)
    assert recovered['exit_state'] == 'UNKNOWN'
    provider.assert_not_called()


def test_generic_concurrent_buy_records_one_attempt(cycle_base):
    case = prepare_next(cycle_base)
    provider = Mock(side_effect=lambda: deepcopy(case['captures']))
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(buy, case, provider=provider) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert sorted(r['recovery_only'] for r in results) == [False, True]
    assert provider.call_count == 1
    with cycle_base['setup']['execution'].tx() as db:
        assert db.execute('SELECT COUNT(*) FROM attempts WHERE request_id=?',
                          (case['key'],)).fetchone()[0] == 1


@pytest.mark.parametrize('stage', [
    'AFTER_CYCLE_RETIREMENT_SEAL', 'AFTER_CYCLE_REFERENCES_RETIRED',
    'BEFORE_CYCLE_RETIREMENT_COMMIT',
])
def test_generic_retirement_rollback_preserves_chain(cycle_base, stage):
    closed = closed_cycle(cycle_base)
    def interrupt(current):
        if current == stage:
            raise RuntimeError('synthetic reusable retirement interruption')
    with pytest.raises(RuntimeError, match='synthetic reusable retirement'):
        retire(closed, checkpoint=interrupt)
    assert current_history(cycle_base)['cycle_count'] == 3
    with cycle_base['setup']['e']['store'].db() as db:
        for table in ACTIVE:
            assert db.execute('SELECT 1 FROM '+table+' WHERE id=?',
                              (closed['case']['key'],)).fetchone() is not None
    retire(closed)
    assert current_history(cycle_base)['cycle_count'] == 4


def test_generic_tampered_predecessor_blocks_chain(cycle_base):
    closed = closed_cycle(cycle_base)
    retire(closed)
    with cycle_base['setup']['e']['store'].db() as db:
        key, raw = db.execute('SELECT id,data FROM '+RETIREMENTS).fetchone()
        row = json.loads(raw)
        row['predecessor_fingerprint'] = '0'*64
        db.execute('UPDATE '+RETIREMENTS+' SET data=? WHERE id=?', (json.dumps(row), key))
    with pytest.raises(ValueError, match='CYCLE_RETIREMENT_SIGNATURE_INVALID'):
        current_history(cycle_base)


def test_generic_current_cash_shortfall_blocks_buy(cycle_base):
    case = prepare_next(cycle_base)
    captures = deepcopy(case['captures'])
    for field in ('funds_before', 'funds_after'):
        captures['cash'][field]['cash_available_to_trade'] = '1'
    resign(captures['cash'])
    with pytest.raises(ValueError, match='CURRENT_REPEAT_CASH_BLOCKED'):
        buy(case, provider=lambda: captures)
    assert len(cycle_base['mod'].FixtureTransport(cycle_base['setup']['execution']).orders()) == 6


@pytest.mark.parametrize('operation', ['prepare', 'buy', 'sell', 'closeout', 'retire'])
def test_generic_live_scope_rejected_before_files(operation):
    pin = dict(PIN, scope='UPSTOX:'+'a'*64)
    def unavailable():
        raise AssertionError('Capture or clock accessed')
    with pytest.raises(ValueError):
        if operation == 'prepare':
            api.prepare(None, '/must-not-open', pin, journal='/must-not-open', sequence=1,
                        account_capture={}, cash_capture={}, market_bundle={},
                        expected_version=0, bridge_run_id='blocked', fee_buffer_paise=10000,
                        clock=unavailable)
        elif operation == 'buy':
            api.buy(None, None, pin, adapter_module=None, request_id='blocked',
                    capture_provider=unavailable, clock=unavailable)
        elif operation == 'sell':
            api.sell(None, None, pin, adapter_module=None, entry_id='blocked',
                     journal='/must-not-open', sequence=1,
                     capture_provider=unavailable, clock=unavailable)
        elif operation == 'closeout':
            api.closeout(None, None, pin, entry_id='blocked', journal='/must-not-open',
                         sequence=1, capture_provider=unavailable, clock=unavailable)
        else:
            api.retire(None, '/must-not-open', {}, pin, entry_id='blocked', clock=unavailable)
