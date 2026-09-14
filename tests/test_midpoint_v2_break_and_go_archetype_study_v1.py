from datetime import date
from market_lab.midpoint_v2_break_and_go_archetype_study_v1 import candidate_events


def test_candidate_selection_ignores_primary_outcome():
    state = {
        "events": [
            {
                "session_date": "2026-09-07",
                "setup_type": "RED_BREAK",
                "direction": "BEARISH",
                "t3_state": "CONFIRM_CONTINUATION",
                "primary_outcome": "RED_BEARISH_BASE_THEN_GO",
            },
            {
                "session_date": "2026-09-03",
                "setup_type": "RED_BREAK",
                "direction": "BEARISH",
                "t3_state": "CONFIRM_CONTINUATION",
                "primary_outcome": "RED_BEARISH_BREAK_AND_GO",
            },
        ]
    }
    rows = candidate_events(state, date(2026, 6, 9), date(2026, 9, 7))
    assert [r["session_date"] for r in rows] == ["2026-09-03", "2026-09-07"]


def test_candidate_selection_rejects_nonmatching_direction_or_state():
    state = {
        "events": [
            {
                "session_date": "2026-08-01",
                "setup_type": "GREEN_BREAK",
                "direction": "BULLISH",
                "t3_state": "CONFIRM_CONTINUATION",
            },
            {
                "session_date": "2026-08-02",
                "setup_type": "RED_BREAK",
                "direction": "BEARISH",
                "t3_state": "WAIT_BASE",
            },
        ]
    }
    rows = candidate_events(state, date(2026, 6, 9), date(2026, 9, 7))
    assert rows == []
