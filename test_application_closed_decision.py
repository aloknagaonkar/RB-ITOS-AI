"""Application-owned decisions using temporary synthetic databases."""
from datetime import timedelta
import json
import sqlite3

import pytest

from application_closed_decision import record_application_decision
from test_fixture_closed_dispatch import (
    prepared, fixture_scope, env, bound_env,
)
from hilega_application_preparation_fixtures import PIN


def invoke(e, **kwargs):
    return record_application_decision(
        e["store"], e["adapter_store"].path, PIN,
        clock=lambda: e["clock"][0], **kwargs,
    )


def decisions(e):
    with e["store"].db() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='closed_dispatch_decisions'"
        ).fetchone()
        return db.execute(
            "SELECT COUNT(*) FROM closed_dispatch_decisions"
        ).fetchone()[0] if exists else 0


def test_commit_reopen_and_replay(prepared):
    e, _ = prepared
    adapter_before = e["adapter_store"].path.read_bytes()
    first = invoke(e)
    second = invoke(e)
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert first["decision_id"] == second["decision_id"]
    assert decisions(e) == 1
    assert e["adapter_store"].path.read_bytes() == adapter_before
    assert e["store"].control()["mode"] == "PAUSED"
    assert second["production_execution_enabled"] is False


@pytest.mark.parametrize("point", [
    "AFTER_REVIEW", "AFTER_DECISION_INSERT", "BEFORE_COMMIT",
])
def test_interruption_rolls_back(prepared, point):
    e, _ = prepared
    adapter_before = e["adapter_store"].path.read_bytes()

    class Interrupted(BaseException):
        pass

    def checkpoint(stage):
        if stage == point:
            raise Interrupted()

    with pytest.raises(Interrupted):
        invoke(e, checkpoint=checkpoint)
    assert decisions(e) == 0
    assert e["adapter_store"].path.read_bytes() == adapter_before


def test_expired_evidence_before_commit_rolls_back(prepared):
    e, _ = prepared

    def checkpoint(stage):
        if stage == "BEFORE_COMMIT":
            e["clock"][0] += timedelta(seconds=61)

    with pytest.raises(ValueError, match="^REVIEW_CHANGED_BEFORE_COMMIT$"):
        invoke(e, checkpoint=checkpoint)
    assert decisions(e) == 0


def test_local_change_before_commit_rolls_back(prepared):
    e, _ = prepared
    original = e["store"].control()

    def checkpoint(stage):
        if stage == "BEFORE_COMMIT":
            # Deliberately alter the uncommitted application transaction.
            from application_closed_decision import read_connection
            # Access the transaction through a wrapper installed below.
            mutate[0] = True

    import application_closed_decision as target
    original_reader = target.read_connection
    mutate = [False]

    def reader(db, *args, **kwargs):
        if mutate[0]:
            mutate[0] = False
            row = json.loads(db.execute(
                "SELECT data FROM control WHERE id=1"
            ).fetchone()[0])
            row["version"] += 1
            db.execute(
                "UPDATE control SET data=? WHERE id=1",
                (json.dumps(row),),
            )
        return original_reader(db, *args, **kwargs)

    from unittest.mock import patch
    with patch.object(target, "read_connection", reader):
        with pytest.raises(ValueError, match="^SOURCE_CHANGED_BEFORE_COMMIT$"):
            invoke(e, checkpoint=checkpoint)
    assert decisions(e) == 0
    assert e["store"].control() == original


def test_real_account_scope_rejected(prepared):
    e, _ = prepared
    with pytest.raises(ValueError, match="^FIXTURE_SCOPE_REQUIRED$"):
        record_application_decision(
            e["store"], e["adapter_store"].path,
            dict(PIN, scope="UPSTOX:" + "a" * 64),
            clock=lambda: e["clock"][0],
        )
    assert decisions(e) == 0