from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/research_hilega_early_risk_refinement.py"
)
SPEC = importlib.util.spec_from_file_location("hilega_early_risk", SCRIPT)
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
        "exit_price": 90.0,
        "captured_points": -10.0,
        "mfe_points": 4.0,
        "mae_points": -12.0,
        "giveback_points": 14.0,
        "evidence_block": "DEVELOPMENT_BLOCK_1",
    }
    row.update(updates)
    return row


def bar(minute, close, *, direction="BULLISH", mfe=2.0, failures=()):
    sign = 1.0 if direction == "BULLISH" else -1.0
    values = {
        "trade_id": "T1",
        "session_date": "2026-10-01",
        "timestamp": f"2026-10-01T10:{minute:02d}:00+05:30",
        "direction": direction,
        "minutes_from_entry": minute,
        "close": close,
        "directional_points_close": (
            close - 100.0 if direction == "BULLISH" else 100.0 - close
        ),
        "mfe_points": mfe,
        "rsi9": 55.0 if direction == "BULLISH" else 45.0,
        "ema3_rsi": 52.0 if direction == "BULLISH" else 48.0,
        "wma21_rsi": 50.0,
        "rsi9_slope_3": sign,
        "ema3_rsi_slope_3": sign,
        "wma21_rsi_slope_3": sign,
        "ema_minus_wma_slope_3": sign,
        "is_exit_candle": False,
    }
    if "EMA_WMA_ORDER" in failures:
        values["ema3_rsi"] = 48.0 if direction == "BULLISH" else 52.0
    if "RSI_SLOPE" in failures:
        values["rsi9_slope_3"] = -sign
    if "EMA_SLOPE" in failures:
        values["ema3_rsi_slope_3"] = -sign
    if "WMA_SLOPE" in failures:
        values["wma21_rsi_slope_3"] = -sign
    if "GAP_EXPANSION" in failures:
        values["ema_minus_wma_slope_3"] = -sign
    return values


ALL_FAILURES = (
    "EMA_WMA_ORDER", "RSI_SLOPE", "EMA_SLOPE", "WMA_SLOPE",
    "GAP_EXPANSION",
)


def test_candidate_a_requires_exact_t5_four_failures_and_mfe_below_five():
    rows = [bar(5, 98.0, mfe=4.9, failures=ALL_FAILURES[:4])]
    result = m.candidate_result(trade(), rows, "A_T5_SEVERE_FAILURE")
    assert result["candidate_fired"] is True
    assert result["signal_minutes_from_entry"] == 5
    assert result["exit_points"] == -2.0

    not_severe = [bar(5, 98.0, mfe=5.0, failures=ALL_FAILURES)]
    result = m.candidate_result(
        trade(), not_severe, "A_T5_SEVERE_FAILURE"
    )
    assert result["candidate_fired"] is False


def test_candidate_b_requires_failure_at_both_t5_and_t10():
    rows = [
        bar(5, 99.0, failures=ALL_FAILURES[:2]),
        bar(10, 98.0, mfe=8.0, failures=ALL_FAILURES[2:4]),
    ]
    result = m.candidate_result(
        trade(), rows, "B_T5_T10_PERSISTENT_FAILURE"
    )
    assert result["candidate_fired"] is True
    assert result["signal_minutes_from_entry"] == 10

    recovered = [rows[0], bar(10, 101.0, mfe=8.0)]
    result = m.candidate_result(
        trade(), recovered, "B_T5_T10_PERSISTENT_FAILURE"
    )
    assert result["candidate_fired"] is False


def test_candidate_c_requires_price_order_gap_and_wma_failure():
    required = ("EMA_WMA_ORDER", "WMA_SLOPE", "GAP_EXPANSION")
    rows = [bar(5, 99.0, mfe=3.0, failures=required)]
    result = m.candidate_result(
        trade(), rows, "C_EARLY_PRICE_STRUCTURE_FAILURE"
    )
    assert result["candidate_fired"] is True
    assert result["signal_minutes_from_entry"] == 5

    missing_wma = [bar(5, 99.0, mfe=3.0, failures=required[:1] + required[2:])]
    result = m.candidate_result(
        trade(), missing_wma, "C_EARLY_PRICE_STRUCTURE_FAILURE"
    )
    assert result["candidate_fired"] is False


def test_wma_flat_zone_is_neutral_for_bullish_and_bearish():
    assert m.directional_wma_state(0.10, "BULLISH") == "FLAT_WAIT"
    assert m.directional_wma_state(-0.10, "BULLISH") == "FLAT_WAIT"
    assert m.directional_wma_state(0.10, "BEARISH") == "FLAT_WAIT"
    assert m.directional_wma_state(-0.10, "BEARISH") == "FLAT_WAIT"
    assert m.directional_wma_state(0.11, "BULLISH") == "SUPPORTING"
    assert m.directional_wma_state(-0.11, "BULLISH") == "OPPOSING"
    assert m.directional_wma_state(-0.11, "BEARISH") == "SUPPORTING"
    assert m.directional_wma_state(0.11, "BEARISH") == "OPPOSING"


