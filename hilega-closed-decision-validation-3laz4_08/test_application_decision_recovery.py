"""Concurrency and recovery tests; temporary synthetic application DBs only."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from application_closed_decision import record_application_decision
from test_fixture_closed_dispatch import (
    prepared, fixture_scope, env, bound_env,
)
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_production_foundation.core import Store


def invoke(store, e):
    return record_application_decision(
        store, e["adapter_store"].path, PIN,
        clock=lambda: e["clock"][0],
    )


def saved_rows(e):
    with e["store"].db() as db:
        return db.execute(
            "SELECT id,data FROM closed_dispatch_decisions ORDER BY id"
        ).fetchall()


def assert_no_transport(e):
    with e["adapter_store"].tx() as db:
        for table in ("attempts", "receipts"):
            assert db.execute(
                "SELECT COUNT(*) FROM " + table
            ).fetchone()[0] == 0


def test_two_callers_commit_one_decision(prepared):
    e, _ = prepared
    adapter_before = e["adapter_store"].path.read_bytes()

    # Construct separate Store objects before launching the callers.
    stores = [Store(e["store"].path), Store(e["store"].path)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(invoke, store, e) for store in stores]
        results = [future.result(timeout=30) for future in futures]

    assert len(saved_rows(e)) == 1
    assert results[0]["decision_id"] == results[1]["decision_id"]
    assert sorted(r["idempotent_replay"] for r in results) == [False, True]
    assert e["adapter_store"].path.read_bytes() == adapter_before
    assert_no_transport(e)


def test_lost_response_after_commit_reopens_without_duplicate(prepared):
    e, _ = prepared
    adapter_before = e["adapter_store"].path.read_bytes()

    class LostResponse(BaseException):
        pass

    def caller():
        invoke(e["store"], e)  # Returns only after the transaction commits.
        raise LostResponse()

    with pytest.raises(LostResponse):
        caller()

    before = saved_rows(e)
    assert len(before) == 1
    reopened = Store(e["store"].path)
    result = invoke(reopened, e)

    assert result["idempotent_replay"] is True
    assert saved_rows(e) == before
    assert e["adapter_store"].path.read_bytes() == adapter_before
    assert_no_transport(e)