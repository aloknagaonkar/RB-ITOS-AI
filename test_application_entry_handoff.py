"""Actual closed adapter handoff using temporary application databases."""
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest

from application_entry_handoff import handoff_entry
from test_hilega_application_preparation_v1 import env, process
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN


def invoke(e, clock=None):
    token = Mock(side_effect=AssertionError("Token must not be accessed"))
    with patch(
        "market_lab.hilega_execution_port_v1.adapter.build_opener",
        side_effect=AssertionError("HTTP must not be opened"),
    ):
        result = handoff_entry(
            e["store"], e["adapter_store"], PIN,
            clock=clock or (lambda: e["clock"][0]),
            token_provider=token,
        )
    token.assert_not_called()
    return result


def no_attempts(e):
    with e["adapter_store"].tx() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0


def test_prepared_entry_reaches_actual_closed_adapter(bound_env):
    e = bound_env
    process(e)
    app_before = e["store"].path.read_bytes()
    request_before = e["adapter_store"].requests()
    result = invoke(e)
    assert result["status"] == "APPLICATION_ENTRY_REACHED_CLOSED_ADAPTER"
    assert result["orders_sent"] is False
    assert e["store"].path.read_bytes() == app_before
    assert e["adapter_store"].requests() == request_before
    no_attempts(e)
    # The installed adapter may append its existing gate-refusal audit event.


def test_stale_preparation_does_not_reach_submit(bound_env):
    e = bound_env
    process(e)
    later = e["clock"][0] + timedelta(minutes=5)
    with patch(
        "application_entry_handoff.Adapter.submit",
        side_effect=AssertionError("Stale preparation must not reach submit"),
    ):
        with pytest.raises(ValueError, match="^ENTRY_PRECONDITIONS_NOT_MET$"):
            invoke(e, clock=lambda: later)
    no_attempts(e)


def test_expiry_during_handoff_does_not_reach_submit(bound_env):
    e = bound_env
    process(e)
    times = iter([
        e["clock"][0],
        e["clock"][0] + timedelta(minutes=5),
    ])
    with patch(
        "application_entry_handoff.Adapter.submit",
        side_effect=AssertionError("Expired evidence must not reach submit"),
    ):
        with pytest.raises(
            ValueError, match="^ENTRY_EVIDENCE_EXPIRED_BEFORE_HANDOFF$"
        ):
            invoke(e, clock=lambda: next(times))
    no_attempts(e)