from market_lab.midpoint_strategy.live_shadow_ui import _causal_option_tapes
from market_lab.midpoint_strategy.materialize_option_observation import (
    sorted_entry_events,
)


def event(event_id, timestamp, event_type, direction):
    return {
        "event_id": event_id,
        "event_timestamp": timestamp,
        "event_type": event_type,
        "direction": direction,
    }


def test_materializer_sorts_entries_chronologically_after_restart_append():
    rows = [
        event("pe", "2026-10-01T12:10:00+05:30", "E_ENTRY", "BEARISH"),
        event("noise", "2026-10-01T12:11:00+05:30", "PLUS20_PROOF", "BEARISH"),
        event("ce", "2026-10-01T09:30:00+05:30", "A_ENTRY", "BULLISH"),
    ]
    assert [row["event_id"] for row in sorted_entry_events(rows)] == ["ce", "pe"]


def test_api_selects_latest_causal_tape_not_last_json_item():
    payload = {"tapes": [
        {"entry_event_id": "pe", "entry_timestamp": "2026-10-01T12:10:00+05:30"},
        {"entry_event_id": "ce", "entry_timestamp": "2026-10-01T09:30:00+05:30"},
    ]}
    tapes = _causal_option_tapes(payload, "2026-10-01T15:00:00+05:30")
    assert [tape["entry_event_id"] for tape in tapes] == ["ce", "pe"]
    assert tapes[-1]["entry_event_id"] == "pe"


def test_api_does_not_expose_future_entry():
    payload = {"tapes": [
        {"entry_event_id": "pe", "entry_timestamp": "2026-10-01T12:10:00+05:30"},
        {"entry_event_id": "ce", "entry_timestamp": "2026-10-01T09:30:00+05:30"},
    ]}
    tapes = _causal_option_tapes(payload, "2026-10-01T10:00:00+05:30")
    assert [tape["entry_event_id"] for tape in tapes] == ["ce"]
