"""Authorization claim + attempt transaction; staged fixture adapter only."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from fixture_execution_authorization import issue, claim
from test_hilega_consolidated_adapter_v1 import request, AT

PATH = Path("hilega-authorized-attempt-stage-xzqykzdz/adapter.py")
EXPECTED = "82c7606a4c4aad8b540b59db35766a736982dac18e9501f26179d9e8fe24b4a4"
PIN = {"scope": "FIXTURE:AUTHORIZED-ATTEMPT", "key": "55" * 32}


@pytest.fixture
def module():
    assert PATH.is_file() and not PATH.is_symlink()
    assert hashlib.sha256(PATH.read_bytes()).hexdigest() == EXPECTED
    spec = importlib.util.spec_from_file_location(
        "market_lab.hilega_execution_port_v1._authorized_candidate", PATH)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def execution(module, tmp_path):
    store = module.Store(tmp_path / "execution.sqlite", PIN["scope"], "OFFLINE_FIXTURE")
    transport = module.FixtureTransport(store)
    adapter = module.Adapter(store, transport)

    draft = request("entry")
    draft["body"].update(order_type="LIMIT", price=100)
    draft["body"].pop("market_protection", None)
    draft["fingerprint"] = module.sha(draft["body"])
    row = adapter.prepare(
        draft, signal_id="synthetic-entry-signal", signal_at=AT,
        direction="BULLISH", reservation_reference="synthetic-hold", as_of=AT)
    wire = adapter._wire(row, "PLACE")
    authorization = issue(
        PIN, request_id="entry", wire=wire,
        budget_paise=660000, fee_buffer_paise=10000, at=AT)
    return module, store, transport, adapter, wire, authorization


def authorize(e, *, at=AT, after_claim=None):
    _, _, _, adapter, wire, authorization = e

    def authorizer(db, attempt):
        claim(
            db, authorization, PIN, request_id=attempt["request_id"],
            wire=attempt["wire"], at=at, attempt_id=attempt["attempt_id"])
        if after_claim:
            after_claim()

    adapter.fixture_authorization_claim = authorizer


def counts(e):
    _, store, _, _, _, _ = e
    with store.tx() as db:
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='fixture_authorization_claims'"
        ).fetchone()
        claims = db.execute(
            "SELECT COUNT(*) FROM fixture_authorization_claims"
        ).fetchone()[0] if table else 0
        attempts = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    return claims, attempts


def test_claim_and_attempt_commit_together(execution):
    authorize(execution)
    execution[3].submit("entry")
    assert counts(execution) == (1, 1)
    assert len(execution[2].orders()) == 1


def test_failure_after_claim_rolls_back_both(execution):
    def interrupt():
        raise RuntimeError("SYNTHETIC_AFTER_CLAIM_FAILURE")
    authorize(execution, after_claim=interrupt)
    with pytest.raises(RuntimeError, match="SYNTHETIC_AFTER_CLAIM_FAILURE"):
        execution[3].submit("entry")
    assert counts(execution) == (0, 0)
    assert execution[2].orders() == []


def test_missing_authorization_creates_no_attempt(execution):
    with pytest.raises(ValueError, match="^FIXTURE_AUTHORIZATION_REQUIRED$"):
        execution[3].submit("entry")
    assert counts(execution) == (0, 0)


def test_expired_authorization_creates_no_attempt(execution):
    from datetime import datetime, timedelta
    expired = (datetime.fromisoformat(AT) + timedelta(seconds=10)).isoformat()
    authorize(execution, at=expired)
    with pytest.raises(ValueError, match="^AUTHORIZATION_EXPIRED_OR_FUTURE$"):
        execution[3].submit("entry")
    assert counts(execution) == (0, 0)


def test_concurrent_callers_commit_once(execution):
    authorize(execution)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execution[3].submit, "entry") for _ in range(2)]
        for future in futures:
            future.result(timeout=30)
    assert counts(execution) == (1, 1)
    assert len(execution[2].orders()) == 1


def test_replay_neither_claims_nor_sends_again(execution):
    authorize(execution)
    adapter = execution[3]
    adapter.submit("entry")
    adapter.fixture_authorization_claim = Mock(
        side_effect=AssertionError("Replay must not claim authorization"))
    with patch.object(
        execution[2], "send",
        side_effect=AssertionError("Replay must not send"),
    ):
        assert adapter.submit("entry")["idempotent_replay"] is True
    adapter.fixture_authorization_claim.assert_not_called()
    assert counts(execution) == (1, 1)


def test_live_gate_remains_before_authorizer_and_network(module, tmp_path):
    store = module.Store(tmp_path / "closed.sqlite", PIN["scope"], "LIVE_CLOSED")
    token = Mock(side_effect=AssertionError("No token access"))
    adapter = module.Adapter(store, module.HttpTransport(token))
    authorizer = Mock(side_effect=AssertionError("Live gate must run first"))
    adapter.fixture_authorization_claim = authorizer
    with patch.object(
        module, "build_opener", side_effect=AssertionError("No HTTP access")
    ):
        result = adapter.submit("entry")
    assert result["status"] == "PRODUCTION_MUTATIONS_CLOSED_IN_CODE"
    token.assert_not_called()
    authorizer.assert_not_called()
    assert adapter.status()["attempts"] == []