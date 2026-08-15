from red_bar_lab.services.historical_dri_reversal_state import (
    HistoricalDRIReversalStateMachine,
    ReversalState,
)


def test_single_opposite_break_is_pending():
    machine = HistoricalDRIReversalStateMachine()
    machine.record_taken("BEARISH", invalidation_level=24300)
    decision = machine.evaluate_opposite_event(
        "BULLISH",
        close_price=24310,
        metrics={"momentum_ok": True, "ema_ok": True},
        setup_type="EARLY_1M_BULLISH_BREAK",
    )
    assert not decision.confirmed
    assert decision.state == ReversalState.PENDING_BULLISH_REVERSAL


def test_second_confirmed_opposite_break_flips_regime():
    machine = HistoricalDRIReversalStateMachine()
    machine.record_taken("BEARISH", invalidation_level=24300)
    machine.evaluate_opposite_event(
        "BULLISH",
        close_price=24310,
        metrics={"momentum_ok": True, "ema_ok": True},
        setup_type="EARLY_1M_BULLISH_BREAK",
    )
    decision = machine.evaluate_opposite_event(
        "BULLISH",
        close_price=24320,
        metrics={"momentum_ok": True, "ema_ok": True},
        setup_type="EARLY_1M_BULLISH_BREAK",
    )
    assert decision.confirmed
    assert decision.state == ReversalState.ACTIVE_BULLISH


def test_missing_ema_flip_stays_pending():
    machine = HistoricalDRIReversalStateMachine()
    machine.record_taken("BULLISH", invalidation_level=24280)
    for _ in range(2):
        decision = machine.evaluate_opposite_event(
            "BEARISH",
            close_price=24270,
            metrics={"momentum_ok": True, "ema_ok": False},
            setup_type="EARLY_1M_BEARISH_BREAK",
        )
    assert not decision.confirmed
    assert "EMA_FLIP" in decision.reason


def test_same_direction_event_clears_pending():
    machine = HistoricalDRIReversalStateMachine()
    machine.record_taken("BEARISH", invalidation_level=24300)
    machine.evaluate_opposite_event(
        "BULLISH",
        close_price=24310,
        metrics={"momentum_ok": True, "ema_ok": True},
        setup_type="EARLY_1M_BULLISH_BREAK",
    )
    decision = machine.evaluate_opposite_event(
        "BEARISH",
        close_price=24290,
        metrics={"momentum_ok": True, "ema_ok": True},
        setup_type="EARLY_1M_BEARISH_BREAK",
    )
    assert decision.state == ReversalState.ACTIVE_BEARISH
    assert machine.pending_direction is None
