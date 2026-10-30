from datetime import datetime

from market_lab.midpoint_strategy.extended_entry_candidates import (
    CRearmCandidate,
    PMMidpointBECandidate,
)
from market_lab.midpoint_strategy.structure import ReferenceStructure


def ts(value):
    return datetime.fromisoformat(f"2026-08-25T{value}:00+05:30")


def test_c_requires_touch_close_and_later_fresh_boundary_break():
    reference = ReferenceStructure(
        "2026-08-25", "RED", ts("09:20").isoformat(),
        ts("09:24").isoformat(), 120.0, 100.0,
    )
    candidate = CRearmCandidate(reference, "B", ts("09:42"))
    action = candidate.observe_active_bar(
        timestamp=ts("10:00"), high=111.0, low=109.0
    )
    assert action.event_type == "C_MIDPOINT_TOUCH_ARMED"
    candidate.mark_origin_closed(ts("10:01"))
    assert candidate.observe_after_close(
        timestamp=ts("10:01"), previous_close=105.0, close=99.0
    ) is None
    assert candidate.observe_after_close(
        timestamp=ts("10:02"), previous_close=99.0, close=98.0
    ) is None
    action = candidate.observe_after_close(
        timestamp=ts("10:03"), previous_close=101.0, close=99.0
    )
    assert action.event_type == "C_FRESH_BOUNDARY_BREAK"
    assert candidate.observe_after_close(
        timestamp=ts("10:04"), previous_close=101.0, close=98.0
    ) is None


def test_pm_midpoint_break_sets_bearish_direction_then_boundary_breaks():
    candidate = PMMidpointBECandidate(
        "2026-08-25", ts("12:45"), ts("13:14"), 120.0, 100.0
    )
    midpoint = candidate.observe(
        timestamp=ts("13:15"), previous_close=115.0, close=109.0
    )
    assert midpoint[0].event_type == "PM_MIDPOINT_BREAK"
    assert midpoint[0].direction == "BEARISH"
    assert candidate.observe(
        timestamp=ts("13:16"), previous_close=109.0, close=105.0
    ) == []
    boundary = candidate.observe(
        timestamp=ts("13:17"), previous_close=105.0, close=99.0
    )
    assert boundary[0].event_type == "PM_BOUNDARY_BREAK"
    assert boundary[0].direction == "BEARISH"
    assert candidate.directional_reference("BEARISH").reference_type == "RED"


def test_pm_bullish_midpoint_and_boundary_can_break_on_same_candle():
    candidate = PMMidpointBECandidate(
        "2026-08-25", ts("12:45"), ts("13:14"), 120.0, 100.0
    )
    actions = candidate.observe(
        timestamp=ts("13:15"), previous_close=105.0, close=121.0
    )
    assert [action.event_type for action in actions] == [
        "PM_MIDPOINT_BREAK", "PM_BOUNDARY_BREAK"
    ]
    assert all(action.direction == "BULLISH" for action in actions)
    assert candidate.directional_reference("BULLISH").reference_type == "GREEN"


def test_pm_can_arm_both_midpoint_directions_before_first_boundary():
    candidate = PMMidpointBECandidate(
        "2026-08-25", ts("12:45"), ts("13:14"), 120.0, 100.0
    )
    bullish = candidate.observe(
        timestamp=ts("13:15"), previous_close=109.0, close=111.0
    )
    bearish = candidate.observe(
        timestamp=ts("13:16"), previous_close=111.0, close=109.0
    )
    boundary = candidate.observe(
        timestamp=ts("13:17"), previous_close=109.0, close=99.0
    )
    assert bullish[0].direction == "BULLISH"
    assert bearish[0].direction == "BEARISH"
    assert boundary[0].event_type == "PM_BOUNDARY_BREAK"
    assert boundary[0].direction == "BEARISH"


def test_pm_candidate_expires_at_1515_without_entry():
    candidate = PMMidpointBECandidate(
        "2026-08-25", ts("12:45"), ts("13:14"), 120.0, 100.0
    )
    actions = candidate.observe(
        timestamp=ts("15:15"), previous_close=105.0, close=121.0
    )
    assert actions[0].event_type == "PM_ENTRY_WINDOW_EXPIRED"
    assert candidate.state == "EXPIRED"
