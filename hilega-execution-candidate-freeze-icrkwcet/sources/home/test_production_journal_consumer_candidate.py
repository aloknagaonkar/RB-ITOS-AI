from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import Mock, patch

import pytest

from production_journal_consumer_candidate import (
    ProductionJournalConsumerCandidate, TABLE,
)
from priced_execution_coordinator_candidate import PricedExecutionCoordinatorCandidate
from test_production_execution_coordinator_candidate import (
    synthetic_scope, env, bound_env, live_case, context, candidate,
    flow, send_receipt,
)
from test_priced_execution_coordinator_candidate import market_bundle
from test_hilega_application_preparation_v1 import append
from hilega_application_preparation_fixtures import PIN

EXIT = "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"


@pytest.fixture
def durable(flow):
    e, mod, adapter, token, state, old, sequence, original = flow
    coordinator = PricedExecutionCoordinatorCandidate(
        e["store"], adapter, PIN, old.authority,
        adapter_module=mod, journal=e["path"],
        capture_provider=lambda: deepcopy(state["snapshot"]),
        market_capture_provider=Mock(
            return_value=market_bundle(e, adapter.store)),
        clock=lambda: state["clock"],
    )
    # A prior acknowledged entry is explicit fixture setup.
    with patch.object(adapter.transport, "check", return_value=None), patch.object(
        adapter.transport, "send",
        side_effect=lambda aid, wire: send_receipt(flow, aid, wire),
    ):
        coordinator.dispatch(sequence)
    state["snapshot"] = deepcopy(original[2])
    consumer = ProductionJournalConsumerCandidate(coordinator)
    baseline = consumer.poll()
    return flow, coordinator, consumer, baseline


def append_exit(durable):
    append(durable[0][0]["path"], [EXIT])


def test_first_use_baselines_without_replaying_history(durable):
    flow, coordinator, consumer, baseline = durable
    assert baseline["status"] == "BASELINED_WAIT_NEXT_FRESH_SIGNAL"
    assert baseline["processed_record_count"] == 0
    with flow[2].store.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1


def test_sell_and_cursor_replay(durable):
    flow, coordinator, consumer, baseline = durable
    append_exit(durable)
    transport = flow[2].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send",
        side_effect=lambda aid, wire: send_receipt(flow, aid, wire),
    ) as send:
        result = consumer.poll()
        replay = consumer.poll()
    assert result["processed_record_count"] == 1
    assert replay["processed_record_count"] == 0
    send.assert_called_once()


def test_lost_cursor_update_recovers_without_second_sell(durable):
    flow, coordinator, consumer, baseline = durable
    append_exit(durable)

    def interrupt(stage):
        raise RuntimeError("SYNTHETIC_DURABLE_CURSOR_LOST")

    transport = flow[2].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send",
        side_effect=lambda aid, wire: send_receipt(flow, aid, wire),
    ):
        with pytest.raises(RuntimeError, match="DURABLE_CURSOR_LOST"):
            consumer.poll(checkpoint=interrupt)
    flow[4]["clock"] += timedelta(hours=2)
    coordinator.capture = Mock(side_effect=AssertionError("No replay capture"))
    coordinator.market_capture = Mock(side_effect=AssertionError("No replay quote"))
    reopened = ProductionJournalConsumerCandidate(coordinator)
    with patch.object(
        transport, "send", side_effect=AssertionError("No second SELL"),
    ):
        assert reopened.poll()["processed_record_count"] == 1
    coordinator.capture.assert_not_called()
    coordinator.market_capture.assert_not_called()


def test_closed_gate_holds_cursor(durable):
    flow, coordinator, consumer, baseline = durable
    append_exit(durable)
    coordinator.capture = Mock(side_effect=AssertionError("No capture behind gate"))
    result = consumer.poll()
    assert result["status"] == "CURSOR_HELD_FOR_RECONCILIATION"
    assert result["cursor_sequence"] == baseline["cursor_sequence"]
    coordinator.capture.assert_not_called()


def test_unknown_sell_holds_cursor_without_resubmitting(durable):
    flow, coordinator, consumer, baseline = durable
    append_exit(durable)
    transport = flow[2].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=TimeoutError("Synthetic response lost"),
    ):
        first = consumer.poll()
    assert first["status"] == "CURSOR_HELD_FOR_RECONCILIATION"
    flow[4]["clock"] += timedelta(hours=2)
    with patch.object(
        transport, "send", side_effect=AssertionError("No unknown-outcome retry"),
    ):
        second = consumer.poll()
    assert second["status"] == "CURSOR_HELD_FOR_RECONCILIATION"
    assert second["cursor_sequence"] == baseline["cursor_sequence"]


def test_concurrent_pollers_submit_sell_once(durable):
    flow, coordinator, consumer, baseline = durable
    append_exit(durable)
    second = ProductionJournalConsumerCandidate(coordinator)
    transport = flow[2].transport
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send",
        side_effect=lambda aid, wire: send_receipt(flow, aid, wire),
    ) as send:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda c: c.poll(), [consumer, second]))
    assert sum(r["processed_record_count"] for r in results) == 1
    send.assert_called_once()


def test_tampered_cursor_blocks(durable):
    store = durable[0][2].store
    with store.tx() as db:
        raw = json.loads(db.execute(
            "SELECT data FROM " + TABLE + " WHERE id=1").fetchone()[0])
        raw["sequence"] = 0
        db.execute("UPDATE " + TABLE + " SET data=?", (json.dumps(raw),))
    with pytest.raises(ValueError, match="CURSOR_SIGNATURE_INVALID"):
        durable[2].poll()
