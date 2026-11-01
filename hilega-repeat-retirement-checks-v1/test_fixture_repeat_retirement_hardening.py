"""Additional fixture-only retirement checks; execute on the user's VM."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from fixture_repeat_retirement_candidate import retire_repeat_fixture, TABLE
from fixture_reference_retirement_candidate import ACTIVE
from fixture_repeat_exit_candidate import CLOSEOUTS
from test_fixture_repeat_retirement_candidate import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle,
    closed, history, reentry, second, ready, position, completed, retire,
)
from hilega_application_preparation_fixtures import PIN


def assert_references_retained(completed):
    position, _, _ = completed
    setup = position['case']['setup']
    key = position['case']['key']
    with setup['e']['store'].db() as db:
        for table in ACTIVE:
            assert db.execute(
                'SELECT 1 FROM '+table+' WHERE id=?', (key,)
            ).fetchone() is not None
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE,),
        ).fetchone()
        if exists:
            assert db.execute(
                'SELECT 1 FROM '+TABLE+' WHERE id=?', (key,)
            ).fetchone() is None


def test_expiry_before_commit_restores_references(completed):
    position, _, _ = completed
    before = deepcopy(position['transport'].orders())
    def expire(stage):
        if stage == 'BEFORE_REPEAT_RETIREMENT_COMMIT':
            position['now'] += timedelta(seconds=61)
    with pytest.raises(ValueError):
        retire(completed, checkpoint=expire)
    assert_references_retained(completed)
    assert position['transport'].orders() == before


def test_stale_capture_keeps_references(completed):
    position, _, _ = completed
    position['now'] += timedelta(seconds=61)
    with pytest.raises(ValueError):
        retire(completed)
    assert_references_retained(completed)


def test_tampered_retirement_replay_blocks(completed):
    retire(completed)
    position, _, _ = completed
    setup = position['case']['setup']
    key = position['case']['key']
    with setup['e']['store'].db() as db:
        row = json.loads(db.execute(
            'SELECT data FROM '+TABLE+' WHERE id=?', (key,)
        ).fetchone()[0])
        row['reservation_release_permission'] = True
        db.execute('UPDATE '+TABLE+' SET data=? WHERE id=?',
                   (json.dumps(row), key))
    with pytest.raises(ValueError, match='REPEAT_RETIREMENT_SIGNATURE_INVALID'):
        retire(completed)


def test_tampered_closeout_keeps_references(completed):
    position, _, _ = completed
    setup = position['case']['setup']
    key = position['case']['key']
    with setup['e']['store'].db() as db:
        row = json.loads(db.execute(
            'SELECT data FROM '+CLOSEOUTS+' WHERE id=?', (key,)
        ).fetchone()[0])
        row['reservation_release_permission'] = True
        db.execute('UPDATE '+CLOSEOUTS+' SET data=? WHERE id=?',
                   (json.dumps(row), key))
    with pytest.raises(ValueError, match='REPEAT_CLOSEOUT_SIGNATURE_INVALID'):
        retire(completed)
    assert_references_retained(completed)


def test_live_scope_rejected_before_database_access():
    class UnavailableStore:
        @property
        def path(self):
            raise AssertionError('Database path accessed for live scope')
        def lock(self):
            raise AssertionError('Database lock accessed for live scope')
    def unavailable_clock():
        raise AssertionError('Clock accessed for live scope')
    with pytest.raises(ValueError, match='FIXTURE_REPEAT_RETIREMENT_ONLY'):
        retire_repeat_fixture(
            UnavailableStore(), '/must-not-open.sqlite', {},
            dict(PIN, scope='UPSTOX:'+'a'*64),
            entry_id='blocked', clock=unavailable_clock,
        )
