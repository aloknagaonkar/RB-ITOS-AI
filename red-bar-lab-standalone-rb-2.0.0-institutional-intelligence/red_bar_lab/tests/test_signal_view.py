from red_bar_lab.strategy.signal_view import (
    sequence_signal_attempts,
    summarize_completed_signals,
)


def test_sequence_numbers_are_per_level_type():
    rows = [
        {"signal_id":"RB-A","level_type":"NEXT_RED_CANDLE","cross_timestamp":"2026-08-07T09:20:00+05:30"},
        {"signal_id":"RB-B","level_type":"FIRST_CANDLE","cross_timestamp":"2026-08-07T09:25:00+05:30"},
        {"signal_id":"RB-C","level_type":"NEXT_RED_CANDLE","cross_timestamp":"2026-08-07T10:10:00+05:30"},
    ]
    result = sequence_signal_attempts(rows)
    by_id = {r["signal_id"]: r for r in result}
    assert by_id["RB-A"]["signal_label"] == "NEXT_RED_CANDLE_1"
    assert by_id["RB-C"]["signal_label"] == "NEXT_RED_CANDLE_2"
    assert by_id["RB-B"]["signal_label"] == "FIRST_CANDLE_1"
    assert by_id["RB-A"]["signal_marker"] == "NRC-1"


def test_completed_signal_summary_has_quality_and_best_worst():
    signals = [{
        "signal_id": "RB-A",
        "level_type": "NEXT_RED_CANDLE",
        "direction": "BEARISH",
        "cross_timestamp": "2026-08-07T10:05:00+05:30",
        "confirmation_timestamp": "2026-08-07T10:15:00+05:30",
        "underlying_entry": 24592.85,
    }]

    trades = []
    model_specs = [
        ("FIXED_TARGET", "20pt", 20.0),
        ("FIXED_TARGET", "30pt", 30.0),
        ("FIXED_TARGET", "40pt", 40.0),
        ("FIXED_TARGET", "50pt", 50.0),
        ("RISK_REWARD", "1R", 22.0),
        ("RISK_REWARD", "2R", 44.0),
        ("RISK_REWARD", "3R", 18.0),
        ("TRAILING_STOP", "10pt", 9.45),
        ("TRAILING_STOP", "20pt", 15.0),
        ("BREAK_EVEN_1R", "BE@1R", 0.0),
    ]
    for index, (exit_model, parameter, points) in enumerate(
        model_specs, start=1
    ):
        trades.append({
            "signal_id": "RB-A",
            "status": "CLOSED",
            "points": points,
            "exit_model": exit_model,
            "model_parameter": parameter,
            "session_mfe_points": 59.95,
            "session_mae_points": 2.85,
            "exit_timestamp": (
                f"2026-08-07T10:{20+index:02d}:00+05:30"
            ),
        })

    # EOD benchmark remains open and must not prevent completion.
    trades.append({
        "signal_id": "RB-A",
        "status": "OPEN",
        "points": None,
        "exit_model": "EOD_HOLD",
        "model_parameter": "EOD",
        "session_mfe_points": 59.95,
        "session_mae_points": 2.85,
        "exit_timestamp": None,
    })

    result = summarize_completed_signals(
        signals,
        trades,
        current_price=24550.0,
    )
    assert len(result) == 1
    item = result[0]
    assert item["signal_label"] == "NEXT_RED_CANDLE_1"
    assert item["actionable_total"] == 10
    assert item["actionable_closed"] == 10
    assert item["actionable_success"] == 9
    assert item["actionable_breakeven"] == 1
    assert item["signal_quality"] == "STRONG_SUCCESS"
    assert item["best_actionable_points"] == 50
    assert item["worst_actionable_points"] == 0
    assert item["mfe_points"] == 59.95
    assert item["mae_points"] == 2.85
    assert item["signal_lifecycle"] == "COMPLETED"
    assert item["benchmark_status"] == "RUNNING"

def test_open_signal_is_not_completed():
    signals = [{"signal_id":"RB-A","level_type":"FIRST_CANDLE","cross_timestamp":"2026-08-07T09:20:00+05:30"}]
    trades = [{"signal_id":"RB-A","status":"OPEN","points":None}]
    assert summarize_completed_signals(signals, trades) == []



def test_quality_visibility_helpers():
    from red_bar_lab.strategy.signal_view import (
        actionable_score,
        quality_band,
        quality_explanation,
        quality_symbol,
    )

    assert quality_explanation(9, 1, 0) == "9W / 1L / 0BE"
    assert actionable_score(9, 10) == "9/10"
    assert quality_band(10) == "GREEN"
    assert quality_band(7) == "YELLOW"
    assert quality_band(4) == "ORANGE"
    assert quality_band(1) == "RED"
    assert quality_symbol(10) == "🟢"
    assert quality_symbol(7) == "🟡"
    assert quality_symbol(4) == "🟠"
    assert quality_symbol(1) == "🔴"



def test_rb0612_trader_helpers():
    from red_bar_lab.strategy.signal_view import (
        current_result,
        priority_label,
        trader_status,
    )
    assert trader_status("TRADE_OPEN", "RUNNING") == "ACTIVE"
    assert trader_status("COMPLETED", "RUNNING") == "BENCHMARK_RUNNING"
    assert trader_status("COMPLETED", "CLOSED") == "CLOSED"
    assert current_result(10) == "PROFIT"
    assert current_result(-1) == "LOSS"
    assert current_result(0) == "BREAKEVEN"
    assert priority_label(10) == "HIGH"
    assert priority_label(7) == "MEDIUM"
    assert priority_label(4) == "LOW"
    assert priority_label(1) == "IGNORE"
