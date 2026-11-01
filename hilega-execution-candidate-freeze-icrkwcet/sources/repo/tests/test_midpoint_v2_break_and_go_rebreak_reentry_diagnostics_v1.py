from market_lab.midpoint_v2_break_and_go_rebreak_reentry_diagnostics_v1 import (
    extract_framework_rows,
)

def test_framework_boundary_extract():
    doc = {"events": [{
        "session_date":"2026-09-07",
        "setup_type":"RED_BREAK",
        "reference_low":23838.25,
        "reference_high":23861.30,
    }]}
    idx = extract_framework_rows(doc)
    assert idx[("2026-09-07","RED_BREAK")]["reference_low"] == 23838.25

def test_green_not_used_as_red_boundary():
    doc = {"events": [{
        "session_date":"2026-09-07",
        "setup_type":"GREEN_BREAK",
        "reference_low":23828.25,
    }]}
    assert extract_framework_rows(doc) == {}
