"""Installed Source -> installed fake execution adapter."""
from pathlib import Path

import pytest

from automatic_entry_fixture import run_entry_fixture
from test_hilega_application_preparation_v1 import env, process
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_execution_port_v1.adapter import Store


@pytest.fixture(autouse=True)
def synthetic_scope(monkeypatch):
    monkeypatch.setitem(PIN, "scope", "FIXTURE:AUTOMATIC-ENTRY")


@pytest.fixture
def entry(bound_env, tmp_path):
    e = bound_env
    process(e)
    execution = Store(
        tmp_path / "execution.sqlite", PIN["scope"], "OFFLINE_FIXTURE")
    return e, execution


def run(entry, **kwargs):
    e, execution = entry
    return run_entry_fixture(
        e["store"].path, e["adapter_store"].path, execution, PIN,
        as_of=e["clock"][0].isoformat(), **kwargs,
    )


def application_bytes(entry):
    e, _ = entry
    return e["store"].path.read_bytes(), e["adapter_store"].path.read_bytes()


def test_prepared_entry_submits_once_and_acknowledges(entry):
    before = application_bytes(entry)
    result = run(entry)
    assert result["attempt_count"] == 1
    assert result["receipt_count"] == 1
    assert result["fixture_order_count"] == 1
    assert result["acknowledged_order_reference_present"] is True
    assert application_bytes(entry) == before


def test_repeated_entry_does_not_submit_twice(entry):
    run(entry)
    result = run(entry)
    assert result["attempt_count"] == 1
    assert result["fixture_order_count"] == 1
    assert result["receipt_count"] == 1


@pytest.mark.parametrize("accepted", [False, True])
def test_timeout_never_resubmits(entry, accepted):
    first = run(
        entry, timeout_before=not accepted, timeout_after=accepted)
    assert first["request_state"] == "UNKNOWN"
    result = run(entry)
    assert result["attempt_count"] == 1
    assert result["fixture_order_count"] == int(accepted)
    assert result["acknowledged_order_reference_present"] is False


@pytest.mark.parametrize("point,orders,receipt", [
    ("AFTER_ATTEMPT_COMMIT", 0, 0),
    ("AFTER_RECEIPT_COMMIT", 1, 1),
])
def test_restart_after_interruption_never_duplicates(entry, point, orders, receipt):
    class Interrupted(BaseException):
        pass

    def checkpoint(stage):
        if stage == point:
            raise Interrupted()

    with pytest.raises(Interrupted):
        run(entry, checkpoint=checkpoint)

    e, execution = entry
    # Reopen the actual persisted fixture execution database.
    reopened = Store(execution.path, PIN["scope"], "OFFLINE_FIXTURE")
    result = run((e, reopened))
    assert result["attempt_count"] == 1
    assert result["fixture_order_count"] == orders
    assert result["receipt_count"] == receipt
    assert result["orders_sent_to_upstox"] is False