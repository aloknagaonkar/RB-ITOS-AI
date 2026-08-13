from __future__ import annotations

from types import SimpleNamespace

from red_bar_lab.execution.trend_automation import TrendAwareDatabaseProxy
from red_bar_lab.storage.database import RedBarDatabase


def _trend():
    return SimpleNamespace(
        ready=True,
        close=24500.0,
        ema10=24510.0,
        timestamp="2026-08-13T10:00:00+05:30",
        reason="READY",
    )


def _database(tmp_path):
    db = RedBarDatabase(tmp_path / "reentry.db")
    db.initialize()
    db.ensure_paper_execution_account(
        account_id="PAPER-STD",
        account_name="Reentry Test",
        initial_capital=100000.0,
    )
    proxy = TrendAwareDatabaseProxy(db, _trend)
    return db, proxy


def _order(order_id):
    return {
        "order_id": order_id,
        "account_id": "PAPER-STD",
        "signal_id": "SIG-SAME-REENTRY",
        "market_data_provider": "ZERODHA",
        "execution_provider": "PAPER",
        "execution_mode": "PAPER",
        "underlying_name": "NIFTY 50",
        "underlying_price_entry": 24500.0,
        "instrument_token": 4242,
        "exchange": "NFO",
        "tradingsymbol": "NIFTY24500CE",
        "option_type": "CE",
        "strike": 24500.0,
        "expiry": "2026-08-13",
        "lot_size": 75,
        "side": "BUY",
        "quantity": 75,
        "entry_timestamp": (
            "2026-08-13T10:00:00+05:30"
            if order_id.endswith("1")
            else "2026-08-13T10:30:00+05:30"
        ),
        "entry_price": 100.0,
        "current_price": 100.0,
        "stop_price": 85.0,
        "target1_price": None,
        "target2_price": None,
        "status": "OPEN",
        "entry_reason": "REENTRY_TEST",
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "mfe_points": 0.0,
        "mae_points": 0.0,
    }


def _queue(status="QUALIFIED", reason="READY"):
    return {
        "queue_id": "Q-SIG-SAME-REENTRY-4242",
        "signal_id": "SIG-SAME-REENTRY",
        "trading_date": "2026-08-13",
        "direction": "BULLISH",
        "candidate_rank": 1,
        "candidate_symbol": "NIFTY24500CE",
        "instrument_token": 4242,
        "exchange": "NFO",
        "option_type": "CE",
        "strike": 24500.0,
        "expiry": "2026-08-13",
        "lot_size": 75,
        "quantity": 75,
        "candidate_score": 92.0,
        "selection_score": 88.0,
        "execution_probability_pct": 92.0,
        "expected_value_pct": 0.0,
        "opportunity_score": 90.0,
        "entry_mode": "OPPORTUNITY_EXTENSION",
        "signal_age_seconds": 1200.0,
        "status": status,
        "reason": reason,
        "created_at": "2026-08-13T10:30:00+05:30",
        "updated_at": "2026-08-13T10:30:00+05:30",
    }


def test_same_signal_same_contract_can_insert_again_after_first_order_closed(tmp_path):
    db, proxy = _database(tmp_path)
    db.insert_paper_execution_order(_order("ORD-REENTRY-1"))

    assert proxy.paper_execution_exists_for_candidate(
        signal_id="SIG-SAME-REENTRY",
        account_id="PAPER-STD",
        instrument_token=4242,
    ) is True

    db.close_paper_execution_order(
        order_id="ORD-REENTRY-1",
        exit_timestamp="2026-08-13T10:20:00+05:30",
        exit_price=110.0,
        exit_reason="BULLISH_EMA10_EXIT",
        realized_pnl=750.0,
        mfe_points=15.0,
        mae_points=3.0,
    )

    assert proxy.paper_execution_exists_for_candidate(
        signal_id="SIG-SAME-REENTRY",
        account_id="PAPER-STD",
        instrument_token=4242,
    ) is False

    # Regression: the legacy permanent UNIQUE index used to fail here even
    # though the duplicate gate correctly allowed the CLOSED contract.
    db.insert_paper_execution_order(_order("ORD-REENTRY-2"))
    rows = db.read_paper_execution_orders("PAPER-STD")
    assert len(rows) == 2
    assert {row["order_id"] for row in rows} == {
        "ORD-REENTRY-1",
        "ORD-REENTRY-2",
    }


def test_closed_queue_slot_is_reset_when_same_signal_contract_qualifies_again(tmp_path):
    db, proxy = _database(tmp_path)
    db.upsert_execution_queue_item(_queue())
    db.update_execution_queue_status(
        queue_id="Q-SIG-SAME-REENTRY-4242",
        status="ACTIVE",
        reason="PAPER_POSITION_OPEN",
        order_id="ORD-REENTRY-1",
        executed_at="2026-08-13T10:00:00+05:30",
    )
    db.update_execution_queue_for_order(
        order_id="ORD-REENTRY-1",
        status="CLOSED",
        reason="BULLISH_EMA10_EXIT",
    )

    before = db.read_execution_queue(
        signal_id="SIG-SAME-REENTRY",
        limit=10,
    )[0]
    assert before["status"] == "CLOSED"
    assert before["order_id"] == "ORD-REENTRY-1"

    proxy.upsert_execution_queue_item(
        _queue(status="QUALIFIED", reason="EMA10_TREND_VALID")
    )
    after = db.read_execution_queue(
        signal_id="SIG-SAME-REENTRY",
        limit=10,
    )[0]

    assert after["status"] == "QUALIFIED"
    assert after["reason"] == "EMA10_TREND_VALID"
    assert after["order_id"] is None
    assert after["executed_at"] is None
