from datetime import datetime, timedelta
import sqlite3

import pytest

from application_lifecycle_review import record_application_review
from application_lifecycle_state import read_current, CURRENT, HISTORY
from test_cancellation_review_state import (
    synthetic_scope, env, bound_env, module, prepared,
    lifecycle, evidence,
)
from hilega_application_preparation_fixtures import PIN


def run(evidence, *, clock=None, checkpoint=lambda stage: None):
    lifecycle, data, sequence = evidence
    e, mod, execution = lifecycle[0]
    source, snapshot, key, at = data
    return record_application_review(
        e["store"].path, execution.path, snapshot, PIN,
        entry_id=key, journal=e["path"], exit_sequences=[sequence],
        clock=clock or (lambda: datetime.fromisoformat(at)),
        mode="OFFLINE_FIXTURE", checkpoint=checkpoint,
    )


def test_application_commit_preserves_execution_database(evidence):
    lifecycle, data, sequence = evidence
    e, mod, execution = lifecycle[0]
    before = execution.path.read_bytes()
    result = run(evidence)
    assert result["status"] == "APPLICATION_LIFECYCLE_REVIEW_COMMITTED"
    assert result["current"]["report"]["cancellation_reference_count"] == 1
    assert result["current"]["report"]["exit_signal_parent_assessed"] is True
    assert execution.path.read_bytes() == before
    assert e["store"].control()["mode"] == "PAUSED"
    assert result["exit_submission_permission"] is False


def test_application_replay_does_not_duplicate_history(evidence):
    run(evidence)
    result = run(evidence)
    assert result["idempotent_replay"] is True
    e = evidence[0][0][0]
    with sqlite3.connect(e["store"].path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM " + HISTORY).fetchone()[0] == 1
        assert read_current(db, PIN) is not None


@pytest.mark.parametrize("stage", [
    "AFTER_HISTORY_INSERT", "BEFORE_COMMIT_VALIDATION",
])
def test_application_interruption_rolls_back(evidence, stage):
    def interrupt(current):
        if current == stage:
            raise RuntimeError("SYNTHETIC_APPLICATION_INTERRUPTION")
    with pytest.raises(RuntimeError, match="APPLICATION_INTERRUPTION"):
        run(evidence, checkpoint=interrupt)
    e = evidence[0][0][0]
    with sqlite3.connect(e["store"].path) as db:
        assert read_current(db, PIN) is None


def test_application_expiry_rolls_back(evidence):
    at = datetime.fromisoformat(evidence[1][3])
    times = iter([at, at + timedelta(minutes=5)])
    with pytest.raises(ValueError):
        run(evidence, clock=lambda: next(times))
    e = evidence[0][0][0]
    with sqlite3.connect(e["store"].path) as db:
        assert read_current(db, PIN) is None


def test_live_mode_rejects_fixture_scope_before_opening_files(tmp_path):
    missing = tmp_path / "absent.sqlite"
    with pytest.raises(ValueError, match="LIVE_PIN_SCOPE_REQUIRED"):
        record_application_review(
            missing, tmp_path / "adapter.sqlite", {}, PIN,
            entry_id="entry", journal=None, exit_sequences=[],
            clock=lambda: None, mode="LIVE_CLOSED",
        )
    assert not missing.exists()
