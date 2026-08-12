from red_bar_lab.strategy.trade_outcome import (
    classify_trade_result,
    decorate_trade_row,
    summarize_signal_trade_models,
)


def test_classify_trade_result():
    assert classify_trade_result(20) == "WIN"
    assert classify_trade_result(-5) == "LOSS"
    assert classify_trade_result(0) == "BREAKEVEN"
    assert classify_trade_result(None) == "UNKNOWN"


def test_decorate_trade_row_adds_result():
    row = {"status": "CLOSED", "points": 12.5}
    decorated = decorate_trade_row(row)
    assert decorated["trade_result"] == "WIN"
    assert decorated["status"] == "CLOSED"


def test_signal_summary_separates_state_and_result():
    rows = [
        {
            "signal_id": "SIG-1",
            "level_type": "NEXT_RED_CANDLE",
            "direction": "BEARISH",
            "entry_timestamp": "2026-08-07T10:15:00+05:30",
            "entry_price": 24592.85,
            "status": "CLOSED",
            "points": 20,
        },
        {
            "signal_id": "SIG-1",
            "level_type": "NEXT_RED_CANDLE",
            "direction": "BEARISH",
            "entry_timestamp": "2026-08-07T10:15:00+05:30",
            "entry_price": 24592.85,
            "status": "CLOSED",
            "points": -5,
        },
        {
            "signal_id": "SIG-1",
            "level_type": "NEXT_RED_CANDLE",
            "direction": "BEARISH",
            "entry_timestamp": "2026-08-07T10:15:00+05:30",
            "entry_price": 24592.85,
            "status": "CLOSED",
            "points": 0,
        },
    ]
    result = summarize_signal_trade_models(rows)[0]
    assert result["trade_models"] == 3
    assert result["winning_models"] == 1
    assert result["losing_models"] == 1
    assert result["breakeven_models"] == 1
    assert result["signal_lifecycle"] == "COMPLETED"



def test_decorated_row_contains_business_outcome_and_points_gained():
    row = {
        "status": "CLOSED",
        "points": 18.75,
    }
    result = decorate_trade_row(row)
    assert result["trade_result"] == "WIN"
    assert result["trade_success"] == "SUCCESS"
    assert result["points_gained"] == 18.75


def test_failed_trade_business_outcome():
    row = {
        "status": "CLOSED",
        "points": -7.5,
    }
    result = decorate_trade_row(row)
    assert result["trade_result"] == "LOSS"
    assert result["trade_success"] == "FAILED"
    assert result["points_gained"] == -7.5
