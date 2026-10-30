from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import pytest

from authorized_journal_consumer import AuthorizedFixtureConsumer
from test_worker_handoff import worker
from test_authorized_attempt import module
from test_automatic_entry_fixture import synthetic_scope, env, bound_env
from test_hilega_application_preparation_v1 import append, BULL
from hilega_application_preparation_fixtures import PIN

EXIT = "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"


@pytest.fixture
def flow(bound_env, module, tmp_path):
    e = bound_env
    store = module.Store(
        tmp_path / "authorized-flow.sqlite", PIN["scope"], "OFFLINE_FIXTURE")
    consumer = AuthorizedFixtureConsumer(
        e["store"], e["adapter_store"].path, store, PIN, e["path"],
        adapter_module=module, clock=lambda: e["clock"][0],
    )
    return e, module, store, consumer


def tick(worker, flow):
    e, _, _, consumer = flow
    return worker.preparation_tick(
        e["source"], e["path"],
        test_handoff=lambda: consumer.poll(
            as_of=e["clock"][0].isoformat()),
    )


def counts(flow):
    _, _, store, _ = flow
    with store.tx() as db:
        attempts = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        exists = db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE name='fixture_authorization_claims'"
        ).fetchone()
        claims = db.execute(
            "SELECT COUNT(*) FROM fixture_authorization_claims"
        ).fetchone()[0] if exists else 0
    return claims, attempts


def orders(flow):
    _, mod, store, _ = flow
    return mod.FixtureTransport(store).orders()


def start(worker, flow):
    append(flow[0]["path"], [BULL])
    tick(worker, flow)
    assert counts(flow) == (1, 1)


def test_worker_authorized_entry_and_cursor_replay(worker, flow):
    start(worker, flow)
    result = tick(worker, flow)
    assert result["execution_handoff"]["processed_record_count"] == 0
    assert counts(flow) == (1, 1)
    assert len(orders(flow)) == 1


def test_lost_result_before_cursor_recovers_without_send(worker, flow):
    e, mod, store, consumer = flow
    append(e["path"], [BULL])
    # Prepare the application without running a handoff.
    worker.preparation_tick(e["source"], e["path"])

    def interrupt(stage):
        raise RuntimeError("SYNTHETIC_CURSOR_INTERRUPTION")

    with pytest.raises(RuntimeError, match="CURSOR_INTERRUPTION"):
        consumer.poll(
            as_of=e["clock"][0].isoformat(), checkpoint=interrupt)
    assert counts(flow) == (1, 1)
    e["clock"][0] += timedelta(minutes=5)
    with patch.object(
        mod.FixtureTransport, "send",
        side_effect=AssertionError("Recovery must not submit"),
    ):
        consumer.poll(as_of=e["clock"][0].isoformat())
    assert counts(flow) == (1, 1)
    assert len(orders(flow)) == 1


@pytest.mark.parametrize("partial", [False, True])
def test_worker_entry_fill_then_authorized_exit(worker, flow, partial):
    start(worker, flow)
    e, mod, store, consumer = flow
    buy = orders(flow)[0]
    quantity = buy["quantity"] - 1 if partial else buy["quantity"]
    transport = mod.FixtureTransport(store)
    transport.fill(buy["order_id"], quantity)
    if partial:
        entry = next(
            r for r in store.requests()
            if r["draft"]["body"]["transaction_type"] == "BUY")
        adapter = mod.Adapter(store, transport)
        # Explicit fake external cancellation setup.
        transport.send(
            "synthetic-external-cancel", adapter._wire(entry, "CANCEL"))
    append(e["path"], [EXIT])
    tick(worker, flow)
    sells = [o for o in orders(flow) if o["side"] == "SELL"]
    assert len(sells) == 1
    assert sells[0]["quantity"] == quantity
    assert counts(flow) == (2, 2)
    transport.fill(sells[0]["order_id"], quantity)
    tick(worker, flow)
    assert counts(flow) == (2, 2)
    assert len(orders(flow)) == 2
    assert e["store"].control()["mode"] == "PAUSED"


def test_concurrent_pollers_commit_one_entry(worker, flow):
    e, _, _, consumer = flow
    append(e["path"], [BULL])
    worker.preparation_tick(e["source"], e["path"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(consumer.poll, as_of=e["clock"][0].isoformat())
            for _ in range(2)
        ]
        results = [future.result(timeout=30) for future in futures]
    assert sum(r["processed_record_count"] for r in results) == 1
    assert counts(flow) == (1, 1)
    assert len(orders(flow)) == 1


def test_truncated_journal_blocks_without_new_attempt(worker, flow):
    start(worker, flow)
    e, _, _, consumer = flow
    e["path"].write_text("")
    with pytest.raises(ValueError):
        consumer.poll(as_of=e["clock"][0].isoformat())
    assert counts(flow) == (1, 1)
