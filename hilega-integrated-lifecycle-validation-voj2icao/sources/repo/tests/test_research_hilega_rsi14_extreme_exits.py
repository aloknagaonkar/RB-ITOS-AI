from datetime import datetime, timedelta, timezone

from scripts.research_hilega_rsi14_extreme_exits import (
    extreme,
    pine_rsi,
    simulate_rsi14_exit,
)


BASE = datetime(2026, 10, 1, 9, 15, tzinfo=timezone.utc)


def test_extreme_is_directional():
    assert extreme("BULLISH", 70.0)
    assert not extreme("BULLISH", 69.99)
    assert extreme("BEARISH", 30.0)
    assert not extreme("BEARISH", 30.01)


def test_pine_rsi_has_fourteen_bar_warmup():
    values = [float(index) for index in range(20)]
    output = pine_rsi(values, 14)
    assert output[13] is None
    assert output[14] == 100.0


def test_direct_bullish_exits_at_first_completed_extreme():
    timeline = [(BASE + timedelta(minutes=i), 100.0 + i) for i in range(12)]
    rsi = {timeline[4][0]: 65.0, timeline[9][0]: 72.0}
    result = simulate_rsi14_exit(
        timeline=timeline, rsi_by_timestamp=rsi, direction="BULLISH",
        entry_price=100.0, control_exit_at=BASE + timedelta(minutes=20),
        control_points=5.0, require_proof=False,
    )
    assert result["candidate_exit"] is True
    assert result["exit_timestamp"] == timeline[9][0].isoformat()
    assert result["exit_rsi14"] == 72.0


def test_post_proof_does_not_exit_before_plus20():
    timeline = [(BASE + timedelta(minutes=i), 100.0 + i) for i in range(12)]
    rsi = {timeline[4][0]: 75.0, timeline[9][0]: 72.0}
    result = simulate_rsi14_exit(
        timeline=timeline, rsi_by_timestamp=rsi, direction="BULLISH",
        entry_price=100.0, control_exit_at=BASE + timedelta(minutes=20),
        control_points=5.0, require_proof=True,
    )
    assert result["candidate_exit"] is False


def test_post_proof_bearish_exits_after_proof():
    timeline = [(BASE + timedelta(minutes=i), 100.0 - 3.0 * i) for i in range(12)]
    rsi = {timeline[4][0]: 35.0, timeline[9][0]: 25.0}
    result = simulate_rsi14_exit(
        timeline=timeline, rsi_by_timestamp=rsi, direction="BEARISH",
        entry_price=100.0, control_exit_at=BASE + timedelta(minutes=20),
        control_points=5.0, require_proof=True,
    )
    assert result["candidate_exit"] is True
    assert result["exit_points"] == 27.0


def test_no_extreme_preserves_control_exit():
    timeline = [(BASE + timedelta(minutes=i), 100.0 + i) for i in range(12)]
    result = simulate_rsi14_exit(
        timeline=timeline, rsi_by_timestamp={timeline[9][0]: 60.0},
        direction="BULLISH", entry_price=100.0,
        control_exit_at=BASE + timedelta(minutes=20), control_points=7.0,
        require_proof=False,
    )
    assert result["candidate_exit"] is False
    assert result["exit_points"] == 7.0
