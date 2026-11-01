from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest

from production_cancel_authorization_candidate import TABLE
import production_cancel_transaction_candidate as transaction
from test_live_closed_lifecycle_candidate import (
    synthetic_scope, env, bound_env, live_case,
)
from test_production_authorizer_hook import candidate
from test_hilega_application_preparation_v1 import append
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_production_simulator_bridge_v1 import verified_records
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign

EXIT = "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"


@pytest.fixture
def execution(live_case, candidate):
    e, key, original, at = live_case
    snapshot = deepcopy(original)
    order = snapshot["orders"][0]
    quantity = order["quantity"] - 1
    order.update(status="PARTIAL", filled=quantity, pending=1)
    snapshot["trades"][0]["quantity"] = quantity
    snapshot["positions"][0]["quantity"] = quantity
    snapshot.pop("signature", None)
    snapshot["signature"] = sign(snapshot, PIN)
    append(e["path"], [EXIT])
    sequence = verified_records(e["path"])[-1]["sequence"]
    store = candidate.Store(
        e["adapter_store"].path, PIN["scope"], "LIVE_CLOSED")
    token = Mock(side_effect=AssertionError("No credentials permitted"))
    adapter = candidate.Adapter(store, candidate.HttpTransport(token))
    authority = dict(
        authority_id="SYNTHETIC-CANCEL-AUTHORITY",
        account_scope=PIN["scope"], key="77"*32,
    )
    return e, key, snapshot, at, sequence, adapter, candidate, authority, token


def run(case, *, clock=None):
    e, key, snapshot, at, sequence, adapter, mod, authority, token = case
    return transaction.submit_cancel_candidate(
        e["store"], adapter, PIN, authority,
        adapter_module=mod, request_id=key,
        journal=e["path"], exit_sequence=sequence,
        capture_provider=lambda: deepcopy(snapshot),
        clock=clock or (lambda: at),
    )


def counts(case):
    with case[5].store.tx() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)
        ).fetchone()
        claims = db.execute(
            "SELECT COUNT(*) FROM " + TABLE).fetchone()[0] if exists else 0
        attempts = db.execute(
            "SELECT COUNT(*) FROM attempts WHERE operation='CANCEL'"
        ).fetchone()[0]
    return claims, attempts


def receipt(case, aid, wire):
    return dict(
        attempt_id=aid, wire_fingerprint=case[6].sha(wire),
        http_status=200, origin="LOCAL_HTTP_TRANSPORT",
        body=dict(status="success", data=dict(
            order_id=wire["query"]["order_id"])),
    )


def test_gate_blocks_production_cancel(execution):
    result = run(execution)
    assert result["status"] == "PRODUCTION_MUTATIONS_CLOSED_IN_CODE"
    assert counts(execution) == (0, 0)
    execution[8].assert_not_called()


def test_authorized_cancel_claim_and_attempt(execution):
    transport = execution[5].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=lambda aid, wire: receipt(execution, aid, wire),
    ) as send:
        result = run(execution)
    assert result["status"] == "CANDIDATE_CANCEL_ATTEMPT_RECORDED"
    assert counts(execution) == (1, 1)
    send.assert_called_once()
    execution[8].assert_not_called()


def test_cancel_claim_failure_rolls_back(execution, monkeypatch):
    original = transaction.claim_candidate

    def interrupt(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("SYNTHETIC_CANCEL_INTERRUPTION")

    monkeypatch.setattr(transaction, "claim_candidate", interrupt)
    transport = execution[5].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=AssertionError("No send after failure"),
    ):
        with pytest.raises(RuntimeError, match="CANCEL_INTERRUPTION"):
            run(execution)
    assert counts(execution) == (0, 0)


def test_cancel_expiry_blocks_attempt(execution):
    at = execution[3]
    times = iter([at, at+timedelta(seconds=10)])
    transport = execution[5].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=AssertionError("No expired cancel"),
    ):
        with pytest.raises(ValueError, match="EXPIRED"):
            run(execution, clock=lambda: next(times))
    assert counts(execution) == (0, 0)


def test_cancel_recovery_never_resends(execution):
    transport = execution[5].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=lambda aid, wire: receipt(execution, aid, wire),
    ):
        run(execution)
    with patch.object(
        transport, "send", side_effect=AssertionError("No repeated cancel"),
    ):
        result = run(
            execution, clock=lambda: execution[3]+timedelta(hours=2))
    assert result["status"] == "EXISTING_CANCEL_RECOVERED_NO_SUBMISSION"
    assert counts(execution) == (1, 1)


def test_lost_cancel_response_remains_unknown(execution):
    transport = execution[5].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=TimeoutError("Synthetic lost response"),
    ):
        run(execution)
    with patch.object(
        transport, "send", side_effect=AssertionError("No unknown-outcome retry"),
    ):
        run(execution, clock=lambda: execution[3]+timedelta(hours=2))
    row = next(r for r in execution[5].store.requests()
               if r["request_id"] == execution[1])
    assert row["state"] == "CANCEL_OUTCOME_UNKNOWN"
    assert counts(execution) == (1, 1)
