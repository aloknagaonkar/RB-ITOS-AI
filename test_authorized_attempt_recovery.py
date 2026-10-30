"""Existing attempts recover without renewing authorization or resubmitting."""
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from test_authorized_attempt import module, execution, authorize, counts
from test_hilega_consolidated_adapter_v1 import AT


@pytest.mark.parametrize("point,expected_orders,expected_receipts,expected_state", [
    ("AFTER_ATTEMPT_COMMIT", 0, 0, "UNKNOWN"),
    ("AFTER_RECEIPT_COMMIT", 1, 1, "RECONCILIATION_REQUIRED"),
])
def test_reopen_after_authorization_expiry(
    execution, point, expected_orders, expected_receipts, expected_state,
):
    m, store, transport, adapter, _, authorization = execution
    authorize(execution)

    class Interrupted(BaseException):
        pass

    def checkpoint(stage):
        if stage == point:
            raise Interrupted()

    adapter.checkpoint = checkpoint
    with pytest.raises(Interrupted):
        adapter.submit("entry")

    later = datetime.fromisoformat(AT) + timedelta(minutes=5)
    assert later > datetime.fromisoformat(authorization["expires_at"])

    reopened = m.Store(store.path, store.scope, "OFFLINE_FIXTURE")
    recovered_transport = m.FixtureTransport(reopened)
    recovered = m.Adapter(reopened, recovered_transport)
    authorizer = Mock(
        side_effect=ValueError("AUTHORIZATION_EXPIRED_OR_FUTURE"))
    recovered.fixture_authorization_claim = authorizer

    with patch.object(
        recovered_transport, "send",
        side_effect=AssertionError("Recovery/replay must not send"),
    ):
        recovered.recover()
        assert recovered.submit("entry")["idempotent_replay"] is True

    authorizer.assert_not_called()
    assert counts(execution) == (1, 1)
    assert len(transport.orders()) == expected_orders
    status = recovered.status()
    assert status["receipt_count"] == expected_receipts
    row, = status["requests"]
    assert row["state"] == expected_state
    if expected_receipts:
        assert row["order_id"] is not None
        assert row["filled"] is None and row["remaining"] is None
    else:
        assert row["order_id"] is None


def test_timeout_after_acceptance_recovers_without_new_authorization(execution):
    m, store, transport, adapter, _, authorization = execution
    authorize(execution)
    transport.timeout_after = True
    adapter.submit("entry")
    assert adapter.status()["requests"][0]["state"] == "UNKNOWN"

    later = datetime.fromisoformat(AT) + timedelta(minutes=5)
    assert later > datetime.fromisoformat(authorization["expires_at"])
    reopened = m.Store(store.path, store.scope, "OFFLINE_FIXTURE")
    recovered_transport = m.FixtureTransport(reopened)
    recovered = m.Adapter(reopened, recovered_transport)
    authorizer = Mock(side_effect=AssertionError("No renewed authorization"))
    recovered.fixture_authorization_claim = authorizer

    with patch.object(
        recovered_transport, "send",
        side_effect=AssertionError("Unknown outcome must not resubmit"),
    ):
        recovered.recover()
        assert recovered.submit("entry")["idempotent_replay"] is True

    authorizer.assert_not_called()
    assert counts(execution) == (1, 1)
    assert len(transport.orders()) == 1
    row, = recovered.status()["requests"]
    assert row["state"] == "UNKNOWN"
    assert row["order_id"] is None