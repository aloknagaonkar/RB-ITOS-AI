"""Synthetic cursor integrity and concurrent-consumer tests."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from test_fixture_journal_consumer import (
    consumer, entry, synthetic_scope, env, bound_env,
)
from market_lab.hilega_execution_port_v1.adapter import FixtureTransport


def test_tampered_cursor_is_rejected(entry):
    e, execution = entry
    consumer(entry).poll(as_of=e["clock"][0].isoformat())

    with execution.tx() as db:
        value = json.loads(db.execute(
            "SELECT data FROM fixture_dispatch_cursor WHERE id=1"
        ).fetchone()[0])
        value["sequence"] = 0
        db.execute(
            "UPDATE fixture_dispatch_cursor SET data=? WHERE id=1",
            (json.dumps(value),),
        )

    with pytest.raises(ValueError, match="^CURSOR_SIGNATURE_INVALID$"):
        consumer(entry).poll(as_of=e["clock"][0].isoformat())

    assert len(FixtureTransport(execution).orders()) == 1


def test_two_pollers_process_entry_once(entry):
    e, execution = entry
    pollers = [consumer(entry), consumer(entry)]
    at = e["clock"][0].isoformat()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(poller.poll, as_of=at)
            for poller in pollers
        ]
        results = [future.result(timeout=30) for future in futures]

    assert sorted(
        r["processed_record_count"] for r in results
    ) == [0, 1]
    assert all(r["cursor_sequence"] == 1 for r in results)
    assert len(FixtureTransport(execution).orders()) == 1
    with execution.tx() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM attempts"
        ).fetchone()[0] == 1