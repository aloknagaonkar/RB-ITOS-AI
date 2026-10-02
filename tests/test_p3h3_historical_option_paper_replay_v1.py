from market_lab.historical_option_paper_replay_v1 import (
    HistoricalPaperPosition,
    _update_position,
)


def test_hard_stop_close():
    p = HistoricalPaperPosition(
        position_id="x",
        session_date="2026-08-25",
        direction="BULLISH",
        option_type="CE",
        strike=24150,
        instrument_key="CE",
        opened_at="2026-08-25T10:00:00+05:30",
        entry_price=100.0,
    )
    event = _update_position(
        p,
        timestamp="2026-08-25T10:05:00+05:30",
        price=94.0,
    )
    assert p.status == "CLOSED"
    assert p.exit_reason == "HARD_STOP"
    assert event.reason_code == "HARD_STOP"


def test_breakeven_arm_then_close():
    p = HistoricalPaperPosition(
        position_id="x",
        session_date="2026-08-25",
        direction="BULLISH",
        option_type="CE",
        strike=24150,
        instrument_key="CE",
        opened_at="2026-08-25T10:00:00+05:30",
        entry_price=100.0,
    )
    _update_position(
        p,
        timestamp="2026-08-25T10:05:00+05:30",
        price=106.0,
    )
    assert p.breakeven_armed is True
    assert p.active_stop_price == 100.0

    event = _update_position(
        p,
        timestamp="2026-08-25T10:10:00+05:30",
        price=99.0,
    )
    assert p.status == "CLOSED"
    assert p.exit_reason == "BREAKEVEN_STOP"
    assert event.reason_code == "BREAKEVEN_STOP"


def test_trailing_arm_and_ratchet():
    p = HistoricalPaperPosition(
        position_id="x",
        session_date="2026-08-25",
        direction="BULLISH",
        option_type="CE",
        strike=24150,
        instrument_key="CE",
        opened_at="2026-08-25T10:00:00+05:30",
        entry_price=100.0,
    )
    _update_position(
        p,
        timestamp="2026-08-25T10:05:00+05:30",
        price=112.0,
    )
    assert p.trailing_armed is True
    assert round(p.active_stop_price, 2) == 108.64

    _update_position(
        p,
        timestamp="2026-08-25T10:10:00+05:30",
        price=120.0,
    )
    assert round(p.active_stop_price, 2) == 116.40

    event = _update_position(
        p,
        timestamp="2026-08-25T10:15:00+05:30",
        price=115.0,
    )
    assert p.status == "CLOSED"
    assert p.exit_reason == "TRAIL_STOP"
    assert event.reason_code == "TRAIL_STOP"
