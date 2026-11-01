from copy import deepcopy
from datetime import timedelta
import json

import pytest

from fixture_third_retirement_candidate import retire_third_fixture, TABLE
from fixture_third_exit_candidate import CLOSEOUTS
from fixture_reference_retirement_candidate import ACTIVE
from test_fixture_third_exit_candidate import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle,
    closed, history, reentry, second, ready, position, completed,
    third, third_ready, third_position,
    close_position, account_snapshot, run_closeout,
)
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign


@pytest.fixture
def third_completed(third_position):
    close_position(third_position)
    snapshot = account_snapshot(third_position)
    result = run_closeout(third_position, snapshot)
    return third_position, snapshot, result


def retire(case, **kwargs):
    position, snapshot, _ = case
    setup = position['case']['setup']
    return retire_third_fixture(
        setup['e']['store'], setup['execution'].path, deepcopy(snapshot), PIN,
        entry_id=position['case']['key'], clock=lambda: position['now'], **kwargs)


def active_rows(case):
    position, _, _ = case
    key = position['case']['key']
    with position['case']['setup']['e']['store'].db() as db:
        return {table: db.execute('SELECT data FROM '+table+' WHERE id=?',
                                  (key,)).fetchone() for table in ACTIVE}


def assert_retirement_absent(case):
    position, _, _ = case
    with position['case']['setup']['e']['store'].db() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE,)).fetchone()
        if exists:
            assert db.execute('SELECT COUNT(*) FROM '+TABLE).fetchone()[0] == 0


def test_third_retirement_preserves_three_cycles_and_broker_evidence(third_completed):
    position, _, _ = third_completed
    setup = position['case']['setup']
    application_tables = [
        'fixture_closed_lifecycle_history', 'fixture_repeat_position_closeouts',
        'fixture_repeat_reference_retirements', CLOSEOUTS,
        'fixture_third_entry_admissions', 'preparation_consumed',
    ]
    with setup['e']['store'].db() as db:
        before_app = {t: db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall()
                      for t in application_tables}
    broker_tables = ['requests', 'attempts', 'receipts', 'events', 'fixture_orders']
    with setup['execution'].tx() as db:
        before_broker = {t: db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall()
                         for t in broker_tables}
    assert len(position['transport'].orders()) == 6
    assert all(value is not None for value in active_rows(third_completed).values())
    result = retire(third_completed)
    assert result['status'] == 'FIXTURE_THIRD_REFERENCES_RETIRED'
    assert result['reservation_release_permission'] is False
    assert result['fourth_entry_admission_assessed'] is False
    assert result['production_execution_enabled'] is False
    assert all(value is None for value in active_rows(third_completed).values())
    with setup['e']['store'].db() as db:
        for table, rows in before_app.items():
            assert db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall() == rows
        assert db.execute('SELECT COUNT(*) FROM '+TABLE).fetchone()[0] == 1
    with setup['execution'].tx() as db:
        for table, rows in before_broker.items():
            assert db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall() == rows


def test_third_retirement_replay_is_historical_only(third_completed):
    retire(third_completed)
    result = retire(third_completed)
    assert result['status'] == 'THIRD_RETIREMENT_HISTORICAL_REPLAY'
    assert result['database_modified'] is False
    assert result['fourth_entry_admission_assessed'] is False
    position, _, _ = third_completed
    with position['case']['setup']['e']['store'].db() as db:
        assert db.execute('SELECT COUNT(*) FROM '+TABLE).fetchone()[0] == 1


@pytest.mark.parametrize('stage', [
    'AFTER_THIRD_RETIREMENT_SEAL', 'AFTER_THIRD_REFERENCES_RETIRED',
    'BEFORE_THIRD_RETIREMENT_COMMIT',
])
def test_third_retirement_interruption_restores_references(third_completed, stage):
    before = active_rows(third_completed)
    def interrupt(current):
        if current == stage:
            raise RuntimeError('synthetic third retirement interruption')
    with pytest.raises(RuntimeError, match='synthetic third retirement'):
        retire(third_completed, checkpoint=interrupt)
    assert active_rows(third_completed) == before
    assert_retirement_absent(third_completed)
    assert retire(third_completed)['status'] == 'FIXTURE_THIRD_REFERENCES_RETIRED'


