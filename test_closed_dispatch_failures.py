"""Closed-dispatch failure handling; synthetic fixtures and mocked reads."""
from copy import deepcopy
import sqlite3

import pytest

from test_closed_entry_dispatch import module, prepared, env, bound_env
from hilega_application_preparation_fixtures import PIN


def call(e):
    return module.dispatch_closed(
        e["store"].path, e["adapter_store"].path,
        PIN, as_of=e["clock"][0].isoformat(),
    )


def contents(e):
    return (
        e["store"].path.read_bytes(),
        e["adapter_store"].path.read_bytes(),
    )


@pytest.mark.parametrize("change", ["control", "stop", "reservation"])
def test_changed_snapshot_stops_review(prepared, monkeypatch, change):
    e, source = prepared
    before = contents(e)
    later = deepcopy(source)

    if change == "control":
        later["control"]["version"] += 1
    elif change == "stop":
        later["stop_state"] = [1, 0]
    else:
        row = next(iter(later["cash_reservations"].values()))
        row["state"] = "UNKNOWN_HOLD_RETAINED"

    snapshots = iter([deepcopy(source), later])
    monkeypatch.setattr(
        module, "read_sources", lambda *a, **k: next(snapshots))
    with pytest.raises(
        ValueError, match="^LOCAL_SOURCES_CHANGED_DURING_DISPATCH_REVIEW$"
    ):
        call(e)
    assert contents(e) == before


@pytest.mark.parametrize("failed_read", [1, 2])
def test_database_read_failure_propagates(prepared, monkeypatch, failed_read):
    e, source = prepared
    before = contents(e)
    calls = []

    def reader(*args, **kwargs):
        calls.append(1)
        if len(calls) == failed_read:
            raise sqlite3.OperationalError("SYNTHETIC_READ_FAILURE")
        return deepcopy(source)

    monkeypatch.setattr(module, "read_sources", reader)
    with pytest.raises(
        sqlite3.OperationalError, match="^SYNTHETIC_READ_FAILURE$"
    ):
        call(e)
    assert len(calls) == failed_read
    assert contents(e) == before


def test_review_exception_propagates_without_write(prepared, monkeypatch):
    e, source = prepared
    before = contents(e)

    def failed_review(*args, **kwargs):
        raise ValueError("SYNTHETIC_REVIEW_FAILURE")

    monkeypatch.setattr(module.review_module, "review", failed_review)
    with pytest.raises(ValueError, match="^SYNTHETIC_REVIEW_FAILURE$"):
        call(e)
    assert contents(e) == before