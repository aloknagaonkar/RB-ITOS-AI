import pandas as pd
from red_bar_lab.services.historical_dri_reversal_state import (
    HistoricalDRIReversalStateMachine,
    ReversalState,
)


def test_two_underlying_closes_confirm_without_second_dri():
    machine = HistoricalDRIReversalStateMachine()
    machine.record_taken("BEARISH", invalidation_level=24300)
    candles = pd.DataFrame([
        {"timestamp":"2026-08-14T04:35:00Z","open":24290,"high":24305,"low":24288,"close":24302},
        {"timestamp":"2026-08-14T04:36:00Z","open":24302,"high":24320,"low":24300,"close":24318},
    ])
    decision = machine.evaluate_opposite_event(
        "BULLISH",
        close_price=24318,
        metrics={"momentum_ok":True,"ema_ok":True},
        setup_type="EARLY_1M_BULLISH_BREAK",
        candles=candles,
        moment="2026-08-14T10:06:00+05:30",
    )
    assert decision.confirmed
    assert decision.state == ReversalState.ACTIVE_BULLISH


def test_missing_two_closes_stays_pending():
    machine = HistoricalDRIReversalStateMachine()
    machine.record_taken("BEARISH", invalidation_level=24300)
    candles = pd.DataFrame([
        {"timestamp":"2026-08-14T04:35:00Z","open":24290,"high":24305,"low":24288,"close":24302},
        {"timestamp":"2026-08-14T04:36:00Z","open":24304,"high":24310,"low":24295,"close":24298},
    ])
    decision = machine.evaluate_opposite_event(
        "BULLISH",
        close_price=24310,
        metrics={"momentum_ok":True,"ema_ok":True},
        setup_type="EARLY_1M_BULLISH_BREAK",
        candles=candles,
        moment="2026-08-14T10:06:00+05:30",
    )
    assert not decision.confirmed
    assert "TWO_UNDERLYING_CLOSES" in decision.reason
