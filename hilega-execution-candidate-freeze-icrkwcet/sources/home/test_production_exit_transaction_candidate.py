from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import Mock, patch

import pytest

import production_exit_transaction_candidate as transaction
from production_entry_authorization_candidate import TABLE
from test_production_exit_authorization_candidate import (
    synthetic_scope, env, bound_env, live_case, exit_case,
)
from test_production_authorizer_hook import candidate
from hilega_application_preparation_fixtures import PIN


@pytest.fixture
def execution(exit_case, live_case, candidate):
    e = live_case[0]
    store = candidate.Store(
        e["adapter_store"].path, PIN["scope"], "LIVE_CLOSED")
    token = Mock(side_effect=AssertionError("No credentials permitted"))
    adapter = candidate.Adapter(store, candidate.HttpTransport(token))
    return exit_case, e, candidate, adapter, token


def run(execution, *, provider=None, clock=None):
    case, e, mod, adapter, token = execution
    source, snapshot, authority, grant, options, at = case
    return transaction.submit_exit_candidate(
        e["store"], adapter, PIN, authority, adapter_module=mod,
        entry_id=options["entry_id"], request_id=options["request_id"],
        journal=options["journal"], exit_sequence=options["exit_sequence"],
        capture_provider=provider or (lambda: deepcopy(snapshot)),
        clock=clock or (lambda: at),
    )


def counts(execution):
    with execution[3].store.tx() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)
        ).fetchone()
        claims = db.execute(
            "SELECT COUNT(*) FROM " + TABLE).fetchone()[0] if exists else 0
        key = execution[0][4]["request_id"]
        attempts = db.execute(
            "SELECT COUNT(*) FROM attempts WHERE request_id=?", (key,)
        ).fetchone()[0]
    return claims, attempts


def receipt(execution, aid, wire):
    return dict(
        attempt_id=aid, wire_fingerprint=execution[2].sha(wire),
        origin="LOCAL_HTTP_TRANSPORT", http_status=200,
        body=dict(status="success", data=dict(
            order_ids=["SYNTHETIC-TRANSACTION-SELL"])),
    )


def test_real_gate_blocks_sell_before_capture(execution):
    provider = Mock(side_effect=AssertionError("No capture behind closed gate"))
    result = run(execution, provider=provider)
    assert result["status"] == "PRODUCTION_MUTATIONS_CLOSED_IN_CODE"
    provider.assert_not_called()
    execution[4].assert_not_called()
    assert counts(execution) == (0, 0)


def test_sell_claim_and_attempt_use_current_transaction(execution):
    transport = execution[3].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=lambda aid, wire: receipt(execution, aid, wire),
    ) as send:
        result = run(execution)
    assert result["status"] == "CANDIDATE_EXIT_ATTEMPT_RECORDED"
    assert counts(execution) == (1, 1)
    send.assert_called_once()
    execution[4].assert_not_called()


def test_changed_parent_outcome_blocks_sell(execution):
    case, e, mod, adapter, token = execution

    def changed_capture():
        key = case[4]["entry_id"]
        with adapter.store.tx() as db:
            row = json.loads(db.execute(
                "SELECT data FROM requests WHERE id=?", (key,)
            ).fetchone()[0])
            row["state"] = "UNKNOWN"
            db.execute("UPDATE requests SET data=? WHERE id=?",
                       (json.dumps(row), key))
        return deepcopy(case[1])

    with patch.object(adapter.transport, "check", return_value=None), patch.object(
        adapter.transport, "send",
        side_effect=AssertionError("Changed ownership must not send"),
    ):
        with pytest.raises(ValueError):
            run(execution, provider=changed_capture)
    assert counts(execution) == (0, 0)


def test_expiry_before_sell_attempt_rolls_back(execution):
    at = execution[0][5]
    times = iter([at, at+timedelta(seconds=10)])
    transport = execution[3].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=AssertionError("Expired SELL must not send"),
    ):
        with pytest.raises(ValueError, match="EXPIRED"):
            run(execution, clock=lambda: next(times))
    assert counts(execution) == (0, 0)


def test_failure_after_sell_claim_rolls_back_both(execution, monkeypatch):
    original = transaction.claim_candidate

    def interrupt(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("SYNTHETIC_SELL_CLAIM_INTERRUPTION")

    monkeypatch.setattr(transaction, "claim_candidate", interrupt)
    transport = execution[3].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=AssertionError("No send after rollback"),
    ):
        with pytest.raises(RuntimeError, match="SELL_CLAIM_INTERRUPTION"):
            run(execution)
    assert counts(execution) == (0, 0)


def test_delayed_sell_recovery_uses_no_capture_or_send(execution):
    transport = execution[3].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=lambda aid, wire: receipt(execution, aid, wire),
    ):
        run(execution)
    provider = Mock(side_effect=AssertionError("No new capture for recovery"))
    with patch.object(
        transport, "send", side_effect=AssertionError("No repeated SELL"),
    ):
        result = run(
            execution, provider=provider,
            clock=lambda: execution[0][5]+timedelta(hours=2),
        )
    assert result["status"] == "EXISTING_EXIT_RECOVERED_NO_SUBMISSION"
    provider.assert_not_called()
    assert counts(execution) == (1, 1)
