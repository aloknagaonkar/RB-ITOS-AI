from market_lab.midpoint_strategy.live_shadow_ui import (
    _selected_trade_view,
    _with_nifty_points,
)


def row(event_id, timestamp, event_type, family, direction, reference, **extra):
    return {
        "event_id": event_id,
        "session_date": "2026-10-01",
        "event_timestamp": f"2026-10-01T{timestamp}:00+05:30",
        "event_type": event_type,
        "family": family,
        "direction": direction,
        "reference_type": reference,
        "underlying_price": extra.pop("price", 100.0),
        "evidence": extra.pop("evidence", {}),
        **extra,
    }


def test_selected_trade_never_mixes_parallel_a_and_e_lanes():
    rows = [
        row("a-entry", "09:30", "A_ENTRY", "A", "BULLISH", "GREEN"),
        row("a-proof", "10:01", "PLUS20_PROOF", "A", "BULLISH", "GREEN", price=122),
        row("a-exit", "10:12", "STRUCTURAL_TERMINAL", "A", "BULLISH", "GREEN", price=90),
        row("e-entry", "12:10", "E_ENTRY", "E", "BEARISH", "RED", price=200),
        row("e-health", "15:28", "CONTINUOUS_HEALTH_CHECK", "E", "BEARISH", "RED",
            price=195, evidence={"health": "UNHEALTHY", "support_count": 0}),
    ]
    trade = _selected_trade_view(rows)
    assert trade["trade_id"] == "e-entry"
    assert trade["status"] == "ACTIVE"
    assert trade["entry"]["family"] == "E"
    assert trade["entry"]["direction"] == "BEARISH"
    assert trade["plus20"] is None
    assert trade["health"]["event_id"] == "e-health"
    assert trade["terminal"] is None


def test_completed_lane_is_labelled_closed_and_keeps_its_own_terminal():
    rows = [
        row("entry", "12:10", "E_ENTRY", "E", "BEARISH", "RED", price=200),
        row("health", "12:11", "CONTINUOUS_HEALTH_CHECK", "E", "BEARISH", "RED",
            price=190, evidence={"health": "HEALTHY", "support_count": 3}),
        row("terminal", "12:20", "STRUCTURAL_TERMINAL", "E", "BEARISH", "RED", price=210),
        row("other", "12:21", "CONTINUOUS_HEALTH_CHECK", "A", "BULLISH", "GREEN",
            evidence={"health": "UNHEALTHY", "support_count": 0}),
    ]
    trade = _selected_trade_view(rows)
    assert trade["status"] == "CLOSED"
    assert trade["health"]["event_id"] == "health"
    assert trade["terminal"]["event_id"] == "terminal"
    assert trade["latest_event"]["event_id"] == "terminal"


def test_repeated_same_identity_opens_a_new_generation_after_terminal():
    rows = [
        row("g0", "09:30", "B_ENTRY", "B", "BEARISH", "RED"),
        row("g0-x", "09:40", "STRUCTURAL_TERMINAL", "B", "BEARISH", "RED"),
        row("g1", "09:50", "B_REARM_ENTRY", "B", "BEARISH", "RED"),
        row("g1-h", "09:51", "CONTINUOUS_HEALTH_CHECK", "B", "BEARISH", "RED",
            evidence={"health": "HEALTHY", "support_count": 2}),
    ]
    trade = _selected_trade_view(rows)
    assert trade["trade_id"] == "g1"
    assert trade["status"] == "ACTIVE"
    assert trade["event_count"] == 2


def test_nifty_delta_is_independent_for_parallel_bullish_and_bearish_lanes():
    rows = [
        row("a", "09:30", "A_ENTRY", "A", "BULLISH", "GREEN", price=100),
        row("e", "09:31", "E_ENTRY", "E", "BEARISH", "RED", price=200),
        row("a-h", "09:32", "CONTINUOUS_HEALTH_CHECK", "A", "BULLISH", "GREEN", price=112,
            evidence={"health": "HEALTHY", "support_count": 3}),
        row("e-h", "09:33", "CONTINUOUS_HEALTH_CHECK", "E", "BEARISH", "RED", price=190,
            evidence={"health": "HEALTHY", "support_count": 3}),
    ]
    projected = _with_nifty_points(rows)
    assert projected[2]["nifty_entry_price"] == 100
    assert projected[2]["nifty_points_from_entry"] == 12
    assert projected[3]["nifty_entry_price"] == 200
    assert projected[3]["nifty_points_from_entry"] == 10
