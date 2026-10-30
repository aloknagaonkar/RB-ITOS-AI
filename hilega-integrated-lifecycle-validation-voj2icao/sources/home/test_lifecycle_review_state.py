from copy import deepcopy
from datetime import datetime, timedelta
import json
import sqlite3

import pytest

from lifecycle_review_state import record_review, read_current, HISTORY, CURRENT
from test_lifecycle_signal_review import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle, linked,
)
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign


@pytest.fixture
def evidence(lifecycle):
    data, event, sequence = linked(lifecycle)
    return lifecycle, data, sequence


def record(db, evidence, *, checkpoint=lambda stage: None, clock=None,
           read_source=None):
    lifecycle, data, sequence = evidence
    source, snapshot, key, at = data
    return record_review(
        db, PIN, snapshot, read_source=read_source or (lambda: deepcopy(source)),
        entry_id=key, journal=lifecycle[0][0]["path"],
        exit_sequences=[sequence],
        clock=clock or (lambda: datetime.fromisoformat(at)),
        checkpoint=checkpoint,
    )


def resign(snapshot):
    snapshot.pop("signature", None)
    snapshot["signature"] = sign(snapshot, PIN)


def test_commit_reopen_and_replay(evidence, tmp_path):
    path = tmp_path / "reviews.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        record(db, evidence)
    with sqlite3.connect(path) as db:
        before = read_current(db, PIN)
        db.execute("BEGIN IMMEDIATE")
        replay = record(db, evidence)
        assert replay["idempotent_replay"] is True
        assert replay["current"] == before
        assert db.execute(
            "SELECT COUNT(*) FROM " + HISTORY).fetchone()[0] == 1


@pytest.mark.parametrize("stage", [
    "AFTER_HISTORY_INSERT", "BEFORE_COMMIT_VALIDATION",
])
def test_interruption_rolls_back(evidence, tmp_path, stage):
    path = tmp_path / "reviews.sqlite"

    def interrupt(current):
        if current == stage:
            raise RuntimeError("SYNTHETIC_INTERRUPTION")

    with pytest.raises(RuntimeError):
        with sqlite3.connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            record(db, evidence, checkpoint=interrupt)
    with sqlite3.connect(path) as db:
        assert read_current(db, PIN) is None
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (HISTORY,)
        ).fetchone()
        assert not exists or db.execute(
            "SELECT COUNT(*) FROM " + HISTORY).fetchone()[0] == 0


def test_conflicting_capture_id_blocks(evidence):
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        record(db, evidence)
        db.commit()
        evidence[1][1]["diagnostics"] = {"changed": True}
        resign(evidence[1][1])
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="CAPTURE_ID_OR_SOURCE_CONFLICT"):
            record(db, evidence)


def test_older_capture_cannot_replace_current(evidence):
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        record(db, evidence)
        db.commit()
        snapshot = evidence[1][1]
        snapshot["snapshot_id"] = "older-capture"
        snapshot["generated_at"] = (
            datetime.fromisoformat(snapshot["generated_at"])
            - timedelta(seconds=1)).isoformat()
        resign(snapshot)
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="OUT_OF_ORDER"):
            record(db, evidence)


def test_persisted_tampering_rejected(evidence):
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        record(db, evidence)
        row = read_current(db, PIN)
        row["report"]["reviewed_remaining_quantity"] = 999
        db.execute(
            "UPDATE " + CURRENT + " SET data=? WHERE id=1", (json.dumps(row),))
        with pytest.raises(ValueError, match="SIGNATURE_INVALID"):
            read_current(db, PIN)


def test_expiry_before_commit_rolls_back(evidence, tmp_path):
    at = datetime.fromisoformat(evidence[1][3])
    times = iter([at, at + timedelta(minutes=5)])
    path = tmp_path / "reviews.sqlite"
    with pytest.raises(ValueError):
        with sqlite3.connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            record(db, evidence, clock=lambda: next(times))
    with sqlite3.connect(path) as db:
        assert read_current(db, PIN) is None


def test_source_change_before_commit_rolls_back(evidence, tmp_path):
    source = deepcopy(evidence[1][0])
    changed = deepcopy(source)
    changed["stop_state"] = [1, 0]
    reads = iter([source, changed])
    path = tmp_path / "reviews.sqlite"
    with pytest.raises(ValueError, match="SOURCE_CHANGED_BEFORE_COMMIT"):
        with sqlite3.connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            record(db, evidence, read_source=lambda: next(reads))
    with sqlite3.connect(path) as db:
        assert read_current(db, PIN) is None


def test_live_scope_rejected_before_table_creation():
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="FIXTURE_SCOPE_REQUIRED"):
            record_review(
                db, {"scope": "UPSTOX:" + "a"*64}, {},
                read_source=lambda: None, entry_id="entry",
                journal=None, exit_sequences=[], clock=lambda: None,
            )
        assert db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0] == 0
