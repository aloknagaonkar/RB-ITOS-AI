from datetime import datetime, timedelta, timezone

from scripts.research_hilega_post_proof_mfe_exits import (
    maximum_drawdown,
    simulate_policy,
)


BASE = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


def timeline(points):
    return [(BASE + timedelta(minutes=i), 100.0 + value) for i, value in enumerate(points)]


def run(points, fraction, mode="ONE_MINUTE_DIRECT"):
    return simulate_policy(
        timeline=timeline(points),
        direction="BULLISH",
        entry_price=100.0,
        control_exit_at=BASE + timedelta(minutes=len(points) + 1),
        control_points=points[-1],
        giveback_fraction=fraction,
        mode=mode,
    )


def test_does_not_arm_before_plus20_proof():
    result = run([0, 10, 18, 5], 0.25)
    assert result["candidate_exit"] is False


def test_direct_one_minute_exit_uses_running_mfe_percentage():
    result = run([0, 20, 40, 32, 29], 0.25)
    assert result["candidate_exit"] is True
    assert result["exit_points"] == 29
    assert result["mfe_at_exit"] == 40
    assert result["floor_at_exit"] == 30


def test_floor_rises_and_never_uses_fixed_points():
    result = run([0, 20, 60, 50, 44], 0.25)
    assert result["candidate_exit"] is True
    assert result["floor_at_exit"] == 45


def test_bearish_directional_points_are_normalized():
    rows = [(BASE + timedelta(minutes=i), 100.0 - value)
            for i, value in enumerate([0, 20, 40, 28])]
    result = simulate_policy(
        timeline=rows,
        direction="BEARISH",
        entry_price=100.0,
        control_exit_at=BASE + timedelta(minutes=10),
        control_points=25,
        giveback_fraction=0.25,
        mode="ONE_MINUTE_DIRECT",
    )
    assert result["candidate_exit"] is True
    assert result["exit_points"] == 28


def test_five_minute_confirmation_does_not_exit_on_recovered_breach():
    # UTC minutes 0..9: completed 5m closes are minute 4 and 9.
    result = run([0, 20, 40, 28, 35, 38, 36, 34, 33, 31], 0.25,
                 "ONE_MINUTE_ARM_FIVE_MINUTE_CONFIRM")
    assert result["candidate_exit"] is False


def test_five_minute_confirmation_exits_if_breach_persists():
    result = run([0, 20, 40, 28, 25], 0.25,
                 "ONE_MINUTE_ARM_FIVE_MINUTE_CONFIRM")
    assert result["candidate_exit"] is True
    assert result["exit_points"] == 25


def test_maximum_drawdown():
    assert maximum_drawdown([10, -3, -9, 4]) == 12
