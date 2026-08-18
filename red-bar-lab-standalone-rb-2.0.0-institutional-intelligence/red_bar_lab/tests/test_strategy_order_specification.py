from __future__ import annotations

from red_bar_lab.ui.strategy_order_specification import build_order_specification


def committee_row(**overrides):
    row = {
        "committee_id": "COM-1",
        "committee_outcome": "COMMITTEE_READY_READ_ONLY",
        "order_preparation_allowed": True,
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "bundle_id": "RSI-BUNDLE-1",
        "signal_id": "RSI-SIGNAL-1",
        "candidate_id": "RSI-CAND-1",
        "role": "ENTRY_1",
        "exchange": "NFO",
        "instrument_token": "12345",
        "instrument_key": "NFO|12345",
        "trading_symbol": "NIFTY26AUG25000CE",
        "expiry": "2026-08-27",
        "strike": 25000.0,
        "lot_size": 75,
        "tick_size": 0.05,
        "quantity": 75,
        "ask": 100.03,
        "ltp": 100.0,
        "required_capital": 7500.0,
        "total_proposed_risk": 300.0,
        "opportunity": {"entry_premium": 100.0, "initial_option_stop": 96.02},
        "admission_priority_rank": 1,
    }
    row.update(overrides)
    return row


def test_ready_candidate_builds_broker_neutral_specification():
    result = build_order_specification({"rows": [committee_row()]})
    row = result["rows"][0]
    assert result["outcome"] == "ORDER_SPEC_READY_READ_ONLY"
    assert row["transaction_intent"] == "BUY_TO_OPEN"
    assert row["order_type"] == "LIMIT"
    assert row["time_in_force"] == "DAY"
    assert row["reference_price_source"] == "ASK"
    assert row["limit_price"] == 100.05
    assert row["protective_stop_trigger"] == 96.0
    assert row["order_quantity"] == 75
    assert row["order_lots"] == 1


def test_ltp_is_used_when_ask_is_missing():
    row = build_order_specification({"rows": [committee_row(ask=None, ltp=100.02)]})["rows"][0]
    assert row["reference_price_source"] == "LTP"
    assert row["limit_price"] == 100.05


def test_non_committee_ready_candidate_waits():
    row = build_order_specification({
        "rows": [committee_row(committee_outcome="WAIT", order_preparation_allowed=False)]
    })["rows"][0]
    assert row["order_specification_outcome"] == "WAIT"
    assert "COMMITTEE_NOT_READY" in row["order_specification_reason"]


def test_quantity_must_be_whole_lot_aligned():
    row = build_order_specification({"rows": [committee_row(quantity=100)]})["rows"][0]
    assert row["order_specification_outcome"] == "WAIT"
    assert "QUANTITY_NOT_WHOLE_LOT_ALIGNED" in row["order_specification_reason"]
    assert row["order_lots"] is None


def test_invalid_protective_stop_waits():
    row = build_order_specification({
        "rows": [committee_row(opportunity={"entry_premium": 100.0, "initial_option_stop": 101.0})]
    })["rows"][0]
    assert row["order_specification_outcome"] == "WAIT"
    assert "PROTECTIVE_STOP_INVALID_OR_UNAVAILABLE" in row["order_specification_reason"]


def test_specification_id_is_deterministic():
    first = build_order_specification({"rows": [committee_row()]})["rows"][0]
    second = build_order_specification({"rows": [committee_row()]})["rows"][0]
    assert first["order_specification_id"] == second["order_specification_id"]


def test_order_specification_remains_read_only():
    result = build_order_specification({"rows": [committee_row()]})
    row = result["rows"][0]
    assert row["broker_payload_created"] is False
    assert row["order_created"] is False
    assert row["order_submitted"] is False
    assert row["persisted"] is False
    assert row["reserved"] is False
    assert row["bundle_consumed"] is False
    assert row["submitted"] is False
