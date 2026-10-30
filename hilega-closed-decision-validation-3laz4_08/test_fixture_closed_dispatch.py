"""Synthetic app -> separate fixture decision DB."""
from copy import deepcopy
import sqlite3

import pytest

import fixture_closed_dispatch as integration
from test_hilega_application_preparation_v1 import env, process
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN


@pytest.fixture(autouse=True)
def fixture_scope(monkeypatch):
    monkeypatch.setitem(PIN, "scope", "FIXTURE:CLOSED-DISPATCH-INTEGRATION")


@pytest.fixture
def prepared(bound_env, tmp_path):
    e = bound_env
    process(e)
    return e, tmp_path / "closed-decisions.sqlite"


def invoke(db, e, **kwargs):
    return integration.record_fixture_decision(
        db, e["store"].path, e["adapter_store"].path, PIN,
        as_of=e["clock"][0].isoformat(), **kwargs,
    )


def contents(e):
    return e["store"].path.read_bytes(), e["adapter_store"].path.read_bytes()


def count(path):
    with sqlite3.connect(path) as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='closed_dispatch_decisions'"
        ).fetchone()
        return db.execute(
            "SELECT COUNT(*) FROM closed_dispatch_decisions"
        ).fetchone()[0] if exists else 0


def test_commit_and_replay_preserve_application(prepared):
    e, path = prepared
    before = contents(e)
    ids = []
    for expected_replay in (False, True):
        with sqlite3.connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            result = invoke(db, e)
            assert result["idempotent_replay"] is expected_replay
            assert result["orders_sent"] is False
            ids.append(result["decision_id"])
    assert ids[0] == ids[1]
    assert count(path) == 1
    assert contents(e) == before


@pytest.mark.parametrize("point", ["AFTER_REVIEW", "AFTER_RECORD_INSERT"])
def test_interruption_rolls_back_decision(prepared, point):
    e, path = prepared
    before = contents(e)

    class Interrupted(BaseException):
        pass

    def checkpoint(stage):
        if stage == point:
            raise Interrupted()

    with pytest.raises(Interrupted):
        with sqlite3.connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            invoke(db, e, checkpoint=checkpoint)
    assert count(path) == 0
    assert contents(e) == before


def test_changed_source_after_insert_rolls_back(prepared, monkeypatch):
    e, path = prepared
    before_bytes = contents(e)
    original_reader = integration.read_sources
    calls = []

    def reader(*args, **kwargs):
        source = original_reader(*args, **kwargs)
        calls.append(1)
        # This module's third read is after decision insertion.
        if len(calls) == 3:
            source = deepcopy(source)
            source["stop_state"] = [1, 0]
        return source

    monkeypatch.setattr(integration, "read_sources", reader)
    with pytest.raises(ValueError, match="^SOURCE_CHANGED_BEFORE_RETURN$"):
        with sqlite3.connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            invoke(db, e)
    assert len(calls) == 3
    assert count(path) == 0
    assert contents(e) == before_bytes