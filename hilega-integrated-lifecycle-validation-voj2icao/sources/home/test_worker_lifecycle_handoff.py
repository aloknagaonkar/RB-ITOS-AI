from copy import deepcopy
from datetime import timedelta
import sqlite3
from unittest.mock import Mock

import pytest

from worker_lifecycle_handoff import capture_and_record
from application_lifecycle_state import read_current, HISTORY
from test_live_closed_lifecycle_candidate import (
    synthetic_scope, env, bound_env, live_case,
)
from test_worker_handoff import worker
from hilega_application_preparation_fixtures import PIN


def handoff(case, *, provider=None, clock=None,
            checkpoint=lambda stage: None):
    e, key, snapshot, at = case
    return capture_and_record(
        e["store"].path, e["adapter_store"].path, PIN,
        journal=e["path"], exit_sequences=[],
        capture_provider=provider or (lambda: deepcopy(snapshot)),
        clock=clock or (lambda: at),
        mode="LIVE_CLOSED", checkpoint=checkpoint,
    )


def test_worker_requests_capture_and_commits_review(worker, live_case):
    e, key, snapshot, at = live_case
    provider = Mock(return_value=deepcopy(snapshot))
    result = worker.preparation_tick(
        e["source"], e["path"],
        test_handoff=lambda: handoff(live_case, provider=provider),
    )
    assert result["execution_handoff"]["status"] == (
        "APPLICATION_LIFECYCLE_REVIEW_COMMITTED")
    provider.assert_called_once()
    assert result["execution_handoff"]["production_execution_enabled"] is False
    assert e["store"].control()["mode"] == "PAUSED"


def test_capture_failure_creates_no_review(worker, live_case):
    e = live_case[0]
    provider = Mock(side_effect=RuntimeError("SYNTHETIC_CAPTURE_FAILURE"))
    with pytest.raises(RuntimeError, match="CAPTURE_FAILURE"):
        worker.preparation_tick(
            e["source"], e["path"],
            test_handoff=lambda: handoff(live_case, provider=provider),
        )
    with sqlite3.connect(e["store"].path) as db:
        assert read_current(db, PIN) is None


def test_stale_capture_cannot_create_review(live_case):
    with pytest.raises(ValueError):
        handoff(
            live_case,
            clock=lambda: live_case[3] + timedelta(minutes=5),
        )
    with sqlite3.connect(live_case[0]["store"].path) as db:
        assert read_current(db, PIN) is None


def test_stale_replay_is_not_reported_as_fresh(live_case):
    handoff(live_case)
    with pytest.raises(ValueError):
        handoff(
            live_case,
            clock=lambda: live_case[3] + timedelta(minutes=5),
        )
    with sqlite3.connect(live_case[0]["store"].path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM " + HISTORY).fetchone()[0] == 1


def test_lost_handoff_result_replays_committed_review(live_case):
    def interrupt(stage):
        raise RuntimeError("SYNTHETIC_HANDOFF_RESULT_LOST")

    with pytest.raises(RuntimeError, match="HANDOFF_RESULT_LOST"):
        handoff(live_case, checkpoint=interrupt)
    result = handoff(live_case)
    assert result["idempotent_replay"] is True
    assert result["database_modified"] is False
    with sqlite3.connect(live_case[0]["store"].path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM " + HISTORY).fetchone()[0] == 1


def test_wrong_account_capture_is_rejected(live_case):
    changed = deepcopy(live_case[2])
    changed["account_scope"] = "UPSTOX:" + "b" * 64
    with pytest.raises(ValueError):
        handoff(live_case, provider=lambda: changed)
    with sqlite3.connect(live_case[0]["store"].path) as db:
        assert read_current(db, PIN) is None


def test_empty_application_does_not_request_capture(
    synthetic_scope, monkeypatch, request,
):
    monkeypatch.setitem(PIN, "scope", "UPSTOX:" + "a" * 64)
    e = request.getfixturevalue("bound_env")
    # Set the temporary fixture to the paused state required by this reviewer.
    import json
    with e["store"].db() as db:
        control = json.loads(db.execute(
            "SELECT data FROM control WHERE id=1"
        ).fetchone()[0])
        control["mode"] = "PAUSED"
        db.execute(
            "UPDATE control SET data=? WHERE id=1",
            (json.dumps(control),),
        )
    provider = Mock(side_effect=AssertionError("No capture for empty state"))
    result = capture_and_record(
        e["store"].path, e["adapter_store"].path, PIN,
        journal=e["path"], exit_sequences=[],
        capture_provider=provider, clock=lambda: e["clock"][0],
        mode="LIVE_CLOSED",
    )
    assert result["status"] == "NO_BOUND_ENTRY_CAPTURE_NOT_REQUESTED"
    provider.assert_not_called()
    with sqlite3.connect(e["store"].path) as db:
        assert read_current(db, PIN) is None
