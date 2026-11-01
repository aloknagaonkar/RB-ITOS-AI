from datetime import datetime, timedelta
import json
import sqlite3

import pytest

from fixture_reference_retirement_candidate import (
    retire_fixture_references, ACTIVE, TABLE,
)
from closed_history_baseline_candidate import TABLE as HISTORY
from test_fixture_closeout_review import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle, closed,
)
from hilega_application_preparation_fixtures import PIN


def run(case, *, clock=None, checkpoint=lambda stage: None):
    lifecycle, data, sequence, fees = case
    e, mod, execution = lifecycle[0]
    source, snapshot, key, at = data
    return retire_fixture_references(
        e["store"], execution.path, snapshot, PIN,
        entry_id=key, journal=e["path"], exit_sequences=[sequence],
        clock=clock or (lambda: datetime.fromisoformat(at)),
        checkpoint=checkpoint,
    )


def counts(case):
    e = case[0][0][0]
    with sqlite3.connect(e["store"].path) as db:
        return {
            table: db.execute(
                "SELECT COUNT(*) FROM "+table).fetchone()[0]
            for table in ACTIVE
        }


def test_retirement_archives_and_preserves_broker_evidence(closed):
    e, mod, execution = closed[0][0]
    broker_before = execution.path.read_bytes()
    closed_before = e["adapter_store"].path.read_bytes()
    with sqlite3.connect(e["store"].path) as db:
        preserved = {
            name: db.execute("SELECT COUNT(*) FROM "+name).fetchone()[0]
            for name in (
                "preparation_evidence", "preparation_consumed",
                "preparation_events", "preparation_source",
            )
        }
    result = run(closed)
    assert result["status"] == "FIXTURE_LOCAL_REFERENCES_RETIRED"
    assert all(n == 0 for n in counts(closed).values())
    assert execution.path.read_bytes() == broker_before
    assert e["adapter_store"].path.read_bytes() == closed_before
    with sqlite3.connect(e["store"].path) as db:
        archived = json.loads(db.execute(
            "SELECT data FROM "+HISTORY).fetchone()[0])
        assert archived["source"]["cash_reservations"]
        assert archived["snapshot"]["trades"]
        for name, count in preserved.items():
            assert db.execute(
                "SELECT COUNT(*) FROM "+name).fetchone()[0] == count
    assert e["store"].control()["mode"] == "PAUSED"


def test_retirement_replay_does_not_duplicate(closed):
    run(closed)
    result = run(closed)
    assert result["idempotent_replay"] is True
    e = closed[0][0][0]
    with sqlite3.connect(e["store"].path) as db:
        assert db.execute("SELECT COUNT(*) FROM "+HISTORY).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM "+TABLE).fetchone()[0] == 1


@pytest.mark.parametrize("stage", [
    "AFTER_HISTORY_SEAL",
    "AFTER_ACTIVE_REFERENCES_RETIRED",
    "BEFORE_RETIREMENT_COMMIT",
])
def test_interruption_restores_all_active_references(closed, stage):
    def interrupt(current):
        if current == stage:
            raise RuntimeError("SYNTHETIC_RETIREMENT_INTERRUPTION")
    with pytest.raises(RuntimeError, match="RETIREMENT_INTERRUPTION"):
        run(closed, checkpoint=interrupt)
    assert all(n == 1 for n in counts(closed).values())


def test_expiry_rolls_back_retirement(closed):
    at = datetime.fromisoformat(closed[1][3])
    times = iter([at, at+timedelta(minutes=5)])
    with pytest.raises(ValueError):
        run(closed, clock=lambda: next(times))
    assert all(n == 1 for n in counts(closed).values())


def test_unknown_outcome_retains_active_references(closed):
    e, mod, execution = closed[0][0]
    key = closed[1][2]
    with execution.tx() as db:
        row = json.loads(db.execute(
            "SELECT data FROM requests WHERE id=?", (key,)
        ).fetchone()[0])
        row["state"] = "UNKNOWN"
        db.execute("UPDATE requests SET data=? WHERE id=?",
                   (json.dumps(row), key))
    with pytest.raises(ValueError):
        run(closed)
    assert all(n == 1 for n in counts(closed).values())


def test_live_scope_rejected_before_database_access():
    with pytest.raises(ValueError, match="FIXTURE_RETIREMENT_ONLY"):
        retire_fixture_references(
            None, None, {}, {"scope": "UPSTOX:"+"a"*64},
            entry_id="entry", journal=None, exit_sequences=[], clock=lambda: None)


def test_tampered_retirement_replay_blocks(closed):
    run(closed)
    e = closed[0][0][0]
    with sqlite3.connect(e["store"].path) as db:
        row = json.loads(db.execute("SELECT data FROM "+TABLE).fetchone()[0])
        row["archive_fingerprint"] = "changed"
        db.execute("UPDATE "+TABLE+" SET data=?", (json.dumps(row),))
    with pytest.raises(ValueError, match="RETIREMENT_SIGNATURE_INVALID"):
        run(closed)

