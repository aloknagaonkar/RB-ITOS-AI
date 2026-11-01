from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from test_hilega_consolidated_adapter_v1 import request, AT

PATH = Path('/home/aloknagaonkar46/RB-ITOS-AI/hilega-production-authorizer-stage-6kll80yx/adapter.py')
EXPECTED = 'a70cc00e9c1e4e8c315460cd3c46e06acdd8c7ebf666bf189ceccf027e11ac46'
SCOPE = "UPSTOX:" + "a" * 64


@pytest.fixture
def candidate():
    assert hashlib.sha256(PATH.read_bytes()).hexdigest() == EXPECTED
    spec = importlib.util.spec_from_file_location(
        "market_lab.hilega_execution_port_v1._production_authorizer_candidate",
        PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def execution(candidate, tmp_path):
    store = candidate.Store(
        tmp_path / "candidate.sqlite", SCOPE, "LIVE_CLOSED")
    token = Mock(side_effect=AssertionError("No credentials permitted"))
    transport = candidate.HttpTransport(token)
    adapter = candidate.Adapter(store, transport)
    draft = request("production-candidate-entry")
    draft["body"].update(order_type="LIMIT", price=100)
    draft["body"].pop("market_protection", None)
    draft["fingerprint"] = candidate.sha(draft["body"])
    adapter.prepare(
        draft, signal_id="synthetic-production-candidate-signal",
        signal_at=AT, direction="BULLISH",
        reservation_reference="synthetic-hold", as_of=AT,
    )
    return candidate, store, token, transport, adapter


def claims_and_attempts(execution):
    store = execution[1]
    with store.tx() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='test_authorizer_claims'"
        ).fetchone()
        claims = db.execute(
            "SELECT COUNT(*) FROM test_authorizer_claims"
        ).fetchone()[0] if exists else 0
        attempts = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    return claims, attempts


def authorizer(execution, *, interrupt=False, invalid=False):
    module, store, token, transport, adapter = execution

    def claim(db, attempt):
        assert db.in_transaction
        db.execute(
            "CREATE TABLE IF NOT EXISTS test_authorizer_claims("
            "request_id TEXT PRIMARY KEY,attempt_id TEXT UNIQUE NOT NULL)")
        db.execute(
            "INSERT INTO test_authorizer_claims VALUES(?,?)",
            (attempt["request_id"], attempt["attempt_id"]),
        )
        if interrupt:
            raise RuntimeError("SYNTHETIC_PRODUCTION_CLAIM_INTERRUPTION")
        return dict(
            authorization_claimed=True, context_revalidated=True,
            account_scope=SCOPE,
            request_id=attempt["request_id"],
            attempt_id=attempt["attempt_id"],
            wire_fingerprint=(
                "INVALID" if invalid else module.sha(attempt["wire"])),
            production_execution_enabled=False,
        )
    adapter.production_attempt_authorizer = claim


def receipt(execution, attempt_id, wire):
    module = execution[0]
    return dict(
        attempt_id=attempt_id, wire_fingerprint=module.sha(wire),
        http_status=200, origin="LOCAL_HTTP_TRANSPORT",
        body=dict(status="success", data=dict(
            order_ids=["SYNTHETIC-PRODUCTION-CANDIDATE-ORDER"])),
    )


def test_real_gate_precedes_authorizer_and_network(execution):
    _, _, token, transport, adapter = execution
    claim = Mock(side_effect=AssertionError("Gate must run first"))
    adapter.production_attempt_authorizer = claim
    with patch.object(
        transport, "send", side_effect=AssertionError("No network permitted"),
    ):
        result = adapter.submit("production-candidate-entry")
    assert result["status"] == "PRODUCTION_MUTATIONS_CLOSED_IN_CODE"
    claim.assert_not_called()
    token.assert_not_called()
    assert claims_and_attempts(execution) == (0, 0)


def test_missing_authorizer_blocks_attempt(execution):
    _, _, token, transport, adapter = execution
    # Scoped gate interception is test-only.
    with patch.object(transport, "check", return_value=None):
        with pytest.raises(ValueError, match="AUTHORIZER_REQUIRED"):
            adapter.submit("production-candidate-entry")
    token.assert_not_called()
    assert claims_and_attempts(execution) == (0, 0)


def test_claim_and_attempt_commit_together(execution):
    _, _, token, transport, adapter = execution
    authorizer(execution)
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=lambda aid, wire: receipt(execution, aid, wire),
    ) as send:
        adapter.submit("production-candidate-entry")
    assert claims_and_attempts(execution) == (1, 1)
    send.assert_called_once()
    token.assert_not_called()


@pytest.mark.parametrize("invalid", [False, True])
def test_failed_authorization_rolls_back_claim_and_attempt(execution, invalid):
    _, _, token, transport, adapter = execution
    authorizer(execution, interrupt=not invalid, invalid=invalid)
    error = ValueError if invalid else RuntimeError
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=AssertionError("No send after failure"),
    ):
        with pytest.raises(error):
            adapter.submit("production-candidate-entry")
    assert claims_and_attempts(execution) == (0, 0)
    token.assert_not_called()


def test_concurrent_callers_commit_once(execution):
    _, _, token, transport, adapter = execution
    authorizer(execution)
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=lambda aid, wire: receipt(execution, aid, wire),
    ) as send:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(adapter.submit, "production-candidate-entry")
                for _ in range(2)
            ]
            for future in futures:
                future.result(timeout=30)
    assert claims_and_attempts(execution) == (1, 1)
    send.assert_called_once()
    token.assert_not_called()


def test_replay_does_not_claim_or_send(execution):
    _, _, token, transport, adapter = execution
    authorizer(execution)
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=lambda aid, wire: receipt(execution, aid, wire),
    ):
        adapter.submit("production-candidate-entry")
    adapter.production_attempt_authorizer = Mock(
        side_effect=AssertionError("Replay must not claim"))
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=AssertionError("Replay must not send"),
    ):
        result = adapter.submit("production-candidate-entry")
    assert result["idempotent_replay"] is True
    assert claims_and_attempts(execution) == (1, 1)
    token.assert_not_called()
