"""Installed fake adapter: entry fill -> strategy EXIT -> SELL."""
from datetime import datetime, timedelta
import json

import pytest

from automatic_exit_fixture import run_exit_fixture
from test_automatic_entry_fixture import (
    entry, synthetic_scope, env, bound_env, run as run_entry,
    application_bytes,
)
from test_hilega_application_preparation_v1 import append
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_execution_port_v1.adapter import FixtureTransport
from market_lab.hilega_production_simulator_bridge_v1 import (
    EXITS, accepted, verified_records,
)


@pytest.fixture
def filled(entry):
    e, execution = entry
    run_entry(entry)
    parent, = execution.requests()
    transport = FixtureTransport(execution)
    transport.fill(parent["order_id"], parent["draft"]["body"]["quantity"])

    at = datetime.fromisoformat(parent["signal_at"]) + timedelta(minutes=5)
    name = next(n for n, direction in EXITS.items()
                if direction == parent["direction"])
    append(e["path"], [name], at=at.isoformat())
    event, = accepted(verified_records(e["path"])[-1])
    with e["store"].db() as db:
        plan = json.loads(db.execute(
            "SELECT data FROM preparation_plans"
        ).fetchone()[0])
    return entry, parent, event, plan["evidence"]["contract"], at


def exit_run(filled, **kwargs):
    (e, execution), parent, event, contract, at = filled
    return run_exit_fixture(
        execution, PIN, entry_id=parent["request_id"],
        exit_event=event, contract=contract,
        as_of=at.isoformat(), **kwargs,
    )


def test_entry_fill_exit_fill_completes_fixture_lifecycle(filled):
    entry, parent, _, _, _ = filled
    e, execution = entry
    before = application_bytes(entry)
    result = exit_run(filled)
    sell = next(r for r in execution.requests()
                if r["request_id"] == result["exit_request_id"])
    FixtureTransport(execution).fill(
        sell["order_id"], parent["draft"]["body"]["quantity"])
    final = exit_run(filled)
    assert final["fixture_remaining_quantity"] == 0
    assert final["fixture_flat_reference"] is True
    assert final["fixture_order_count"] == 2
    assert final["reservation_release_permission"] is False
    assert application_bytes(entry) == before


def test_repeated_exit_does_not_duplicate_sell(filled):
    exit_run(filled)
    result = exit_run(filled)
    assert result["fixture_order_count"] == 2
    assert result["fixture_remaining_quantity"] == 65


def test_partial_exit_retains_remaining_quantity(filled):
    entry, _, _, _, _ = filled
    _, execution = entry
    result = exit_run(filled)
    sell = next(r for r in execution.requests()
                if r["request_id"] == result["exit_request_id"])
    FixtureTransport(execution).fill(sell["order_id"], 20)
    final = exit_run(filled)
    assert final["fixture_remaining_quantity"] == 45
    assert final["fixture_flat_reference"] is False


def test_lost_exit_response_never_resubmits(filled):
    first = exit_run(filled, timeout_after=True)
    assert first["exit_state"] == "UNKNOWN"
    final = exit_run(filled)
    assert final["fixture_order_count"] == 2
    assert final["fixture_remaining_quantity"] is None


def test_non_exit_event_is_rejected(filled):
    entry, parent, event, contract, at = filled
    with pytest.raises(ValueError, match="^CONFIRMED_EXIT_EVENT_REQUIRED$"):
        run_exit_fixture(
            entry[1], PIN, entry_id=parent["request_id"],
            exit_event=dict(event, role="ENTRY"), contract=contract,
            as_of=at.isoformat(),
        )