"""Temporary SQLite tests; no application DB or broker access."""
import json
import sqlite3

import pytest

from closed_dispatch_decisions import record, FLAGS

PIN = {"scope": "FIXTURE:CLOSED-DECISIONS", "key": "33" * 32}
AT = "2026-10-30T11:10:00+05:30"


def report():
    return dict(
        {k: False for k in FLAGS},
        model="HILEGA_CLOSED_ENTRY_DISPATCH_V1",
        status="DISPATCH_REFUSED_LIVE_GATE_CLOSED",
        reference_checks_passed=True, review_reasons=[],
    )


def save(db, **changes):
    args = dict(
        request_id="synthetic-entry", source_fingerprint="a" * 64,
        report=report(), assessed_at=AT,
    )
    args.update(changes)
    return record(db, PIN, **args)


@pytest.fixture
def db(tmp_path):
    connection = sqlite3.connect(tmp_path / "decisions.sqlite")
    connection.execute("BEGIN IMMEDIATE")
    yield connection
    connection.rollback()
    connection.close()


def test_commit_reopen_and_replay(db):
    first = save(db)
    path = db.execute("PRAGMA database_list").fetchone()[2]
    db.commit()
    with sqlite3.connect(path) as reopened:
        reopened.execute("BEGIN IMMEDIATE")
        second = save(
            reopened, assessed_at="2026-10-30T11:10:05+05:30")
        assert second["idempotent_replay"] is True
        assert first["decision_id"] == second["decision_id"]
        assert reopened.execute(
            "SELECT COUNT(*) FROM closed_dispatch_decisions"
        ).fetchone()[0] == 1


def test_rollback_removes_decision(db):
    save(db)
    db.rollback()
    # Table creation is part of the caller's transaction too.
    assert db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='closed_dispatch_decisions'"
    ).fetchone() is None


def test_changed_report_conflicts(db):
    save(db)
    changed = report()
    changed["reference_checks_passed"] = False
    with pytest.raises(ValueError, match="^DECISION_REPLAY_CONFLICT$"):
        save(db, report=changed)


def test_persisted_tampering_rejected(db):
    save(db)
    raw = db.execute(
        "SELECT data FROM closed_dispatch_decisions"
    ).fetchone()[0]
    row = json.loads(raw)
    row["report"]["reference_checks_passed"] = False
    db.execute(
        "UPDATE closed_dispatch_decisions SET data=?", (json.dumps(row),))
    with pytest.raises(ValueError, match="^PERSISTED_DECISION_SIGNATURE_INVALID$"):
        save(db)


def test_permission_injection_rejected(db):
    changed = report()
    changed["entry_permission"] = True
    with pytest.raises(ValueError, match="^CLOSED_REPORT_FLAGS_REQUIRED$"):
        save(db, report=changed)


def test_live_scope_rejected_before_table_creation(db):
    with pytest.raises(ValueError, match="^FIXTURE_SCOPE_REQUIRED$"):
        record(
            db, dict(PIN, scope="UPSTOX:" + "a" * 64),
            request_id="entry", source_fingerprint="a" * 64,
            report=report(), assessed_at=AT,
        )
    assert db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='closed_dispatch_decisions'"
    ).fetchone() is None


def test_missing_transaction_rejected(db):
    db.rollback()
    with pytest.raises(ValueError, match="^CALLER_TRANSACTION_REQUIRED$"):
        save(db)