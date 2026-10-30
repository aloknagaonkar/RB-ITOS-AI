from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import pytest

from authorized_journal_consumer import AuthorizedFixtureConsumer
from test_authorized_consumer_batch import (
    synthetic_scope, env, bound_env, module, worker, flow,
    start, tick, counts, orders, append, BULL, EXIT, PIN,
)


def prepare_exit(worker, flow, partial=False):
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
        transport.send(
            "synthetic-external-cancel", adapter._wire(entry, "CANCEL"))
    append(e["path"], [EXIT])
    worker.preparation_tick(e["source"], e["path"])
    return quantity


def reopened(flow):
    e, mod, store, _ = flow
    new_store = mod.Store(store.path, PIN["scope"], "OFFLINE_FIXTURE")
    return AuthorizedFixtureConsumer(
        e["store"], e["adapter_store"].path,
        new_store, PIN, e["path"],
        adapter_module=mod, clock=lambda: e["clock"][0],
    )


@pytest.mark.parametrize("partial", [False, True])
def test_delayed_exit_restart_after_lost_cursor(worker, flow, partial):
    quantity = prepare_exit(worker, flow, partial)
    e, mod, store, consumer = flow

    def interrupt(stage):
        raise RuntimeError("SYNTHETIC_EXIT_CURSOR_LOST")

    with pytest.raises(RuntimeError, match="EXIT_CURSOR_LOST"):
        consumer.poll(
            as_of=e["clock"][0].isoformat(), checkpoint=interrupt)
    assert counts(flow) == (2, 2)
    e["clock"][0] += timedelta(hours=2)
    restarted = reopened(flow)
    with patch.object(
        mod.FixtureTransport, "send",
        side_effect=AssertionError("Restart must not submit"),
    ):
        result = restarted.poll(as_of=e["clock"][0].isoformat())
        replay = restarted.poll(as_of=e["clock"][0].isoformat())
    assert result["processed_record_count"] == 1
    assert replay["processed_record_count"] == 0
    sells = [o for o in orders(flow) if o["side"] == "SELL"]
    assert len(sells) == 1
    assert sells[0]["quantity"] == quantity
    assert counts(flow) == (2, 2)


def test_lost_sell_response_and_cursor_remain_unknown(worker, flow):
    prepare_exit(worker, flow)
    e, mod, store, consumer = flow
    original_send = mod.FixtureTransport.send

    def lose_sell_response(self, attempt_id, wire):
        if wire.get("body", {}).get("transaction_type") == "SELL":
            self.timeout_after = True
        return original_send(self, attempt_id, wire)

    def interrupt(stage):
        raise RuntimeError("SYNTHETIC_UNKNOWN_EXIT_CURSOR_LOST")

    with patch.object(
        mod.FixtureTransport, "send", new=lose_sell_response,
    ):
        with pytest.raises(RuntimeError, match="UNKNOWN_EXIT_CURSOR_LOST"):
            consumer.poll(
                as_of=e["clock"][0].isoformat(), checkpoint=interrupt)

    assert counts(flow) == (2, 2)
    e["clock"][0] += timedelta(hours=2)
    with patch.object(
        mod.FixtureTransport, "send",
        side_effect=AssertionError("Unknown outcome must not resubmit"),
    ):
        reopened(flow).poll(as_of=e["clock"][0].isoformat())

    sellers = [
        r for r in store.requests()
        if r["draft"]["body"]["transaction_type"] == "SELL"
    ]
    assert len(sellers) == 1
    assert sellers[0]["state"] == "UNKNOWN"
    assert counts(flow) == (2, 2)
    assert len([o for o in orders(flow) if o["side"] == "SELL"]) == 1


def test_concurrent_exit_pollers_submit_once(worker, flow):
    prepare_exit(worker, flow)
    e, _, _, consumer = flow
    second = reopened(flow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(c.poll, as_of=e["clock"][0].isoformat())
            for c in (consumer, second)
        ]
        results = [future.result(timeout=30) for future in futures]
    assert sum(r["processed_record_count"] for r in results) == 1
    assert counts(flow) == (2, 2)
    assert len([o for o in orders(flow) if o["side"] == "SELL"]) == 1


def test_stale_new_entry_cannot_create_attempt(worker, flow):
    e, _, _, consumer = flow
    append(e["path"], [BULL])
    worker.preparation_tick(e["source"], e["path"])
    e["clock"][0] += timedelta(minutes=5)
    with pytest.raises(ValueError, match="FRESH_ENTRY_PRECONDITIONS_REQUIRED"):
        consumer.poll(as_of=e["clock"][0].isoformat())
    assert counts(flow) == (0, 0)
    assert orders(flow) == []
