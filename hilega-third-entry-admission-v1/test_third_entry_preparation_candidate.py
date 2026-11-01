from copy import deepcopy
from datetime import datetime, timedelta
import json
from unittest.mock import patch

import pytest

from third_entry_preparation_candidate import prepare_third_fixture
from third_entry_history_candidate import load_closed_history
from fixture_repeat_retirement_candidate import TABLE as RETIREMENTS
from fixture_reference_retirement_candidate import ACTIVE
from closed_history_baseline_candidate import TABLE as HISTORY
from test_fixture_repeat_retirement_candidate import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle,
    closed, history, reentry, second, ready, position, completed, retire,
)
from test_fixture_repeat_exit_candidate import market_snapshot
from test_hilega_application_preparation_v1 import append, BULL
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign

BEAR = 'ENTRY_BEARISH_ROUTE_B_STRUCTURAL'


def resign(row):
    row.pop('signature', None)
    row['signature'] = sign(row, PIN)


@pytest.fixture
def third(completed):
    position, final_account, _ = completed
    retire(completed)
    setup = position['case']['setup']
    now = position['now'] + timedelta(minutes=5)
    account = deepcopy(final_account)
    account.update(generated_at=now.isoformat(), completed_at=now.isoformat(),
                   session_date=now.date().isoformat(),
                   snapshot_id='synthetic-third-entry-account')
    resign(account)
    cash = deepcopy(position['case']['captures']['cash'])
    cash.update(started_at=now.isoformat(), completed_at=now.isoformat(),
                session_date=now.date().isoformat(),
                snapshot_id='synthetic-third-entry-cash')
    if 'generated_at' in cash:
        cash['generated_at'] = now.isoformat()
    for key in ('orders', 'trades', 'positions', 'diagnostics'):
        cash[key] = deepcopy(account[key])
    resign(cash)
    market_position = dict(position, now=now)
    market = market_snapshot(market_position)
    setup['e']['clock'][0] = now
    with setup['e']['store'].db() as db:
        control = json.loads(db.execute(
            'SELECT data FROM control WHERE id=1').fetchone()[0])
        control.update(mode='ARMED', version=control['version']+1,
                       reconciled=True,
                       resumed_at=(now-timedelta(seconds=1)).isoformat(),
                       last_reconciled_at=now.isoformat())
        db.execute('UPDATE control SET data=? WHERE id=1',
                   (json.dumps(control),))
        health = json.loads(db.execute(
            'SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])
        delta = now-setup['now']
        def shifted(value):
            if isinstance(value, dict):
                return {k: shifted(v) for k, v in value.items()}
            if isinstance(value, list):
                return [shifted(v) for v in value]
            if isinstance(value, str):
                try:
                    at = datetime.fromisoformat(value)
                    if at.tzinfo is not None:
                        return (at+delta).isoformat()
                except ValueError:
                    pass
            return value
        health = shifted(health)
        db.execute('UPDATE sim_bridge_health SET data=? WHERE id=1',
                   (json.dumps(health),))
    return dict(setup=setup, position=position, now=now,
                account=account, cash=cash, market=market,
                version=control['version'], run_id=health['run_id'],
                sequence=None, old_requests=deepcopy(setup['execution'].requests()))


def run(case, *, bearish=False, clock=None, checkpoint=lambda stage: None):
    setup = case['setup']
    if case['sequence'] is None:
        append(setup['e']['path'], [BEAR if bearish else BULL],
               at=case['now'].isoformat())
        case['sequence'] = len(setup['e']['path'].read_text().splitlines())
    return prepare_third_fixture(
        setup['e']['store'], setup['execution'].path, PIN,
        journal=setup['e']['path'], sequence=case['sequence'],
        account_capture=case['account'], cash_capture=case['cash'],
        market_bundle=case['market'], expected_version=case['version'],
        bridge_run_id=case['run_id'], fee_buffer_paise=10000,
        clock=clock or (lambda: case['now']), checkpoint=checkpoint)


def assert_no_third_admission(case):
    setup = case['setup']
    assert setup['execution'].requests() == case['old_requests']
    with setup['e']['store'].db() as db:
        for table in ACTIVE:
            assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 0


@pytest.mark.parametrize('bearish', [False, True])
def test_third_disabled_entry_preserves_both_cycles(third, bearish):
    setup = third['setup']
    with setup['e']['store'].db() as db:
        old_history = db.execute('SELECT id,data FROM '+HISTORY).fetchall()
        old_retirement = db.execute('SELECT id,data FROM '+RETIREMENTS).fetchall()
        baseline = load_closed_history(db, PIN)
        assert len(baseline) == 1
        assert len(baseline[0]['source']['requests']) == 4
        assert len(baseline[0]['snapshot']['orders']) == 4
    transport_class = third['position']['case']['mod'].FixtureTransport
    with patch.object(transport_class, 'send',
                      side_effect=AssertionError('Preparation must not submit')):
        result = run(third, bearish=bearish)
    assert result['status'] == 'FIXTURE_THIRD_ENTRY_PREPARED_DISABLED'
    assert result['direction'] == ('BEARISH' if bearish else 'BULLISH')
    assert result['budget_paise'] <= result['half_cash_cap_paise']
    assert result['orders_sent'] is False
    assert result['production_execution_enabled'] is False
    requests = setup['execution'].requests()
    assert len(requests) == 5
    for old in third['old_requests']:
        assert old in requests
    new = next(r for r in requests if r['request_id'] == result['request_id'])
    assert new['state'] == 'PREPARED' and new['order_id'] is None
    with setup['e']['store'].db() as db:
        assert db.execute('SELECT id,data FROM '+HISTORY).fetchall() == old_history
        assert db.execute('SELECT id,data FROM '+RETIREMENTS).fetchall() == old_retirement
        for table in ACTIVE:
            assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 1
        binding = json.loads(db.execute(
            'SELECT data FROM preparation_request_bindings WHERE id=?',
            (result['request_id'],)).fetchone()[0])
        assert binding['model'] == 'HILEGA_FIXTURE_THIRD_DISABLED_BINDING_V1'


def test_third_preparation_replay_is_idempotent(third):
    first = run(third)
    replay = run(third)
    assert replay['idempotent_replay'] is True
    assert len(third['setup']['execution'].requests()) == 5
    assert first['production_execution_enabled'] is False


@pytest.mark.parametrize('stage', [
    'AFTER_ACTIVE_REFERENCES', 'AFTER_DISABLED_REQUEST_INSERT',
    'BEFORE_REPEAT_COMMIT',
])
def test_third_preparation_rollback_restores_both_databases(third, stage):
    def interrupt(current):
        if current == stage:
            raise RuntimeError('synthetic third-entry interruption')
    with pytest.raises(RuntimeError, match='synthetic third-entry'):
        run(third, checkpoint=interrupt)
    assert_no_third_admission(third)
    assert third['setup']['e']['store'].control()['mode'] == 'ARMED'


def test_third_entry_uses_current_cash(third):
    for key in ('funds_before', 'funds_after'):
        third['cash'][key]['cash_available_to_trade'] = '1'
    resign(third['cash'])
    with pytest.raises(ValueError, match='REPEAT_ENTRY_CASH_BLOCKED'):
        run(third)
    assert_no_third_admission(third)


def test_third_entry_stale_account_blocks(third):
    old = third['now']-timedelta(seconds=31)
    third['account'].update(generated_at=old.isoformat(), completed_at=old.isoformat())
    resign(third['account'])
    with pytest.raises(ValueError):
        run(third)
    assert_no_third_admission(third)


def test_third_entry_tampered_retirement_blocks(third):
    with third['setup']['e']['store'].db() as db:
        key, raw = db.execute('SELECT id,data FROM '+RETIREMENTS).fetchone()
        row = json.loads(raw)
        row['local_reference_retired'] = False
        db.execute('UPDATE '+RETIREMENTS+' SET data=? WHERE id=?',
                   (json.dumps(row), key))
    with pytest.raises(ValueError, match='THIRD_RETIREMENT_SIGNATURE_INVALID'):
        run(third)
    assert_no_third_admission(third)


def test_third_entry_missing_retirement_blocks(third):
    with third['setup']['e']['store'].db() as db:
        db.execute('DELETE FROM '+RETIREMENTS)
    with pytest.raises(ValueError, match='EXACT_SECOND_RETIREMENT_REQUIRED'):
        run(third)
    assert_no_third_admission(third)


def test_third_entry_paused_controller_blocks(third):
    with third['setup']['e']['store'].db() as db:
        row = json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0])
        row['mode'] = 'PAUSED'
        db.execute('UPDATE control SET data=? WHERE id=1', (json.dumps(row),))
    with pytest.raises(ValueError, match='CONTROL_RESUME_OR_STOP'):
        run(third)
    assert_no_third_admission(third)


def test_third_entry_expiry_before_commit_rolls_back(third):
    times = iter([third['now'], third['now']+timedelta(seconds=61)])
    with pytest.raises(ValueError):
        run(third, clock=lambda: next(times))
    assert_no_third_admission(third)


def test_live_scope_rejected_before_files():
    with pytest.raises(ValueError, match='FIXTURE_THIRD_PREPARATION_ONLY'):
        prepare_third_fixture(
            None, '/must-not-open.sqlite', dict(PIN, scope='UPSTOX:'+'a'*64),
            journal='/must-not-open.jsonl', sequence=1,
            account_capture={}, cash_capture={}, market_bundle={},
            expected_version=0, bridge_run_id='blocked', fee_buffer_paise=10000,
            clock=lambda: (_ for _ in ()).throw(AssertionError('Clock accessed')))
