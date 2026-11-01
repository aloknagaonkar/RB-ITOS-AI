from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/validate_hilega_entry_filters_dates.py"
)
SPEC = importlib.util.spec_from_file_location("hilega_date_validation", SCRIPT)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def candidate_trade(**updates):
    row = {
        "session_date": "2026-09-30",
        "direction": "BULLISH",
        "route": "ROUTE_A",
        "captured_points": 20.0,
        "mfe_points": 30.0,
        "mae_points": -4.0,
        "giveback_points": 10.0,
        "candidate_status": "AVAILABLE",
        "wma_flat_warning": False,
        "large_gain_alignment_keep": True,
        "flat_confirmation_keep": True,
        "flat_confirmation_reject": False,
        "alignment_candidate_points": 20.0,
        "flat_confirmation_candidate_points": 20.0,
    }
    row.update(updates)
    return row


def test_dates_are_sorted_and_deduplicated():
    assert m.validate_dates(["2026-10-01", "2026-09-30", "2026-10-01"]) == [
        "2026-09-30", "2026-10-01"
    ]


def test_daily_summary_uses_zero_for_rejected_candidate():
    rows = [
        candidate_trade(),
        candidate_trade(
            direction="BEARISH",
            captured_points=-12.0,
            large_gain_alignment_keep=False,
            alignment_candidate_points=0.0,
            flat_confirmation_keep=False,
            flat_confirmation_reject=True,
            flat_confirmation_candidate_points=0.0,
            wma_flat_warning=True,
        ),
    ]
    summary = m.daily_summary(rows, ["2026-09-30"])[0]
    assert summary["control_points_all_signals"] == 8.0
    assert summary["candidate_comparable_control_points"] == 8.0
    assert summary["large_gain_alignment_points_available"] == 20.0
    assert summary["large_gain_alignment_delta_available"] == 12.0
    assert summary["flat_confirmation_points_available"] == 20.0
    assert summary["flat_confirmation_rejected"] == 1


def test_unavailable_trade_is_reported_but_not_treated_as_rejected():
    rows = [
        candidate_trade(),
        candidate_trade(
            captured_points=-7.0,
            candidate_status="UNAVAILABLE",
            alignment_candidate_points=None,
            flat_confirmation_candidate_points=None,
            large_gain_alignment_keep=None,
            flat_confirmation_keep=None,
            flat_confirmation_reject=None,
            wma_flat_warning=None,
        ),
    ]
    rows[0]["candidate_status"] = "AVAILABLE"
    summary = m.daily_summary(rows, ["2026-09-30"])[0]
    assert summary["control_points_all_signals"] == 13.0
    assert summary["candidate_available_signals"] == 1
    assert summary["candidate_unavailable_signals"] == 1
    assert summary["candidate_comparable_control_points"] == 20.0
    assert summary["large_gain_alignment_points_available"] == 20.0


def test_replay_event_set_contains_entry_and_exit():
    rows = [{
        "entry_timestamp": "2026-09-30T10:00:00+05:30",
        "entry_event": "ENTRY_PATH1_ROUTE_B_STRUCTURAL",
        "exit_timestamp": "2026-09-30T10:30:00+05:30",
        "exit_event": "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21",
        "direction": "BULLISH",
    }]
    result = m.replay_events(rows)
    assert len(result) == 2
    assert (
        "2026-09-30T10:00:00+05:30",
        "ENTRY_PATH1_ROUTE_B_STRUCTURAL",
        "BULLISH",
    ) in result


def test_no_recorded_audit_is_explicit(tmp_path):
    trades = [{
        "entry_timestamp": "2026-09-30T10:00:00+05:30",
        "entry_event": "ENTRY_PATH1_ROUTE_B_STRUCTURAL",
        "exit_timestamp": "2026-09-30T10:30:00+05:30",
        "exit_event": "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21",
        "direction": "BULLISH",
    }]
    result = m.event_parity(trades, tmp_path / "missing.jsonl", {"2026-09-30"})
    assert result["status"] == "RECORDED_AUDIT_UNAVAILABLE"
    assert result["replayed_event_count"] == 2


def test_event_direction_maps_all_canonical_lifecycle_events():
    for event in m.BULLISH_ENTRY_EVENTS | m.BULLISH_EXIT_EVENTS:
        assert m.event_direction(event) == "BULLISH"
    for event in m.BEARISH_ENTRY_EVENTS | m.BEARISH_EXIT_EVENTS:
        assert m.event_direction(event) == "BEARISH"
