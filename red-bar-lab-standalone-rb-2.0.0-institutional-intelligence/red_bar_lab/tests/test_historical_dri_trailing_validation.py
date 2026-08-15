import pandas as pd
from red_bar_lab.services.historical_dri_trailing_validation import (
    simulate_trailing_stop,
)


def test_trailing_stop_activates_and_locks_profit():
    candles = pd.DataFrame([
        {"timestamp":"2026-08-14T04:31:00Z","high":108.0,"low":103.0,"close":107.0},
        {"timestamp":"2026-08-14T04:32:00Z","high":120.0,"low":116.0,"close":119.0},
        {"timestamp":"2026-08-14T04:33:00Z","high":121.0,"low":114.0,"close":115.0},
    ])
    result = simulate_trailing_stop(
        candles,
        entry_moment="2026-08-14T10:00:00+05:30",
        entry_price=100.0,
        baseline_exit_price=110.0,
    )
    assert result.activated
    assert result.exit_reason == "TRAILING_STOP"
    assert result.exit_price >= 114.0
    assert result.protected_points > 0


def test_initial_stop_applies_before_activation():
    candles = pd.DataFrame([
        {"timestamp":"2026-08-14T04:31:00Z","high":103.0,"low":89.0,"close":91.0},
    ])
    result = simulate_trailing_stop(
        candles,
        entry_moment="2026-08-14T10:00:00+05:30",
        entry_price=100.0,
    )
    assert not result.activated
    assert result.exit_reason == "INITIAL_STOP"
    assert result.exit_price == 90.0
