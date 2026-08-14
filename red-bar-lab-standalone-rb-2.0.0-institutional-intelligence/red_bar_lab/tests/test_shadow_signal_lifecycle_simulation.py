from red_bar_lab.services.shadow_signal_lifecycle_simulation import (
    SimulationConfig,
    apply_simulation,
    ShadowSignalLifecycleSimulationService,
)


def row(
    timestamp,
    *,
    direction="BULLISH",
    correct=True,
    regime="EXPANSION",
    breakout=True,
):
    return {
        "timestamp": timestamp,
        "direction": direction,
        "direction_correct_5m": correct,
        "direction_correct_15m": correct,
        "direction_correct_30m": correct,
        "maximum_favorable_excursion": 20.0 if correct else 8.0,
        "maximum_adverse_excursion": 6.0 if correct else 18.0,
        "regime": regime,
        "time_bucket": "MORNING_1030_1159",
        "breakout": breakout,
        "breakdown": False,
        "ema_spread_atr": 0.5,
        "directional_displacement_atr": 1.0,
        "evidence": [
            "ADX_RISING",
            "SWING_HIGH_BREAKOUT",
            "POSITIVE_ATR_DISPLACEMENT",
        ],
    }


def test_cooldown_suppresses_close_same_direction_signal():
    rows = [
        row("2026-08-01 10:00:00"),
        row("2026-08-01 10:05:00"),
        row("2026-08-01 10:40:00"),
    ]
    accepted, suppressed = apply_simulation(
        rows,
        SimulationConfig(name="TEST", cooldown_minutes=30),
    )
    assert len(accepted) == 2
    assert len(suppressed) == 1
    assert suppressed[0]["suppression_reason"] == "COOLDOWN_SUPPRESSED"


def test_failure_lockout_suppresses_after_failed_signal():
    rows = [
        row("2026-08-01 10:00:00", correct=False),
        row("2026-08-01 10:30:00"),
        row("2026-08-01 11:10:00"),
    ]
    accepted, suppressed = apply_simulation(
        rows,
        SimulationConfig(name="TEST", failure_lockout_minutes=60),
    )
    assert len(accepted) == 2
    assert len(suppressed) == 1
    assert suppressed[0]["suppression_reason"] == "FAILURE_LOCKOUT_SUPPRESSED"


def test_one_signal_per_move_suppresses_repeated_move():
    rows = [
        row("2026-08-01 10:00:00"),
        row("2026-08-01 10:40:00"),
    ]
    accepted, suppressed = apply_simulation(
        rows,
        SimulationConfig(name="TEST", one_signal_per_move=True),
    )
    assert len(accepted) == 1
    assert suppressed[0]["suppression_reason"] == "SAME_MOVE_SUPPRESSED"


def test_default_service_returns_ranked_comparisons():
    rows = [
        row("2026-08-01 10:00:00"),
        row("2026-08-01 10:05:00", correct=False),
        row("2026-08-01 10:40:00"),
    ]
    result = ShadowSignalLifecycleSimulationService().evaluate(rows)
    assert len(result["summaries"]) >= 10
    assert result["ranked"]
    assert result["execution_allowed"] is False
    assert all(
        summary["execution_allowed"] is False
        for summary in result["summaries"]
    )
