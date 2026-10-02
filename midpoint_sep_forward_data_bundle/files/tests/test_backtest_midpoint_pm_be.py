import json
from datetime import datetime

from scripts.backtest_midpoint_pm_be import (
    directional_points,
    load_forward_sessions,
    selected_exit,
    trade_metric,
    validate_pm_chronology,
)


def event(timestamp, event_type, **values):
    return {
        "event_timestamp": f"2026-09-30T{timestamp}:00+05:30",
        "event_type": event_type,
        **values,
    }


def test_directional_points_are_signed_by_trade_direction():
    assert directional_points("BULLISH", 100.0, 112.0) == 12.0
    assert directional_points("BEARISH", 100.0, 88.0) == 12.0


def test_selected_exit_uses_route_candidate_before_structural():
    segment = [
        event("13:50", "MANAGEMENT_ROUTE_SELECTED", result="RUNNER_DEGRADED_EXIT"),
        event("13:55", "DEGRADED_EXIT_CANDIDATE_TRIGGERED"),
        event("14:20", "STRUCTURAL_TERMINAL"),
    ]
    policy, selected = selected_exit(segment)
    assert policy == "DEGRADED_EXIT_CANDIDATE"
    assert selected["event_timestamp"].endswith("13:55:00+05:30")


def test_pm_b_chronology_accepts_delayed_confirmed_entry():
    rows = [
        event("13:15", "PM_MIDPOINT_BREAK", direction="BEARISH"),
        event("13:35", "PM_BOUNDARY_CLASSIFIED", direction="BEARISH", result="B"),
        event("13:35", "PM_B_WATCH_STARTED", direction="BEARISH"),
        event("13:36", "PM_B_CONFIRMATION_CHECK", direction="BEARISH", result="WAIT"),
        event("13:44", "PM_B_CONFIRMATION_CHECK", direction="BEARISH", result="ENTRY"),
        event("13:44", "PM_B_ENTRY", direction="BEARISH", result="SHADOW_ENTRY"),
    ]
    validate_pm_chronology("2026-09-30", rows)


def test_pm_e_must_enter_on_boundary_minute():
    rows = [
        event("13:15", "PM_MIDPOINT_BREAK", direction="BULLISH"),
        event("13:35", "PM_BOUNDARY_CLASSIFIED", direction="BULLISH", result="E"),
        event("13:36", "PM_E_ENTRY", direction="BULLISH", result="SHADOW_ENTRY"),
    ]
    try:
        validate_pm_chronology("2026-09-30", rows)
    except AssertionError as error:
        assert "not immediate" in str(error)
    else:
        raise AssertionError("PM_E chronology should have failed")


def test_trade_metric_reports_confirmation_cost():
    row = {
        "selected_exit_points": 20.0,
        "confirmation_delay_minutes": 4.0,
        "pre_entry_move_points": 8.0,
        "boundary_counterfactual_points_same_exit": 28.0,
    }
    summary = trade_metric([row])
    assert summary["sum_points"] == 20.0
    assert summary["sum_pre_entry_move_points"] == 8.0
    assert summary["boundary_counterfactual_delta_sum"] == 8.0


def test_load_forward_sessions_reads_exact_360(tmp_path):
    root = tmp_path / "forward"
    day = "2026-09-09"
    folder = root / day
    folder.mkdir(parents=True)
    start = datetime.fromisoformat(day + "T09:15:00+05:30")
    rows = []
    from datetime import timedelta
    for offset in range(360):
        rows.append({
            "timestamp": (start + timedelta(minutes=offset)).isoformat(),
            "underlying_open": 100,
            "underlying_high": 101,
            "underlying_low": 99,
            "underlying_close": 100,
            "futures_close": 110,
            "futures_vwap": 109,
            "futures_volume": 1,
        })
    (folder / "minutes.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows)
    )
    (root / "manifest.json").write_text(json.dumps({
        "session_count": 1,
        "sessions": [{"session_date": day}],
    }))
    loaded = load_forward_sessions(root)
    assert list(loaded) == [day]
    assert len(loaded[day][0]) == 360
