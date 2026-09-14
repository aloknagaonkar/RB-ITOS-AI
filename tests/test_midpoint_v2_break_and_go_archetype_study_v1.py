from datetime import date
from market_lab.midpoint_v2_break_and_go_archetype_study_v1 import (
    candidate_events, resolve_t3_timestamp, extract_economics_rows
)


def test_candidate_selection_ignores_primary_outcome():
    state = {"events": [
        {"session_date":"2026-09-07","setup_type":"RED_BREAK","direction":"BEARISH",
         "t3_state":"CONFIRM_CONTINUATION","primary_outcome":"RED_BEARISH_BASE_THEN_GO"},
        {"session_date":"2026-09-03","setup_type":"RED_BREAK","direction":"BEARISH",
         "t3_state":"CONFIRM_CONTINUATION","primary_outcome":"RED_BEARISH_BREAK_AND_GO"},
    ]}
    rows = candidate_events(state, date(2026,6,9), date(2026,9,7))
    assert [r["session_date"] for r in rows] == ["2026-09-03","2026-09-07"]


def test_extract_nested_economics_row():
    doc = {
        "nested": {"items": [{
            "session_date":"2026-09-07",
            "setup_type":"RED_BREAK",
            "direction":"BEARISH",
            "t3_state":"CONFIRM_CONTINUATION",
            "entry_timestamp":"2026-09-07T09:29:00+05:30",
            "entry_price":74.75,
        }]}
    }
    rows = extract_economics_rows(doc)
    assert len(rows) == 1


def test_resolve_t3_timestamp_prefers_state():
    s = {"t3_timestamp":"2026-09-07T09:28:00+05:30"}
    e = {"t3_timestamp":"2026-09-07T09:29:00+05:30"}
    assert resolve_t3_timestamp(s,e) == s["t3_timestamp"]


def test_resolve_t3_timestamp_falls_back_to_economics_t3():
    s = {}
    e = {"t3_timestamp":"2026-09-07T09:28:00+05:30"}
    assert resolve_t3_timestamp(s,e) == e["t3_timestamp"]


def test_resolve_t3_from_exact_entry_minus_one_minute():
    s = {}
    e = {"entry_timestamp":"2026-09-07T09:29:00+05:30"}
    assert resolve_t3_timestamp(s,e) == "2026-09-07T09:28:00+05:30"


def test_resolve_t3_timestamp_missing_returns_none():
    assert resolve_t3_timestamp({}, {}) is None
