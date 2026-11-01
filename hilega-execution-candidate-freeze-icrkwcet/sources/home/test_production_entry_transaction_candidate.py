from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import Mock, patch

import pytest

from production_entry_transaction_candidate import submit_entry_candidate
from production_entry_authorization_candidate import TABLE
from test_production_entry_authorization_candidate import (
    synthetic_scope, env, bound_env, live_case, context,
)
from test_production_authorizer_hook import candidate
from hilega_application_preparation_fixtures import PIN


@pytest.fixture
def execution(context, candidate):
    e, key, at, source, snapshot, wire, authority, grant = context
    store = candidate.Store(
        e["adapter_store"].path, PIN["scope"], "LIVE_CLOSED")
    token = Mock(side_effect=AssertionError("No credentials permitted"))
    transport = candidate.HttpTransport(token)
    adapter = candidate.Adapter(store, transport)
    return context, candidate, adapter, token


def run(execution, *, provider=None, clock=None):
    c, mod, adapter, token = execution
    e, key, at, source, snapshot, wire, authority, grant = c
    return submit_entry_candidate(
        e["store"], adapter, PIN, authority,
        adapter_module=mod, request_id=key,
        capture_provider=provider or (lambda: deepcopy(snapshot)),
        clock=clock or (lambda: at),
    )


def receipt(execution, aid, wire):
    mod = execution[1]
    return dict(
        attempt_id=aid, wire_fingerprint=mod.sha(wire),
        origin="LOCAL_HTTP_TRANSPORT", http_status=200,
        body=dict(status="success", data=dict(
            order_ids=["SYNTHETIC-TRANSACTION-AUTHORIZED-ENTRY"])),
    )


def count(execution):
    with execution[2].store.tx() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)
        ).fetchone()
        claims = db.execute(
            "SELECT COUNT(*) FROM " + TABLE).fetchone()[0] if exists else 0
        return claims, db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]


def test_closed_gate_skips_capture_and_authorization(execution):
    provider = Mock(side_effect=AssertionError("Gate must precede capture"))
    result = run(execution, provider=provider)
    assert result["status"] == "PRODUCTION_MUTATIONS_CLOSED_IN_CODE"
    provider.assert_not_called()
    execution[3].assert_not_called()
    assert count(execution) == (0, 0)


def test_current_database_context_claims_with_attempt(execution):
    transport = execution[2].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=lambda aid, wire: receipt(execution, aid, wire),
    ) as send:
        result = run(execution)
    assert result["status"] == "CANDIDATE_ENTRY_ATTEMPT_RECORDED"
    assert count(execution) == (1, 1)
    send.assert_called_once()
    execution[3].assert_not_called()


def test_changed_adapter_context_before_claim_blocks(execution):
    c, mod, adapter, token = execution

    def changed_capture():
        with adapter.store.tx() as db:
            key = c[1]
            row = json.loads(db.execute(
                "SELECT data FROM requests WHERE id=?", (key,)
            ).fetchone()[0])
            row["state"] = "UNKNOWN"
            db.execute("UPDATE requests SET data=? WHERE id=?",
                       (json.dumps(row), key))
        return deepcopy(c[4])

    with patch.object(adapter.transport, "check", return_value=None), patch.object(
        adapter.transport, "send",
        side_effect=AssertionError("Changed context must not send"),
    ):
        with pytest.raises(ValueError):
            run(execution, provider=changed_capture)
    assert count(execution) == (0, 0)
    token.assert_not_called()


def test_expiry_before_attempt_rolls_back(execution):
    at = execution[0][2]
    times = iter([at, at + timedelta(seconds=10)])
    with patch.object(execution[2].transport, "check", return_value=None), patch.object(
        execution[2].transport, "send",
        side_effect=AssertionError("Expired authorization must not send"),
    ):
        with pytest.raises(ValueError, match="EXPIRED"):
            run(execution, clock=lambda: next(times))
    assert count(execution) == (0, 0)


def test_delayed_recovery_uses_no_capture_or_transport(execution):
    adapter = execution[2]
    with patch.object(adapter.transport, "check", return_value=None), patch.object(
        adapter.transport, "send",
        side_effect=lambda aid, wire: receipt(execution, aid, wire),
    ):
        run(execution)
    provider = Mock(side_effect=AssertionError("Recovery needs no new capture"))
    with patch.object(
        adapter.transport, "send",
        side_effect=AssertionError("Recovery must not send"),
    ):
        result = run(
            execution, provider=provider,
            clock=lambda: execution[0][2] + timedelta(hours=2),
        )
    assert result["recovery_only"] is True
    provider.assert_not_called()
    assert count(execution) == (1, 1)
