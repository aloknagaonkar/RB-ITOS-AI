from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from red_bar_lab.execution.checkpoint import TradeCheckpointService

IST = ZoneInfo("Asia/Kolkata")


class FakeDatabase:
    def __init__(self, orders, marks):
        self.orders = orders
        self.marks = marks
        self.checkpoints = {}

    def read_paper_execution_orders(self, account_id):
        return list(self.orders)

    def read_paper_execution_marks(self, order_id):
        return list(self.marks.get(order_id, []))

    def read_paper_trade_checkpoint(self, *, order_id, horizon_minutes):
        return self.checkpoints.get((order_id, horizon_minutes))

    def upsert_paper_trade_checkpoint(self, row):
        key = (row["order_id"], row["horizon_minutes"])
        self.checkpoints.setdefault(key, dict(row))


def _order(entry_at, **overrides):
    row = {
        "order_id": "PAPER-1",
        "account_id": "PAPER-STD",
        "signal_id": "RSI7-TEST",
        "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
        "evaluation_horizon_minutes": 15,
        "entry_timestamp": entry_at.isoformat(),
        "entry_price": 100.0,
        "current_price": 110.0,
        "stop_price": 102.0,
        "status": "OPEN",
        "exit_timestamp": None,
        "exit_price": None,
    }
    row.update(overrides)
    return row


def test_checkpoint_captures_first_mark_at_or_after_horizon():
    entry = datetime(2026, 8, 17, 10, 0, tzinfo=IST)
    db = FakeDatabase([_order(entry)], {"PAPER-1": [
        {"timestamp": (entry + timedelta(minutes=5)).isoformat(), "price": 104.0},
        {"timestamp": (entry + timedelta(minutes=15)).isoformat(), "price": 109.0},
        {"timestamp": (entry + timedelta(minutes=16)).isoformat(), "price": 112.0},
    ]})
    result = TradeCheckpointService(db, account_id="PAPER-STD").capture_due(
        now=entry + timedelta(minutes=16)
    )
    assert result.captured == 1
    checkpoint = db.checkpoints[("PAPER-1", 15)]
    assert checkpoint["checkpoint_price"] == 109.0
    assert checkpoint["return_pct"] == 9.0
    assert checkpoint["mfe_points"] == 9.0
    assert checkpoint["mae_points"] == 0.0
    assert checkpoint["peak_price"] == 109.0
    assert checkpoint["protected_stop_price"] == 102.0
    assert checkpoint["position_status_at_checkpoint"] == "OPEN"


def test_checkpoint_is_idempotent():
    entry = datetime(2026, 8, 17, 10, 0, tzinfo=IST)
    db = FakeDatabase([_order(entry)], {"PAPER-1": []})
    service = TradeCheckpointService(db, account_id="PAPER-STD")
    first = service.capture_due(now=entry + timedelta(minutes=15))
    second = service.capture_due(now=entry + timedelta(minutes=30))
    assert first.captured == 1
    assert second.captured == 0
    assert len(db.checkpoints) == 1


def test_closed_after_horizon_was_open_at_checkpoint():
    entry = datetime(2026, 8, 17, 10, 0, tzinfo=IST)
    db = FakeDatabase([_order(
        entry,
        status="CLOSED",
        exit_timestamp=(entry + timedelta(minutes=20)).isoformat(),
        exit_price=108.0,
    )], {"PAPER-1": [
        {"timestamp": (entry + timedelta(minutes=15)).isoformat(), "price": 107.0}
    ]})
    TradeCheckpointService(db, account_id="PAPER-STD").capture_due(
        now=entry + timedelta(minutes=25)
    )
    checkpoint = db.checkpoints[("PAPER-1", 15)]
    assert checkpoint["position_status_at_checkpoint"] == "OPEN"
    assert checkpoint["captured_order_status"] == "CLOSED"


def test_closed_before_horizon_was_closed_at_checkpoint():
    entry = datetime(2026, 8, 17, 10, 0, tzinfo=IST)
    db = FakeDatabase([_order(
        entry,
        status="CLOSED",
        exit_timestamp=(entry + timedelta(minutes=10)).isoformat(),
        exit_price=95.0,
        current_price=95.0,
    )], {"PAPER-1": [
        {"timestamp": (entry + timedelta(minutes=10)).isoformat(), "price": 95.0}
    ]})
    TradeCheckpointService(db, account_id="PAPER-STD").capture_due(
        now=entry + timedelta(minutes=15)
    )
    checkpoint = db.checkpoints[("PAPER-1", 15)]
    assert checkpoint["position_status_at_checkpoint"] == "CLOSED"
    assert checkpoint["checkpoint_price"] == 95.0


def test_future_checkpoint_is_not_captured():
    entry = datetime(2026, 8, 17, 10, 0, tzinfo=IST)
    db = FakeDatabase([_order(entry)], {"PAPER-1": []})
    result = TradeCheckpointService(db, account_id="PAPER-STD").capture_due(
        now=entry + timedelta(minutes=14, seconds=59)
    )
    assert result.captured == 0
    assert not db.checkpoints
