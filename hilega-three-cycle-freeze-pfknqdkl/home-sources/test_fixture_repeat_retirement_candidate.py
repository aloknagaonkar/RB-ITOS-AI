from copy import deepcopy
import json
import pytest

from fixture_repeat_retirement_candidate import (
    retire_repeat_fixture, TABLE,
)
from fixture_reference_retirement_candidate import ACTIVE
from test_fixture_repeat_exit_candidate import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle,
    closed, history, reentry, second, ready, position,
    close_position, account_snapshot, run_closeout,
)
from hilega_application_preparation_fixtures import PIN


@pytest.fixture
def completed(position):
    close_position(position)
    snapshot = account_snapshot(position)
    closeout = run_closeout(position, snapshot)
    return position, snapshot, closeout


def retire(completed, **kwargs):
    position, snapshot, _ = completed
    setup = position["case"]["setup"]
    return retire_repeat_fixture(
        setup["e"]["store"], setup["execution"].path,
        deepcopy(snapshot), PIN,
        entry_id=position["case"]["key"],
        clock=lambda: position["now"], **kwargs)


def test_retirement_preserves_broker_evidence(completed):
    position, _, _ = completed
    setup = position["case"]["setup"]
    requests = deepcopy(setup["execution"].requests())
    orders = deepcopy(position["transport"].orders())
    result = retire(completed)
    assert result["status"] == "FIXTURE_REPEAT_REFERENCES_RETIRED"
    assert result["reservation_release_permission"] is False
    assert result["third_entry_admission_assessed"] is False
    assert setup["execution"].requests() == requests
    assert position["transport"].orders() == orders
    key = position["case"]["key"]
    with setup["e"]["store"].db() as db:
        for table in ACTIVE:
            assert db.execute(
                "SELECT 1 FROM "+table+" WHERE id=?", (key,)
            ).fetchone() is None
        assert db.execute(
            "SELECT 1 FROM fixture_repeat_position_closeouts WHERE id=?",
            (key,)).fetchone() is not None
        assert db.execute(
            "SELECT COUNT(*) FROM "+TABLE
        ).fetchone()[0] == 1


def test_retirement_replay_is_idempotent(completed):
    retire(completed)
    replay = retire(completed)
    assert replay["status"] == "REPEAT_RETIREMENT_HISTORICAL_REPLAY"
    assert replay["database_modified"] is False
    position, _, _ = completed
    setup = position["case"]["setup"]
    with setup["e"]["store"].db() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM "+TABLE
        ).fetchone()[0] == 1


@pytest.mark.parametrize("stage", [
    "AFTER_REPEAT_RETIREMENT_SEAL",
    "AFTER_REPEAT_REFERENCES_RETIRED",
    "BEFORE_REPEAT_RETIREMENT_COMMIT",
])
def test_retirement_interruption_restores_references(completed, stage):
    position, _, _ = completed
    setup = position["case"]["setup"]
    key = position["case"]["key"]
    with setup["e"]["store"].db() as db:
        before = {
            table: db.execute(
                "SELECT data FROM "+table+" WHERE id=?", (key,)
            ).fetchone()[0]
            for table in ACTIVE
        }
    def interrupt(current):
        if current == stage:
            raise RuntimeError("synthetic retirement interruption")
    with pytest.raises(RuntimeError, match="synthetic retirement"):
        retire(completed, checkpoint=interrupt)
    with setup["e"]["store"].db() as db:
        for table, raw in before.items():
            assert db.execute(
                "SELECT data FROM "+table+" WHERE id=?", (key,)
            ).fetchone()[0] == raw
        exists = db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name=?", (TABLE,)
        ).fetchone()
        if exists:
            assert db.execute(
                "SELECT COUNT(*) FROM "+TABLE
            ).fetchone()[0] == 0
    assert retire(completed)["status"] == (
        "FIXTURE_REPEAT_REFERENCES_RETIRED")
