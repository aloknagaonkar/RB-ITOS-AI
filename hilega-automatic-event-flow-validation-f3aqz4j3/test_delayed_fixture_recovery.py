"""Expired evidence never permits a second transport call."""
from datetime import timedelta
from unittest.mock import patch

import pytest

from test_fixture_journal_consumer import (
    consumer, entry, synthetic_scope, env, bound_env,
)
from automatic_entry_fixture import run_entry_fixture
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_execution_port_v1.adapter import FixtureTransport


def test_delayed_receipt_recovery_never_calls_transport(entry):
    e, execution = entry

    class Interrupted(BaseException):
        pass

    def interrupt(stage):
        if stage == "AFTER_DISPATCH_BEFORE_CURSOR":
            raise Interrupted()

    with pytest.raises(Interrupted):
        consumer(entry).poll(
            as_of=e["clock"][0].isoformat(), checkpoint=interrupt)

    later = (e["clock"][0] + timedelta(minutes=5)).isoformat()
    with patch.object(
        FixtureTransport, "send",
        side_effect=AssertionError("Recovery must not call transport"),
    ):
        result = consumer(entry).poll(as_of=later)

    assert result["cursor_sequence"] == 1
    saved, = execution.requests()
    assert saved["order_id"] is not None
    assert saved["state"] == "RECONCILIATION_REQUIRED"
    assert saved["filled"] is None and saved["remaining"] is None
    assert len(FixtureTransport(execution).orders()) == 1


def test_delayed_missing_receipt_stays_unknown(entry):
    e, execution = entry

    class Interrupted(BaseException):
        pass

    def interrupt(stage):
        if stage == "AFTER_ATTEMPT_COMMIT":
            raise Interrupted()

    with pytest.raises(Interrupted):
        run_entry_fixture(
            e["store"].path, e["adapter_store"].path, execution, PIN,
            as_of=e["clock"][0].isoformat(), checkpoint=interrupt,
        )

    later = (e["clock"][0] + timedelta(minutes=5)).isoformat()
    with patch.object(
        FixtureTransport, "send",
        side_effect=AssertionError("Unknown attempt must not be retried"),
    ):
        consumer(entry).poll(as_of=later)

    saved, = execution.requests()
    assert saved["state"] == "UNKNOWN"
    assert saved["order_id"] is None
    assert FixtureTransport(execution).orders() == []


def test_stale_event_without_attempt_cannot_submit(entry):
    e, execution = entry
    later = (e["clock"][0] + timedelta(minutes=5)).isoformat()
    with patch.object(
        FixtureTransport, "send",
        side_effect=AssertionError("Stale event must not submit"),
    ):
        with pytest.raises(ValueError, match="^ENTRY_PRECONDITIONS_NOT_MET$"):
            consumer(entry).poll(as_of=later)

    with execution.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        import json
        cursor = json.loads(db.execute(
            "SELECT data FROM fixture_dispatch_cursor WHERE id=1"
        ).fetchone()[0])
    assert cursor["sequence"] == 0