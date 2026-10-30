"""Staged worker -> actual preparation -> actual closed execution adapter."""
from unittest.mock import Mock, patch

from test_worker_handoff import worker
from test_hilega_application_preparation_v1 import env, append, BULL
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN
from application_entry_handoff import handoff_entry


def callback(e, token):
    def handoff():
        result = handoff_entry(
            e["store"], e["adapter_store"], PIN,
            clock=lambda: e["clock"][0],
            token_provider=token,
        )
        # Adapt the handoff's reporting fields to the worker boundary.
        return dict(result, orders_sent_to_upstox=False)
    return handoff


def assert_no_transport(e):
    with e["adapter_store"].tx() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0


def test_worker_preparation_reaches_closed_adapter(worker, bound_env):
    e = bound_env
    token = Mock(side_effect=AssertionError("No token access"))
    append(e["path"], [BULL])

    with patch(
        "market_lab.hilega_execution_port_v1.adapter.build_opener",
        side_effect=AssertionError("No HTTP calls"),
    ):
        result = worker.preparation_tick(
            e["source"], e["path"], test_handoff=callback(e, token))

    assert result["execution_handoff"]["status"] == (
        "APPLICATION_ENTRY_REACHED_CLOSED_ADAPTER")
    assert result["execution_handoff"]["live_submission_authorized"] is False
    assert len(e["adapter_store"].requests()) == 1
    assert e["store"].control()["mode"] == "PAUSED"
    token.assert_not_called()
    assert_no_transport(e)


def test_repeated_worker_tick_creates_no_execution_attempt(worker, bound_env):
    e = bound_env
    token = Mock(side_effect=AssertionError("No token access"))
    append(e["path"], [BULL])
    handoff = callback(e, token)

    with patch(
        "market_lab.hilega_execution_port_v1.adapter.build_opener",
        side_effect=AssertionError("No HTTP calls"),
    ):
        worker.preparation_tick(e["source"], e["path"], test_handoff=handoff)
        requests_before = e["adapter_store"].requests()
        worker.preparation_tick(e["source"], e["path"], test_handoff=handoff)

    assert e["adapter_store"].requests() == requests_before
    assert len(requests_before) == 1
    token.assert_not_called()
    assert_no_transport(e)