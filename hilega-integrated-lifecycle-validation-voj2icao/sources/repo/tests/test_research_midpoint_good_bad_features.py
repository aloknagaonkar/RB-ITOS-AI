from datetime import datetime, timedelta

from scripts.research_midpoint_good_bad_features import (
    build_daily_context,
    directional_vwap,
    feature_row,
    label_trade,
)


def test_labels_are_explicit_and_do_not_convert_unresolved_to_bad():
    assert label_trade({"plus20": True}) == "GOOD_PLUS20_PROVED"
    assert label_trade({
        "plus20": False,
        "selected_exit_policy": "STRUCTURAL_BASELINE",
        "selected_exit_points": -20,
    }) == "BAD_UNPROVED_STRUCTURAL_LOSS"
    assert label_trade({
        "plus20": False,
        "selected_exit_policy": "STRUCTURAL_BASELINE",
        "selected_exit_points": None,
    }) == "UNRESOLVED"


def test_directional_vwap_orients_both_directions_favourably():
    row = {"close": 110, "vwap": 100}
    assert directional_vwap("BULLISH", row) == 10
    assert directional_vwap("BEARISH", row) == -10


def test_atr_uses_only_prior_completed_sessions():
    sessions = {}
    start = datetime.fromisoformat("2026-01-01T09:15:00+05:30")
    for offset in range(12):
        day = (start + timedelta(days=offset)).date().isoformat()
        sessions[day] = {
            "block": "TEST",
            "underlying": {
                f"{day}T09:15:00+05:30": {
                    "open": 100, "high": 105, "low": 95, "close": 100,
                }
            },
        }
    context = build_daily_context(sessions)
    assert context["2026-01-11"]["atr10_prior_sessions"] is None
    assert context["2026-01-12"]["atr10_prior_sessions"] == 10


def test_checkpoint_after_exit_is_missing_not_forward_filled():
    day = "2026-01-12"
    entry = datetime.fromisoformat(day + "T09:30:00+05:30")
    underlying = {}
    futures = {}
    for minute in range(31):
        moment = datetime.fromisoformat(day + "T09:15:00+05:30") + timedelta(minutes=minute)
        underlying[moment.isoformat()] = {
            "open": 100, "high": 101, "low": 99, "close": 100,
        }
        futures[moment.isoformat()] = {
            "close": 110, "vwap": 109, "volume": 10,
        }
    trade = {
        "block": "TEST", "session_date": day, "family": "E",
        "direction": "BULLISH", "entry_timestamp": entry.isoformat(),
        "entry_price": 100, "reference_high": 99, "reference_low": 90,
        "midpoint": 94.5, "original_boundary": 99, "plus20": False,
        "plus20_timestamp": "", "selected_exit_policy": "STRUCTURAL_BASELINE",
        "selected_exit_timestamp": (entry + timedelta(minutes=2)).isoformat(),
        "selected_exit_points": -5,
    }
    row = feature_row(
        trade=trade, segment="MORNING", underlying=underlying, futures=futures,
        context={"atr10_prior_sessions": 20, "previous_day": None, "previous_week": None},
        split="IS_FROZEN_FIRST_70",
    )
    assert row["t1_available"] is True
    assert row["t3_available"] is False
    assert row["t3_terminal_before"] is True
