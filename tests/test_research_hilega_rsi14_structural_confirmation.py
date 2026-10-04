from datetime import datetime, timedelta, timezone

from scripts.research_hilega_rsi14_structural_confirmation import (
    simulate_structural_exit,
)


BASE = datetime(2026, 10, 1, 9, 15, tzinfo=timezone.utc)


def run(minimum, final):
    timeline = [(BASE + timedelta(minutes=i), 100.0 + 10.0 * i) for i in range(8)]
    indicators = {
        timeline[2][0]: {"rsi14": 72.0, "gap": 8.0, "wma_slope": 1.0},
        timeline[4][0]: {"rsi14": 68.0, "gap": 6.0, "wma_slope": 0.5},
        timeline[6][0]: final,
    }
    return simulate_structural_exit(
        timeline=timeline, indicators=indicators, direction="BULLISH",
        entry_price=100.0, control_exit_at=BASE + timedelta(minutes=10),
        control_points=20.0, minimum_components=minimum,
    )


def test_two_of_three_exits_with_two_components():
    result = run(2, {"rsi14": 66.0, "gap": 5.0, "wma_slope": 0.7})
    assert result["candidate_exit"] is True
    assert result["component_count"] == 2


def test_three_of_three_requires_every_component():
    result = run(3, {"rsi14": 66.0, "gap": 5.0, "wma_slope": 0.7})
    assert result["candidate_exit"] is False


def test_three_of_three_exits_when_all_confirm():
    result = run(3, {"rsi14": 66.0, "gap": 5.0, "wma_slope": 0.2})
    assert result["candidate_exit"] is True
    assert result["component_count"] == 3


def test_gap_expansion_cancels_warning():
    result = run(2, {"rsi14": 66.0, "gap": 7.0, "wma_slope": 0.2})
    assert result["candidate_exit"] is False
    assert result["cancellation_count"] == 1


def test_no_arm_without_plus20_proof():
    timeline = [(BASE + timedelta(minutes=i), 100.0 + i) for i in range(8)]
    indicators = {
        timeline[2][0]: {"rsi14": 72.0, "gap": 8.0, "wma_slope": 1.0},
        timeline[4][0]: {"rsi14": 68.0, "gap": 6.0, "wma_slope": 0.5},
        timeline[6][0]: {"rsi14": 65.0, "gap": 5.0, "wma_slope": 0.2},
    }
    result = simulate_structural_exit(
        timeline=timeline, indicators=indicators, direction="BULLISH",
        entry_price=100.0, control_exit_at=BASE + timedelta(minutes=10),
        control_points=7.0, minimum_components=2,
    )
    assert result["candidate_exit"] is False
    assert result["armed_timestamp"] is None
