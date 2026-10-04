from datetime import datetime, timedelta, timezone

from scripts.research_hilega_rsi_extreme_reversal_exits import (
    is_extreme, left_extreme, simulate_reversal_exit,
)


BASE = datetime(2026, 10, 1, 9, 15, tzinfo=timezone.utc)


def rows(points):
    return [(BASE + timedelta(minutes=i), 100.0 + point) for i, point in enumerate(points)]


def test_directional_zone_rules():
    assert is_extreme("BULLISH", 70.0)
    assert left_extreme("BULLISH", 69.9)
    assert is_extreme("BEARISH", 30.0)
    assert left_extreme("BEARISH", 30.1)


def test_bullish_arms_but_does_not_exit_while_extreme():
    timeline = rows([0, 5, 10, 15, 20, 25, 30])
    result = simulate_reversal_exit(
        timeline=timeline,
        rsi_by_timestamp={timeline[2][0]: 72.0, timeline[4][0]: 75.0},
        direction="BULLISH", entry_price=100.0,
        control_exit_at=BASE + timedelta(minutes=10), control_points=20.0,
        require_proof=False,
    )
    assert result["candidate_exit"] is False
    assert result["armed_timestamp"] == timeline[2][0].isoformat()


def test_bullish_exits_only_on_later_return_below_70():
    timeline = rows([0, 5, 10, 15, 20, 25, 30])
    result = simulate_reversal_exit(
        timeline=timeline,
        rsi_by_timestamp={
            timeline[2][0]: 72.0, timeline[4][0]: 75.0, timeline[6][0]: 68.0,
        },
        direction="BULLISH", entry_price=100.0,
        control_exit_at=BASE + timedelta(minutes=10), control_points=20.0,
        require_proof=False,
    )
    assert result["candidate_exit"] is True
    assert result["exit_points"] == 30.0
    assert result["peak_extreme_rsi"] == 75.0


def test_bearish_exits_on_return_above_30():
    timeline = [(BASE + timedelta(minutes=i), 100.0 - point)
                for i, point in enumerate([0, 5, 10, 15, 20, 25, 30])]
    result = simulate_reversal_exit(
        timeline=timeline,
        rsi_by_timestamp={timeline[2][0]: 28.0, timeline[4][0]: 25.0, timeline[6][0]: 33.0},
        direction="BEARISH", entry_price=100.0,
        control_exit_at=BASE + timedelta(minutes=10), control_points=20.0,
        require_proof=False,
    )
    assert result["candidate_exit"] is True
    assert result["exit_points"] == 30.0


def test_plus20_variant_cannot_arm_before_proof():
    timeline = rows([0, 5, 10, 15, 18, 12, 8])
    result = simulate_reversal_exit(
        timeline=timeline,
        rsi_by_timestamp={timeline[2][0]: 72.0, timeline[4][0]: 75.0, timeline[6][0]: 65.0},
        direction="BULLISH", entry_price=100.0,
        control_exit_at=BASE + timedelta(minutes=10), control_points=8.0,
        require_proof=True,
    )
    assert result["candidate_exit"] is False
    assert result["armed_timestamp"] is None
