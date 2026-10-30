from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/research_hilega_t5_failure_exits.py"
)
SPEC = importlib.util.spec_from_file_location("hilega_t5_failure", SCRIPT)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def trade(**updates):
    row = {
        "trade_id": "T1",
        "session_date": "2026-10-01",
        "direction": "BULLISH",
        "route": "ROUTE_B",
        "entry_timestamp": "2026-10-01T10:00:00+05:30",
        "entry_price": 100.0,
        "exit_timestamp": "2026-10-01T10:30:00+05:30",
        "exit_price": 110.0,
        "captured_points": 10.0,
        "mfe_points": 20.0,
        "mae_points": -5.0,
        "giveback_points": 10.0,
        "research_split": "IS",
    }
    row.update(updates)
    return row


def bar(timestamp, close, *, direction="BULLISH", **updates):
    row = {
        "trade_id": "T1",
        "session_date": "2026-10-01",
        "timestamp": timestamp,
        "direction": direction,
        "minutes_from_entry": None,
        "close": close,
        "directional_points_close": (
            close - 100.0 if direction == "BULLISH" else 100.0 - close
        ),
        "rsi9": 55.0 if direction == "BULLISH" else 45.0,
        "ema3_rsi": 52.0 if direction == "BULLISH" else 48.0,
        "wma21_rsi": 50.0,
        "rsi9_slope_3": 1.0 if direction == "BULLISH" else -1.0,
        "ema3_rsi_slope_3": 0.8 if direction == "BULLISH" else -0.8,
        "wma21_rsi_slope_3": 0.4 if direction == "BULLISH" else -0.4,
        "ema_minus_wma_slope_3": 0.3 if direction == "BULLISH" else -0.3,
        "is_exit_candle": False,
    }
    row.update(updates)
    return row


def unhealthy_bar(timestamp, close, *, direction="BULLISH"):
    adverse = 1.0 if direction == "BULLISH" else -1.0
    # Reverse ordering/slopes relative to the requested direction.
    return bar(
        timestamp,
        close,
        direction=direction,
        ema3_rsi=48.0 if direction == "BULLISH" else 52.0,
        wma21_rsi=50.0,
        rsi9_slope_3=-adverse,
        ema3_rsi_slope_3=-adverse,
        wma21_rsi_slope_3=-adverse,
        ema_minus_wma_slope_3=-adverse,
    )


def test_good_trade_is_not_exited_at_t5():
    rows = [
        bar("2026-10-01T10:05:00+05:30", 105.0),
        bar("2026-10-01T10:10:00+05:30", 108.0),
    ]
    result = m.candidate_result(
        trade(), rows, "T5_IMMEDIATE_FAILURE"
    )
    assert result["candidate_fired"] is False
    assert result["exit_points"] == 10.0


def test_immediate_failure_uses_exact_t5_actual_close():
    rows = [
        unhealthy_bar("2026-10-01T10:05:00+05:30", 97.0),
        unhealthy_bar("2026-10-01T10:10:00+05:30", 95.0),
    ]
    result = m.candidate_result(
        trade(), rows, "T5_IMMEDIATE_FAILURE"
    )
    assert result["candidate_fired"] is True
    assert result["exit_timestamp"].startswith("2026-10-01T10:05")
    assert result["exit_price"] == 97.0
    assert result["exit_points"] == -3.0
    assert result["valuation_basis"] == "OBSERVED_COMPLETED_FIVE_MINUTE_CLOSE"


def test_two_close_requires_consecutive_failures_and_resets():
    rows = [
        unhealthy_bar("2026-10-01T10:05:00+05:30", 97.0),
        bar("2026-10-01T10:10:00+05:30", 102.0),
        unhealthy_bar("2026-10-01T10:15:00+05:30", 96.0),
        unhealthy_bar("2026-10-01T10:20:00+05:30", 94.0),
    ]
    result = m.candidate_result(
        trade(), rows, "T5_TWO_CLOSE_FAILURE"
    )
    assert result["candidate_fired"] is True
    assert result["exit_timestamp"].startswith("2026-10-01T10:20")
    assert result["exit_points"] == -6.0


def test_one_failed_component_does_not_exit():
    weak_gap_only = bar(
        "2026-10-01T10:05:00+05:30",
        99.0,
        ema_minus_wma_slope_3=-0.2,
    )
    health = m.candle_health(weak_gap_only, "BULLISH")
    assert health["failure_count"] == 1
    assert health["unhealthy"] is False
    result = m.candidate_result(
        trade(), [weak_gap_only], "T5_IMMEDIATE_FAILURE"
    )
    assert result["candidate_fired"] is False


def test_bearish_exit_points_are_direction_normalized():
    bearish_trade = trade(
        direction="BEARISH",
        entry_price=100.0,
        exit_price=95.0,
        captured_points=5.0,
    )
    rows = [unhealthy_bar(
        "2026-10-01T10:05:00+05:30",
        103.0,
        direction="BEARISH",
    )]
    result = m.candidate_result(
        bearish_trade, rows, "T5_IMMEDIATE_FAILURE"
    )
    assert result["candidate_fired"] is True
    assert result["exit_points"] == -3.0


def test_control_has_priority_on_same_exit_candle():
    same_candle_trade = trade(
        exit_timestamp="2026-10-01T10:05:00+05:30",
        exit_price=97.0,
        captured_points=-3.0,
    )
    rows = [unhealthy_bar("2026-10-01T10:05:00+05:30", 97.0)]
    result = m.candidate_result(
        same_candle_trade, rows, "T5_IMMEDIATE_FAILURE"
    )
    assert result["candidate_fired"] is False
    assert result["status"] == "CONTROL_SAME_CANDLE_PRIORITY"
    assert result["exit_points"] == -3.0


def test_split_is_336_144_10_for_490_sessions():
    rows = []
    # Lexically sortable synthetic session strings are sufficient here.
    for index in range(490):
        rows.append(trade(
            trade_id=f"T{index}",
            session_date=f"S{index:03d}",
        ))
    universe = m.assign_splits(rows, forward_sessions=10, is_ratio=0.70)
    assert universe["is"] == 336
    assert universe["oos"] == 144
    assert universe["forward"] == 10


def test_no_bar_after_control_exit_is_eligible():
    target = trade(exit_timestamp="2026-10-01T10:10:00+05:30")
    rows = [
        bar("2026-10-01T10:05:00+05:30", 101.0),
        bar("2026-10-01T10:10:00+05:30", 102.0),
        unhealthy_bar("2026-10-01T10:15:00+05:30", 90.0),
    ]
    eligible = m.eligible_bars(target, rows)
    assert [row["derived_minutes_from_entry"] for row in eligible] == [5, 10]