def test_third_retirement_expiry_before_commit_rolls_back(third_completed):
    position, _, _ = third_completed
    before = active_rows(third_completed)
    def expire(stage):
        if stage == 'BEFORE_THIRD_RETIREMENT_COMMIT':
            position['now'] += timedelta(seconds=61)
    with pytest.raises(ValueError):
        retire(third_completed, checkpoint=expire)
    assert active_rows(third_completed) == before
    assert_retirement_absent(third_completed)


def test_third_retirement_stale_capture_blocks(third_completed):
    position, _, _ = third_completed
    before = active_rows(third_completed)
    position['now'] += timedelta(seconds=61)
    with pytest.raises(ValueError):
        retire(third_completed)
    assert active_rows(third_completed) == before
    assert_retirement_absent(third_completed)


def test_third_retirement_tampered_replay_blocks(third_completed):
    retire(third_completed)
    position, _, _ = third_completed
    key = position['case']['key']
    with position['case']['setup']['e']['store'].db() as db:
        row = json.loads(db.execute('SELECT data FROM '+TABLE+' WHERE id=?',
                                    (key,)).fetchone()[0])
        row['reservation_release_permission'] = True
        db.execute('UPDATE '+TABLE+' SET data=? WHERE id=?', (json.dumps(row), key))
    with pytest.raises(ValueError, match='REPEAT_RETIREMENT_SIGNATURE_INVALID'):
        retire(third_completed)


def test_third_retirement_tampered_closeout_blocks(third_completed):
    position, _, _ = third_completed
    before = active_rows(third_completed)
    key = position['case']['key']
    with position['case']['setup']['e']['store'].db() as db:
        row = json.loads(db.execute('SELECT data FROM '+CLOSEOUTS+' WHERE id=?',
                                    (key,)).fetchone()[0])
        row['fees_complete'] = True
        db.execute('UPDATE '+CLOSEOUTS+' SET data=? WHERE id=?', (json.dumps(row), key))
    with pytest.raises(ValueError, match='REPEAT_CLOSEOUT_SIGNATURE_INVALID'):
        retire(third_completed)
    assert active_rows(third_completed) == before


def test_third_retirement_missing_zero_position_blocks(third_completed):
    _, snapshot, _ = third_completed
    before = active_rows(third_completed)
    snapshot['positions'] = []
    snapshot.pop('signature')
    snapshot['signature'] = sign(snapshot, PIN)
    with pytest.raises(ValueError, match='MISSING_POSITION_ROW_IS_NOT_FLAT'):
        retire(third_completed)
    assert active_rows(third_completed) == before
    assert_retirement_absent(third_completed)


def test_third_retirement_reappeared_reference_blocks_replay(third_completed):
    position, _, _ = third_completed
    key = position['case']['key']
    before = active_rows(third_completed)
    retire(third_completed)
    with position['case']['setup']['e']['store'].db() as db:
        db.execute('INSERT INTO preparation_plans VALUES(?,?)',
                   (key, before['preparation_plans'][0]))
    with pytest.raises(ValueError, match='RETIRED_REPEAT_REFERENCE_REAPPEARED'):
        retire(third_completed)


def test_third_retirement_live_scope_rejected_before_files():
    class UnavailableStore:
        @property
        def path(self):
            raise AssertionError('Live database path accessed')
    def unavailable():
        raise AssertionError('Live clock accessed')
    with pytest.raises(ValueError, match='FIXTURE_THIRD_RETIREMENT_ONLY'):
        retire_third_fixture(
            UnavailableStore(), '/must-not-open.sqlite', {},
            dict(PIN, scope='UPSTOX:'+'a'*64), entry_id='blocked', clock=unavailable)