def test_flat_wma_does_not_increment_failure_count():
    row = bar(
        5,
        99.0,
        failures=("EMA_WMA_ORDER", "RSI_SLOPE"),
    )
    row["wma21_rsi_slope_3"] = 0.05
    health = m.candle_health(row, "BULLISH")
    assert health["wma_state"] == "FLAT_WAIT"
    assert health["wma_flat_wait"] is True
    assert health["wma_slope_opposing"] is False
    assert health["failure_count"] == 2
    assert "WMA_SLOPE_OPPOSING" not in health["failure_reasons"]


def test_candidate_c_cannot_exit_on_flat_wma():
    row = bar(
        5,
        98.0,
        mfe=3.0,
        failures=("EMA_WMA_ORDER", "GAP_EXPANSION"),
    )
    row["wma21_rsi_slope_3"] = 0.0
    result = m.candidate_result(
        trade(), [row], "C_EARLY_PRICE_STRUCTURE_FAILURE"
    )
    assert result["candidate_fired"] is False


def test_flat_at_t5_can_improve_to_supporting_at_t10_without_exit():
    t5 = bar(5, 99.0, mfe=3.0, failures=("EMA_WMA_ORDER", "RSI_SLOPE"))
    t5["wma21_rsi_slope_3"] = 0.04
    t10 = bar(10, 108.0, mfe=12.0)
    t10["wma21_rsi_slope_3"] = 0.21
    assert m.candle_health(t5, "BULLISH")["wma_state"] == "FLAT_WAIT"
    assert m.candle_health(t10, "BULLISH")["wma_state"] == "SUPPORTING"
    for policy in m.POLICIES[1:]:
        result = m.candidate_result(trade(), [t5, t10], policy)
        assert result["candidate_fired"] is False


def test_no_candidate_can_use_a_bar_after_t10():
    rows = [bar(15, 85.0, mfe=3.0, failures=ALL_FAILURES)]
    assert m.eligible_checkpoints(trade(), rows) == []
    for policy in m.POLICIES[1:]:
        result = m.candidate_result(trade(), rows, policy)
        assert result["candidate_fired"] is False


def test_causal_running_mfe_blocks_late_candidate_even_if_close_is_negative():
    rows = [bar(5, 98.0, mfe=10.0, failures=ALL_FAILURES)]
    result = m.candidate_result(
        trade(), rows, "C_EARLY_PRICE_STRUCTURE_FAILURE"
    )
    assert result["candidate_fired"] is False


def test_bearish_points_are_direction_normalized():
    bearish = trade(direction="BEARISH", exit_price=110.0)
    rows = [bar(5, 102.0, direction="BEARISH", failures=ALL_FAILURES)]
    result = m.candidate_result(bearish, rows, "A_T5_SEVERE_FAILURE")
    assert result["candidate_fired"] is True
    assert result["exit_points"] == -2.0


def test_control_exit_has_same_candle_priority():
    target = trade(
        exit_timestamp="2026-10-01T10:05:00+05:30",
        exit_price=98.0,
        captured_points=-2.0,
    )
    result = m.candidate_result(
        target,
        [bar(5, 98.0, failures=ALL_FAILURES)],
        "A_T5_SEVERE_FAILURE",
    )
    assert result["candidate_fired"] is False
    assert result["status"] == "CONTROL_SAME_CANDLE_PRIORITY"


def test_outcome_labels_make_good_and_bad_trade_effect_explicit():
    assert m.outcome_label(-20.0, -5.0, True) == (
        "BAD_TRADE_CORRECTLY_EXITED_EARLY"
    )
    assert m.outcome_label(-20.0, -20.0, False) == "BAD_TRADE_NOT_DETECTED"
    assert m.outcome_label(30.0, 30.0, False) == "GOOD_TRADE_RETAINED"
    assert m.outcome_label(30.0, -5.0, True) == (
        "GOOD_TRADE_WRONGLY_EXITED_EARLY"
    )


def test_490_sessions_are_480_development_plus_10_observed():
    rows = [
        trade(trade_id=f"T{index}", session_date=f"S{index:03d}")
        for index in range(490)
    ]
    universe = m.assign_evidence_blocks(rows, observed_forward_sessions=10)
    assert universe["development_sessions"] == 480
    assert universe["development_block_1"] == 160
    assert universe["development_block_2"] == 160
    assert universe["development_block_3"] == 160
    assert universe["observed_forward_sessions"] == 10
    assert universe["new_untouched_confirmation_sessions"] == 0


def test_simulation_marks_plus20_move_destroyed_by_early_exit():
    target = trade(captured_points=25.0, exit_price=125.0, mfe_points=40.0)
    rows = [bar(5, 98.0, mfe=3.0, failures=ALL_FAILURES)]
    result = m.simulate([target], {"T1": rows})[0]
    assert result["candidate_a_plus20_move_destroyed"] is True
    assert result["candidate_a_outcome_label"] == (
        "GOOD_TRADE_WRONGLY_EXITED_EARLY"
    )
