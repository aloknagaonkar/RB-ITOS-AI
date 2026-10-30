"""Staged refusal recorder recovery; synthetic temporary databases only."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from unittest.mock import patch

import pytest

from test_production_refusal_candidate import (
    candidate, prepared, verify_candidate, env, bound_env,
    invoke, rows, preparation,
)
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_production_foundation.core import Store


def test_concurrent_callers_record_once(prepared):
    e = prepared
    before = preparation(e)
    broker = e["adapter_store"].path.read_bytes()
    stores = [Store(e["store"].path), Store(e["store"].path)]

    def run(store):
        return candidate.record_application_decision(
            store, e["adapter_store"].path, PIN,
            clock=lambda: e["clock"][0],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, store) for store in stores]
        results = [future.result(timeout=30) for future in futures]

    assert len(rows(e)) == 1
    assert results[0]["decision_id"] == results[1]["decision_id"]
    assert sorted(r["idempotent_replay"] for r in results) == [False, True]
    assert preparation(e) == before
    assert e["adapter_store"].path.read_bytes() == broker


def test_lost_response_after_commit_replays_once(prepared):
    e = prepared

    class LostResponse(BaseException):
        pass

    def caller():
        invoke(e)
        raise LostResponse()

    with pytest.raises(LostResponse):
        caller()
    saved = rows(e)
    assert len(saved) == 1

    reopened = Store(e["store"].path)
    result = candidate.record_application_decision(
        reopened, e["adapter_store"].path, PIN,
        clock=lambda: e["clock"][0],
    )
    assert result["idempotent_replay"] is True
    assert rows(e) == saved


@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_source_read_failure_rolls_back(prepared, fail_at):
    e = prepared
    before = preparation(e)
    original = candidate.read_connection
    calls = []

    def reader(*args, **kwargs):
        calls.append(1)
        if len(calls) == fail_at:
            raise sqlite3.OperationalError("SYNTHETIC_SOURCE_READ_FAILURE")
        return original(*args, **kwargs)

    with patch.object(candidate, "read_connection", reader):
        with pytest.raises(
            sqlite3.OperationalError,
            match="^SYNTHETIC_SOURCE_READ_FAILURE$",
        ):
            invoke(e)
    assert len(calls) == fail_at
    assert rows(e) == []
    assert preparation(e) == before


def test_failure_after_insert_rolls_back(prepared):
    e = prepared
    before = preparation(e)
    original = candidate.record
    reached = []

    def failing_record(*args, **kwargs):
        original(*args, **kwargs)
        reached.append(True)
        raise sqlite3.OperationalError("SYNTHETIC_POST_INSERT_FAILURE")

    with patch.object(candidate, "record", failing_record):
        with pytest.raises(
            sqlite3.OperationalError,
            match="^SYNTHETIC_POST_INSERT_FAILURE$",
        ):
            invoke(e)
    assert reached == [True]
    assert rows(e) == []
    assert preparation(e) == before