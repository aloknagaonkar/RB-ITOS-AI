"""Reject full-size exits for unfilled/partial synthetic entries."""
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


@pytest.mark.parametrize("filled_quantity", [0, 20, 64])
def test_incomplete_entry_cannot_submit_full_exit(entry, filled_quantity):
    e, execution = entry
    run_entry(entry)
    parent, = execution.requests()
    transport = FixtureTransport(execution)
    if filled_quantity:
        transport.fill(parent["order_id"], filled_quantity)

    at = datetime.fromisoformat(parent["signal_at"]) + timedelta(minutes=5)
    name = next(
        name for name, direction in EXITS.items()
        if direction == parent["direction"]
    )
    append(e["path"], [name], at=at.isoformat())
    event, = accepted(verified_records(e["path"])[-1])

    with e["store"].db() as db:
        plan = json.loads(db.execute(
            "SELECT data FROM preparation_plans"
        ).fetchone()[0])

    application_before = application_bytes(entry)
    requests_before = execution.requests()
    with execution.tx() as db:
        attempts_before = db.execute(
            "SELECT COUNT(*) FROM attempts"
        ).fetchone()[0]

    with pytest.raises(ValueError, match="^FULL_ENTRY_FILL_REQUIRED$"):
        run_exit_fixture(
            execution, PIN,
            entry_id=parent["request_id"],
            exit_event=event,
            contract=plan["evidence"]["contract"],
            as_of=at.isoformat(),
        )

    assert application_bytes(entry) == application_before
    assert len(execution.requests()) == len(requests_before) == 1
    assert all(
        order["side"] == "BUY" for order in transport.orders()
    )
    with execution.tx() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM attempts"
        ).fetchone()[0] == attempts_before == 1