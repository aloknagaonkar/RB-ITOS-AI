"""Confirmed journal events drive the fixture lifecycle."""
from datetime import datetime, timedelta
import json

import pytest

from fixture_event_dispatcher import dispatch_journal_record
from test_automatic_entry_fixture import (
    entry, synthetic_scope, env, bound_env, application_bytes,
)
from test_hilega_application_preparation_v1 import append, ARM, BULL
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_execution_port_v1.adapter import FixtureTransport
from market_lab.hilega_production_simulator_bridge_v1 import EXITS, verified_records


def dispatch(entry, sequence, at):
    e, execution = entry
    return dispatch_journal_record(
        e["store"].path, e["adapter_store"].path, execution,
        PIN, e["path"], sequence=sequence, as_of=at.isoformat(),
    )


def test_journal_entry_fill_exit_and_replay(entry):
    e, execution = entry
    before = application_bytes(entry)
    sequence = len(verified_records(e["path"]))
    first = dispatch(entry, sequence, e["clock"][0])
    assert first["dispatched_event_role"] == "ENTRY"
    dispatch(entry, sequence, e["clock"][0])
    parent, = execution.requests()
    transport = FixtureTransport(execution)
    assert len(transport.orders()) == 1
    transport.fill(parent["order_id"], 65)

    at = datetime.fromisoformat(parent["signal_at"]) + timedelta(minutes=5)
    name = next(n for n, direction in EXITS.items()
                if direction == parent["direction"])
    append(e["path"], [name], at=at.isoformat())
    sequence = len(verified_records(e["path"]))
    result = dispatch(entry, sequence, at)
    assert result["dispatched_event_role"] == "EXIT"
    sell = next(r for r in execution.requests()
                if r["request_id"] == result["exit_request_id"])
    transport.fill(sell["order_id"], 65)

    final = dispatch(entry, sequence, at)
    assert final["status"] == "EXISTING_ATTEMPT_INSPECTED_NO_SUBMISSION"
    assert final["recovery_only"] is True
    assert final["new_submission_authorized"] is False

    # Independently inspect fake fills; recovery does not certify exposure.
    orders = transport.orders()
    assert len(orders) == 2
    assert sum(o["filled"] for o in orders if o["side"] == "BUY") == 65
    assert sum(o["filled"] for o in orders if o["side"] == "SELL") == 65
    recovered = next(
        r for r in execution.requests()
        if r["request_id"] == sell["request_id"])
    assert recovered["state"] == "RECONCILIATION_REQUIRED"
    assert recovered["filled"] is None
    assert recovered["remaining"] is None
    assert final["orders_sent_to_upstox"] is False
    assert application_bytes(entry) == before


def test_armed_event_never_submits(entry):
    e, execution = entry
    append(e["path"], [ARM])
    result = dispatch(
        entry, len(verified_records(e["path"])), e["clock"][0])
    assert result["status"] == "NO_CONFIRMED_EXECUTION_EVENT"
    assert execution.requests() == []


def test_reconstructed_event_never_submits(entry):
    e, execution = entry
    append(e["path"], [BULL], reconstructed=True)
    result = dispatch(
        entry, len(verified_records(e["path"])), e["clock"][0])
    assert result["status"] == "NO_CONFIRMED_EXECUTION_EVENT"
    assert execution.requests() == []


def test_invalid_sequence_never_submits(entry):
    e, execution = entry
    with pytest.raises(ValueError, match="^JOURNAL_SEQUENCE_INVALID$"):
        dispatch(entry, 0, e["clock"][0])
    assert execution.requests() == []