import csv
from pathlib import Path

from backend.market_lab.change_pcr_transition_lead_lag_v1 import (
    detect_transitions,
    build_event_windows,
)


def _row(session, ts, h, state, mech, cpcr=1.0):
    return {
        "session_date": session,
        "timestamp": ts,
        "horizon": h,
        "existing_horizon_state": state,
        "change_pcr_mechanics": mech,
        "change_pcr": cpcr,
        "ce_delta": 1.0,
        "pe_delta": 1.0,
        "delta_pattern": "CE+/PE+",
        "oi_imbalance": 1.0,
        "regular_pcr_change": 0.1,
        "futures_oi_direction": "NEUTRAL",
        "futures_oi_status": "UNAVAILABLE",
        "vwap_side": "ABOVE",
        "session_pcr_change": 0.0,
        "evaluation_label": None,
    }


def test_detects_directional_flip_across_mixed():
    rows = []
    times = ["09:30", "09:35", "09:40"]
    states = [
        ("BULLISH", "BOTH_BUILD_PE_DOMINANT"),
        ("MIXED", "BOTH_BUILD_CE_DOMINANT"),
        ("BEARISH", "BOTH_BUILD_CE_DOMINANT"),
    ]
    for t, (state, mech) in zip(times, states):
        for h in ("5m", "10m", "15m"):
            rows.append(_row("2026-08-25", f"2026-08-25T{t}:00+05:30", h, state, mech))

    events = detect_transitions(rows)
    assert len(events) == 1
    assert events[0]["from_state"] == "BULLISH_ALL_3"
    assert events[0]["to_state"] == "BEARISH_ALL_3"
    assert events[0]["transition_timestamp"].startswith("2026-08-25T09:40")


def test_build_window_scores_target_mechanics():
    rows = []
    specs = [
        ("09:25", "BULLISH", "BOTH_BUILD_PE_DOMINANT"),
        ("09:30", "BULLISH", "BOTH_BUILD_PE_DOMINANT"),
        ("09:35", "BULLISH", "BOTH_BUILD_CE_DOMINANT"),  # pre bearish clue
        ("09:40", "BEARISH", "BOTH_BUILD_CE_DOMINANT"),
        ("09:45", "BEARISH", "CE_BUILD_PE_UNWIND"),
    ]
    for t, state, mech in specs:
        for h in ("5m", "10m", "15m"):
            rows.append(_row("2026-08-25", f"2026-08-25T{t}:00+05:30", h, state, mech))

    events = detect_transitions(rows)
    windows = build_event_windows(rows, events)

    pre = [
        r for r in windows
        if r["offset_minutes"] == -5 and r["horizon"] == "5m"
    ][0]
    assert pre["mechanics_score_for_target"] == 1

    at = [
        r for r in windows
        if r["offset_minutes"] == 0 and r["horizon"] == "5m"
    ][0]
    assert at["mechanics_score_for_target"] == 1

    post = [
        r for r in windows
        if r["offset_minutes"] == 5 and r["horizon"] == "5m"
    ][0]
    assert post["mechanics_score_for_target"] == 2
