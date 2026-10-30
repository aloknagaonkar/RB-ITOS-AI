"""Recovery identity and delayed EXIT tests; fake transport only."""
from datetime import datetime, timedelta
import json
from unittest.mock import patch

import pytest

from test_fixture_journal_consumer import (
    consumer, entry, synthetic_scope, env, bound_env,
)
from test_hilega_application_preparation_v1 import append
from hilega_application_preparation_fixtures import PIN
from automatic_exit_fixture import run_exit_fixture
from market_lab.hilega_execution_port_v1.adapter import FixtureTransport, sha
from market_lab.hilega_production_simulator_bridge_v1 import (
    EXITS, accepted, verified_records,
)


def interrupt_after_dispatch(stage):
    if stage == "AFTER_DISPATCH_BEFORE_CURSOR":
        raise Interrupted()


class Interrupted(BaseException):
    pass


@pytest.mark.parametrize("case,reason", [
    ("request", "RECOVERY_EVENT_REQUEST_MISMATCH"),
    ("wire", "RECOVERY_ATTEMPT_IDENTITY_OR_WIRE_MISMATCH"),
    ("receipt", "RECEIPT_PROVENANCE_MISMATCH"),
])
def test_changed_recovery_records_block_without_transport(entry, case, reason):
    e, execution = entry
    with pytest.raises(Interrupted):
        consumer(entry).poll(
            as_of=e["clock"][0].isoformat(),
            checkpoint=interrupt_after_dispatch,
        )

    with execution.tx() as db:
        if case == "request":
            key, raw = db.execute("SELECT id,data FROM requests").fetchone()
            request = json.loads(raw)
            request["signal_id"] = "synthetic-different-signal"
            stable = {
                k: request[k] for k in (
                    "request_id", "draft", "signal_id", "signal_at",
                    "direction", "reservation_reference",
                )
            }
            db.execute(
                "UPDATE requests SET fingerprint=?,data=? WHERE id=?",
                (sha(stable), json.dumps(request), key),
            )
        elif case == "wire":
            key, raw = db.execute("SELECT id,data FROM attempts").fetchone()
            attempt = json.loads(raw)
            attempt["wire"]["body"]["quantity"] += 1
            db.execute(
                "UPDATE attempts SET data=? WHERE id=?",
                (json.dumps(attempt), key),
            )
        else:
            key, raw = db.execute("SELECT id,data FROM receipts").fetchone()
            receipt = json.loads(raw)
            receipt["origin"] = "SYNTHETIC_WRONG_ORIGIN"
            db.execute(
                "UPDATE receipts SET data=? WHERE id=?",
                (json.dumps(receipt), key),
            )

    later = (e["clock"][0] + timedelta(minutes=5)).isoformat()
    with patch.object(
        FixtureTransport, "send",
        side_effect=AssertionError("Recovery must never send"),
    ):
        with pytest.raises(ValueError, match="^" + reason + "$"):
            consumer(entry).poll(as_of=later)

    with execution.tx() as db:
        cursor = json.loads(db.execute(
            "SELECT data FROM fixture_dispatch_cursor WHERE id=1"
        ).fetchone()[0])
        assert cursor["sequence"] == 0
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


@pytest.mark.parametrize("durable_receipt", [True, False])
def test_delayed_exit_recovery_never_resubmits(entry, durable_receipt):
    e, execution = entry
    consumer(entry).poll(as_of=e["clock"][0].isoformat())
    parent, = execution.requests()
    transport = FixtureTransport(execution)
    transport.fill(parent["order_id"], 65)

    at = datetime.fromisoformat(parent["signal_at"]) + timedelta(minutes=5)
    name = next(n for n, direction in EXITS.items()
                if direction == parent["direction"])
    append(e["path"], [name], at=at.isoformat())
    event, = accepted(verified_records(e["path"])[-1])

    if durable_receipt:
        with pytest.raises(Interrupted):
            consumer(entry).poll(
                as_of=at.isoformat(), checkpoint=interrupt_after_dispatch)
    else:
        with e["store"].db() as db:
            plan = json.loads(db.execute(
                "SELECT data FROM preparation_plans"
            ).fetchone()[0])
        run_exit_fixture(
            execution, PIN, entry_id=parent["request_id"],
            exit_event=event, contract=plan["evidence"]["contract"],
            as_of=at.isoformat(), timeout_after=True,
        )

    later = (at + timedelta(minutes=5)).isoformat()
    with patch.object(
        FixtureTransport, "send",
        side_effect=AssertionError("EXIT recovery must never send"),
    ):
        result = consumer(entry).poll(as_of=later)

    assert result["cursor_sequence"] == 2
    assert len(transport.orders()) == 2
    sell = next(r for r in execution.requests()
                if r["draft"]["body"]["transaction_type"] == "SELL")
    if durable_receipt:
        assert sell["state"] == "RECONCILIATION_REQUIRED"
        assert sell["order_id"] is not None
        assert sell["filled"] is None and sell["remaining"] is None
    else:
        assert sell["state"] == "UNKNOWN"
        assert sell["order_id"] is None
    with execution.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 2