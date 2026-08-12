from red_bar_lab.strategy.trade_outcome import (
    benchmark_summary,
    summarize_actionable_models,
)
from red_bar_lab.strategy.signal_view import (
    summarize_completed_signals,
)


def rows():
    actionable = []
    for i in range(10):
        actionable.append({
            "signal_id": "RB-X",
            "status": "CLOSED",
            "exit_model": "FIXED_TARGET" if i < 4 else (
                "RISK_REWARD" if i < 7 else (
                    "TRAILING_STOP" if i < 9 else "BREAK_EVEN_1R"
                )
            ),
            "model_parameter": str(i),
            "points": 10 if i < 8 else (-5 if i == 8 else 0),
            "session_mfe_points": 50,
            "session_mae_points": 3,
            "exit_timestamp": f"2026-08-07T10:{20+i:02d}:00+05:30",
        })
    actionable.append({
        "signal_id": "RB-X",
        "status": "OPEN",
        "exit_model": "EOD_HOLD",
        "model_parameter": "EOD",
        "points": None,
        "session_mfe_points": 55,
        "session_mae_points": 3,
        "exit_timestamp": None,
    })
    return actionable


def test_eod_does_not_keep_signal_open():
    result = summarize_actionable_models(rows())
    assert result["actionable_total"] == 10
    assert result["actionable_closed"] == 10
    assert result["actionable_open"] == 0
    assert result["signal_lifecycle"] == "COMPLETED"


def test_benchmark_is_separate_and_running():
    result = benchmark_summary(
        rows(),
        current_price=90,
        direction="BEARISH",
        entry_price=100,
    )
    assert result["benchmark_status"] == "RUNNING"
    assert result["benchmark_current_points"] == 10


def test_completed_signal_visible_even_when_eod_open():
    signals = [{
        "signal_id": "RB-X",
        "level_type": "NEXT_RED_CANDLE",
        "direction": "BEARISH",
        "cross_timestamp": "2026-08-07T10:00:00+05:30",
        "confirmation_timestamp": "2026-08-07T10:05:00+05:30",
        "underlying_entry": 100,
    }]
    result = summarize_completed_signals(
        signals,
        rows(),
        current_price=90,
    )
    assert len(result) == 1
    assert result[0]["signal_lifecycle"] == "COMPLETED"
    assert result[0]["benchmark_status"] == "RUNNING"
    assert result[0]["actionable_total"] == 10



def test_open_actionable_models_with_none_points_do_not_crash_summary():
    rows = [
        {
            "signal_id": "RB-LIVE",
            "status": "CLOSED",
            "exit_model": "FIXED_TARGET",
            "model_parameter": "20pt",
            "points": 20.0,
        },
        {
            "signal_id": "RB-LIVE",
            "status": "OPEN",
            "exit_model": "FIXED_TARGET",
            "model_parameter": "30pt",
            "points": None,
        },
        {
            "signal_id": "RB-LIVE",
            "status": "OPEN",
            "exit_model": "FIXED_TARGET",
            "model_parameter": "40pt",
            "points": None,
        },
    ]

    result = summarize_actionable_models(rows)

    assert result["actionable_open"] == 2
    assert result["actionable_closed"] == 1
    assert result["best_actionable_points"] == 20.0
    assert result["worst_actionable_points"] == 20.0
    assert result["best_actionable_exit"] == "FIXED_TARGET 20pt"
    assert result["signal_lifecycle"] == "TRADE_OPEN"


def test_all_open_actionable_models_with_none_points_are_safe():
    rows = [
        {
            "signal_id": "RB-LIVE",
            "status": "OPEN",
            "exit_model": "FIXED_TARGET",
            "model_parameter": "20pt",
            "points": None,
        },
        {
            "signal_id": "RB-LIVE",
            "status": "OPEN",
            "exit_model": "RISK_REWARD",
            "model_parameter": "1R",
            "points": None,
        },
    ]

    result = summarize_actionable_models(rows)

    assert result["actionable_open"] == 2
    assert result["best_actionable_points"] is None
    assert result["worst_actionable_points"] is None
    assert result["best_actionable_exit"] is None
    assert result["worst_actionable_exit"] is None
    assert result["signal_lifecycle"] == "TRADE_OPEN"



def test_rb0612_actionable_summary_has_precise_exit_details():
    rows = []
    for i in range(10):
        rows.append({
            "signal_id": "RB-TX",
            "status": "CLOSED",
            "exit_model": "FIXED_TARGET" if i < 4 else (
                "RISK_REWARD" if i < 7 else (
                    "TRAILING_STOP" if i < 9 else "BREAK_EVEN_1R"
                )
            ),
            "model_parameter": str(i),
            "points": float(i + 1),
            "exit_timestamp": f"2026-08-07T10:{20+i:02d}:00+05:30",
            "exit_price": 100.0 + i,
        })
    result = summarize_actionable_models(rows)
    assert result["actionable_completed_at"] == "2026-08-07T10:29:00+05:30"
    assert result["best_actionable_points"] == 10.0
    assert result["best_actionable_exit_time"] == "2026-08-07T10:29:00+05:30"
    assert result["best_actionable_exit_price"] == 109.0
