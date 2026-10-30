"""Cursor and recovery tests on synthetic temporary journals/databases."""
from datetime import datetime, timedelta

import pytest

from fixture_journal_consumer import FixtureConsumer
from test_automatic_entry_fixture import (
    entry, synthetic_scope, env, bound_env,
)
from test_hilega_application_preparation_v1 import append
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_execution_port_v1.adapter import FixtureTransport
from market_lab.hilega_production_simulator_bridge_v1 import EXITS


def consumer(entry):
    e, execution = entry
    return FixtureConsumer(
        e["store"].path, e["adapter_store"].path,
        execution, PIN, e["path"])


def test_reopen_cursor_does_not_resubmit(entry):
    e, execution = entry
    first = consumer(entry).poll(as_of=e["clock"][0].isoformat())
    second = consumer(entry).poll(as_of=e["clock"][0].isoformat())
    assert first["processed_record_count"] == 1
    assert second["processed_record_count"] == 0
    assert first["cursor_sequence"] == second["cursor_sequence"] == 1
    assert len(FixtureTransport(execution).orders()) == 1


def test_lost_result_before_cursor_recovers_once(entry):
    e, execution = entry

    class Interrupted(BaseException):
        pass

    def interrupt(stage):
        if stage == "AFTER_DISPATCH_BEFORE_CURSOR":
            raise Interrupted()

    with pytest.raises(Interrupted):
        consumer(entry).poll(
            as_of=e["clock"][0].isoformat(), checkpoint=interrupt)
    result = consumer(entry).poll(as_of=e["clock"][0].isoformat())
    assert result["cursor_sequence"] == 1
    assert len(FixtureTransport(execution).orders()) == 1
    with execution.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


def test_poll_new_exit_after_entry_fill(entry):
    e, execution = entry
    consumer(entry).poll(as_of=e["clock"][0].isoformat())
    parent, = execution.requests()
    transport = FixtureTransport(execution)
    transport.fill(parent["order_id"], 65)

    at = datetime.fromisoformat(parent["signal_at"]) + timedelta(minutes=5)
    name = next(n for n, direction in EXITS.items()
                if direction == parent["direction"])
    append(e["path"], [name], at=at.isoformat())
    result = consumer(entry).poll(as_of=at.isoformat())
    assert result["processed_record_count"] == 1
    assert result["cursor_sequence"] == 2
    assert len(transport.orders()) == 2
    assert any(o["side"] == "SELL" for o in transport.orders())


def test_source_truncation_is_rejected(entry):
    e, _ = entry
    consumer(entry).poll(as_of=e["clock"][0].isoformat())
    e["path"].write_text("")
    with pytest.raises(ValueError, match="^SOURCE_TRUNCATED_OR_CURSOR_INVALID$"):
        consumer(entry).poll(as_of=e["clock"][0].isoformat())