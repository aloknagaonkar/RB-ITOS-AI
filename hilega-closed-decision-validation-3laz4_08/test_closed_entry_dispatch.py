"""Closed dispatch against synthetic application DBs; no broker access."""
import importlib.util
from pathlib import Path

import pytest

from test_dispatch_precondition_review import prepared, env, bound_env
from test_hilega_application_preparation_v1 import command

path = Path(__file__).resolve().parent / "closed_entry_dispatch.py"
spec = importlib.util.spec_from_file_location("closed_dispatch_target", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def call(e):
    return module.dispatch_closed(
        e["store"].path, e["adapter_store"].path,
        __import__("hilega_application_preparation_fixtures").PIN,
        as_of=e["clock"][0].isoformat(),
    )


def database_bytes(e):
    return (
        e["store"].path.read_bytes(),
        e["adapter_store"].path.read_bytes(),
    )


def assert_closed(result):
    assert result["status"] == "DISPATCH_REFUSED_LIVE_GATE_CLOSED"
    for field in (
        "database_modified", "transport_attempt_created",
        "broker_reads_performed", "entry_permission",
        "exit_submission_permission", "orders_sent",
        "production_execution_enabled", "reservation_release_permission",
        "production_ready",
    ):
        assert result[field] is False


def test_valid_preparation_is_reviewed_but_not_dispatched(prepared):
    e, _ = prepared
    before = database_bytes(e)
    result = call(e)
    assert result["reference_checks_passed"] is True, result
    assert_closed(result)
    assert database_bytes(e) == before


def test_repeated_closed_dispatch_writes_nothing(prepared):
    e, _ = prepared
    before = database_bytes(e)
    first = call(e)
    second = call(e)
    assert first == second
    assert_closed(second)
    assert database_bytes(e) == before


def test_empty_paused_application_is_refused(bound_env):
    e = bound_env
    command(e["s"], "pause")
    before = database_bytes(e)
    result = call(e)
    assert result["reference_checks_passed"] is False
    assert result["review_reasons"] == ["SINGLE_BOUND_PREPARED_ENTRY_REQUIRED"]
    assert_closed(result)
    assert database_bytes(e) == before


def test_review_cannot_inject_execution_permission(prepared, monkeypatch):
    e, _ = prepared
    before = database_bytes(e)
    monkeypatch.setattr(
        module.review_module, "review",
        lambda *args, **kwargs: dict(
            reference_checks_passed=True, reasons=[],
            entry_permission=True, production_execution_enabled=True,
            orders_sent=True,
        ),
    )
    result = call(e)
    assert_closed(result)
    assert database_bytes(e) == before