from datetime import datetime

from scripts.analyze_hilega_wma_gap_capture_failures import (
    classify_loss,
    lifecycle_excursion,
    signal_period,
)


def test_lifecycle_excursion_measures_capture_and_giveback_from_candidate_entry():
    rows = [
        (datetime.fromisoformat("2026-10-01T10:00:00+05:30"), 100.0),
        (datetime.fromisoformat("2026-10-01T10:01:00+05:30"), 120.0),
        (datetime.fromisoformat("2026-10-01T10:02:00+05:30"), 115.0),
    ]
    result = lifecycle_excursion("BULLISH", 100.0, rows, 115.0)
    assert result["candidate_mfe_close_points"] == 20
    assert result["captured_points"] == 15
    assert result["giveback_from_mfe_points"] == 5
    assert result["winner_capture_ratio_pct"] == 75
    assert result["winner_giveback_ratio_pct"] == 25


def loss_row(**overrides):
    row = {
        "captured_points": -10,
        "own_same_exit_5m_candle": False,
        "t1_points_from_candidate_entry": -1,
        "t3_points_from_candidate_entry": -2,
        "t5_points_from_candidate_entry": -3,
        "candidate_mfe_close_points": 1,
    }
    row.update(overrides)
    return row


def test_loss_groups_are_mutually_exclusive():
    assert classify_loss(loss_row(own_same_exit_5m_candle=True)) == "SAME_EXIT_5M_CANDLE"
    assert classify_loss(loss_row()) == "IMMEDIATE_FAILURE_THROUGH_T5"
    assert classify_loss(loss_row(
        t1_points_from_candidate_entry=4,
        t5_points_from_candidate_entry=-2,
    )) == "EARLY_REVERSAL_BY_T5"
    assert classify_loss(loss_row(
        t5_points_from_candidate_entry=5,
    )) == "LATE_GIVEBACK_AFTER_T5"


def test_signal_periods_are_explicit():
    assert signal_period("2026-10-01T09:30:00+05:30") == "OPEN_0915_1029"
    assert signal_period("2026-10-01T11:30:00+05:30") == "MIDDAY_1030_1259"
    assert signal_period("2026-10-01T13:30:00+05:30") == "AFTERNOON_1300_1515"
