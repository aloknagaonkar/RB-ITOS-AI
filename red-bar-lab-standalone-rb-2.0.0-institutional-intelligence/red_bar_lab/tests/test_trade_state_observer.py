import sqlite3

from red_bar_lab.execution.trade_state_observer import (
    TradeLifecycleState,
    classify_trade_status,
    observe_paper_execution_orders,
    observe_trade_state,
)


def _trade(trade_id, status, *, side="CE", entry="2026-08-21T10:00:00+05:30", exit_time=None, updated=None):
    return {
        "trade_id": trade_id,
        "signal_id": f"SIG-{trade_id}",
        "instrument_key": "NIFTY",
        "option_side": side,
        "status": status,
        "entry_timestamp": entry,
        "exit_timestamp": exit_time,
        "updated_at": updated or exit_time or entry,
    }


def test_flat_when_no_orders_exist():
    snapshot = observe_trade_state([])
    assert snapshot.lifecycle_state == TradeLifecycleState.FLAT
    assert snapshot.previous_trade_closed is True
    assert snapshot.can_admit_new_candidate is True


def test_open_order_is_active_and_blocks_candidate():
    snapshot = observe_trade_state([_trade("1", "OPEN")])
    assert snapshot.lifecycle_state == TradeLifecycleState.ACTIVE
    assert snapshot.active_trade.trade_id == "1"
    assert snapshot.previous_trade_closed is False
    assert snapshot.can_admit_new_candidate is False


def test_exit_timestamp_makes_trade_closed_even_with_legacy_open_status():
    snapshot = observe_trade_state(
        [_trade("1", "OPEN", exit_time="2026-08-21T10:30:00+05:30")]
    )
    assert snapshot.lifecycle_state == TradeLifecycleState.CLOSED
    assert snapshot.active_trade is None
    assert snapshot.previous_trade_closed is True
    assert snapshot.can_admit_new_candidate is True


def test_pending_order_blocks_candidate_without_claiming_active_trade():
    snapshot = observe_trade_state([_trade("1", "ENTRY_PENDING", entry=None)])
    assert snapshot.lifecycle_state == TradeLifecycleState.PENDING
    assert snapshot.active_trade is None
    assert snapshot.has_pending_trade is True
    assert snapshot.can_admit_new_candidate is False


def test_rejected_order_does_not_count_as_executed_trade():
    snapshot = observe_trade_state([_trade("1", "REJECTED", entry=None)])
    assert snapshot.lifecycle_state == TradeLifecycleState.FLAT
    assert snapshot.latest_executed_trade is None
    assert snapshot.previous_trade_closed is True


def test_multiple_active_trades_are_reported_as_conflict():
    snapshot = observe_trade_state(
        [
            _trade("1", "OPEN", side="CE", updated="2026-08-21T10:00:00+05:30"),
            _trade("2", "FILLED", side="PE", updated="2026-08-21T10:05:00+05:30"),
        ]
    )
    assert snapshot.lifecycle_state == TradeLifecycleState.CONFLICT
    assert snapshot.active_trade_count == 2
    assert snapshot.conflict_reason == "MULTIPLE_ACTIVE_TRADES"
    assert snapshot.can_admit_new_candidate is False


def test_latest_executed_trade_must_be_closed_before_reentry():
    snapshot = observe_trade_state(
        [
            _trade(
                "1",
                "CLOSED",
                exit_time="2026-08-21T10:20:00+05:30",
                updated="2026-08-21T10:20:00+05:30",
            ),
            _trade("2", "OPEN", updated="2026-08-21T10:25:00+05:30"),
        ]
    )
    assert snapshot.latest_executed_trade.trade_id == "2"
    assert snapshot.previous_trade_closed is False


def test_unknown_status_is_conservatively_pending():
    assert classify_trade_status("BROKER_ACKNOWLEDGED") == TradeLifecycleState.PENDING


def test_database_adapter_is_read_only_and_filters_instrument():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE paper_execution_orders (
            trade_id TEXT,
            signal_id TEXT,
            instrument_key TEXT,
            option_side TEXT,
            status TEXT,
            entry_timestamp TEXT,
            exit_timestamp TEXT,
            updated_at TEXT
        )
        """
    )
    connection.executemany(
        "INSERT INTO paper_execution_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("1", "S1", "NIFTY", "CE", "CLOSED", "10:00", "10:20", "10:20"),
            ("2", "S2", "BANKNIFTY", "PE", "OPEN", "10:25", None, "10:25"),
        ],
    )
    before = connection.total_changes
    snapshot = observe_paper_execution_orders(connection, instrument_key="NIFTY")
    after = connection.total_changes

    assert snapshot.lifecycle_state == TradeLifecycleState.CLOSED
    assert snapshot.latest_executed_trade.trade_id == "1"
    assert before == after
