from datetime import datetime

from market_lab.midpoint_strategy.extended_entry_candidates import (
    CRearmCandidate,
    PMEReversalCandidate,
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


def test_pm_requires_first_break_recross_and_later_fresh_opposite_break():
    candidate = PMEReversalCandidate(
        "2026-08-25", ts("12:45"), ts("13:14"), 120.0, 100.0
    )
    first = candidate.observe(
        timestamp=ts("13:15"), previous_close=115.0, close=121.0
    )
    assert first[0].event_type == "PM_FALSE_BREAK_OBSERVED"
    assert candidate.observe(
        timestamp=ts("13:16"), previous_close=121.0, close=115.0
    ) == []
    recross = candidate.observe(
        timestamp=ts("13:17"), previous_close=115.0, close=109.0
    )
    assert recross[0].event_type == "PM_MIDPOINT_RECROSS_ARMED"
    assert candidate.observe(
        timestamp=ts("13:18"), previous_close=99.0, close=98.0
    ) == []
    final = candidate.observe(
        timestamp=ts("13:19"), previous_close=101.0, close=99.0
    )
    assert final[0].event_type == "PM_E_FRESH_BOUNDARY_BREAK"
    assert final[0].direction == "BEARISH"


def test_pm_bullish_reversal_is_symmetric():
    candidate = PMEReversalCandidate(
        "2026-08-25", ts("12:45"), ts("13:14"), 120.0, 100.0
    )
    candidate.observe(timestamp=ts("13:15"), previous_close=105.0, close=99.0)
    candidate.observe(timestamp=ts("13:16"), previous_close=99.0, close=111.0)
    final = candidate.observe(
        timestamp=ts("13:17"), previous_close=119.0, close=121.0
    )
    assert final[0].direction == "BULLISH"
    assert candidate.reversal_reference().reference_type == "GREEN"
