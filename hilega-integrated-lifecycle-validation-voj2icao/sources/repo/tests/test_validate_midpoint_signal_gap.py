from __future__ import annotations

from datetime import datetime

from market_lab.domain import IST

from scripts.validate_midpoint_signal_gap import (
    entry_chain,
    event_key,
    minute_reason,
    quiet_intervals,
)


def event(minute: int, kind: str, result: str = "OK") -> dict:
    return {
        "event_timestamp": datetime(2026, 10, 1, 9, minute, tzinfo=IST).isoformat(),
        "event_type": kind,
        "direction": "BEARISH",
        "result": result,
    }


def test_event_key_is_stable_and_state_specific():
    row = event(30, "MIDPOINT_BREAK", "CONFIRMED_CLOSE")
    assert event_key(row) == (
        "2026-10-01T09:30:00+05:30",
        "MIDPOINT_BREAK",
        "BEARISH",
        "CONFIRMED_CLOSE",
    )


def test_quiet_interval_counts_minutes_between_decisions():
    rows = [event(30, "MIDPOINT_BREAK"), event(40, "BOUNDARY_BREAK")]
    result = quiet_intervals(rows, minimum=5)
    assert result[0]["quiet_completed_minutes"] == 9
    assert result[0]["interpretation"] == "DATA_PRESENT_BUT_NO_STATE_TRANSITION"


def test_entry_chain_is_bounded_and_ends_at_entry():
    rows = [event(minute, "MIDPOINT_BREAK") for minute in range(20, 32)]
    entry = event(32, "E_ENTRY", "SHADOW_ENTRY")
    rows.append(entry)
    chain = entry_chain(rows, entry)
    assert len(chain) == 12
    assert chain[-1]["event_type"] == "E_ENTRY"


def test_minute_reason_explains_waiting_gate():
    references = [{
        "key": "RED", "closed": False, "lifecycle_state": None,
        "watch_active": False, "midpoint_seen": True, "boundary_seen": False,
    }]
    assert minute_reason([], references, None) == (
        "RED=WAITING_FOR_CLOSE_BEYOND_BOUNDARY"
    )


def test_minute_reason_prioritizes_entry_event():
    assert minute_reason([event(32, "E_ENTRY", "SHADOW_ENTRY")], [], None) == (
        "ENTRY_EMITTED:E_ENTRY"
    )
