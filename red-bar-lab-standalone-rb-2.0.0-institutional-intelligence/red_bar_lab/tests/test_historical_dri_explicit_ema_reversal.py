import pandas as pd

from red_bar_lab.services.historical_dri_reversal_state import (
    HistoricalDRIReversalStateMachine,
    ReversalState,
)


def _bullish_frame():
    return pd.DataFrame([
        {"timestamp":"2026-08-14T04:30:00Z","open":99,"high":100,"low":98,"close":99},
        {"timestamp":"2026-08-14T04:31:00Z","open":99,"high":101,"low":99,"close":100},
        {"timestamp":"2026-08-14T04:32:00Z","open":100,"high":103,"low":100,"close":102},
        {"timestamp":"2026-08-14T04:33:00Z","open":102,"high":106,"low":102,"close":105},
    ])


def test_explicit_ema10_can_create_provisional_reversal():
    machine = HistoricalDRIReversalStateMachine()
    machine.record_taken("BEARISH", invalidation_level=120)
    decision = machine.evaluate_opposite_event(
        "BULLISH",
        close_price=105,
        metrics={"momentum_ok":True,"ema_ok":False},
        setup_type="EARLY_1M_BULLISH_BREAK",
        candles=_bullish_frame(),
        moment="2026-08-14T10:03:00+05:30",
    )
    assert decision.ema10_ok is True
    assert decision.provisional or decision.confirmed


def test_ema30_or_invalidation_can_confirm():
    machine = HistoricalDRIReversalStateMachine()
    machine.record_taken("BEARISH", invalidation_level=104)
    decision = machine.evaluate_opposite_event(
        "BULLISH",
        close_price=105,
        metrics={"momentum_ok":True,"ema_ok":False},
        setup_type="EARLY_1M_BULLISH_BREAK",
        candles=_bullish_frame(),
        moment="2026-08-14T10:03:00+05:30",
    )
    assert decision.confirmed
    assert decision.state == ReversalState.ACTIVE_BULLISH
