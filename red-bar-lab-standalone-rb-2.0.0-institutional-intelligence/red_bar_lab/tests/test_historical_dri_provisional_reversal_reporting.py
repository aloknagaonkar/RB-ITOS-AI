import pandas as pd

from red_bar_lab.services.historical_dri_reversal_state import (
    HistoricalDRIReversalStateMachine,
    ReversalState,
)
from red_bar_lab.services.historical_dri_trailing_reporting import (
    attach_trailing_columns,
    summarize_trailing_audit,
)


def test_provisional_reversal_requires_two_closes_ema_and_momentum():
    machine = HistoricalDRIReversalStateMachine()
    machine.record_taken("BEARISH", invalidation_level=24400)
    candles = pd.DataFrame([
        {"timestamp":"2026-08-14T04:35:00Z","open":24300,"high":24320,"low":24295,"close":24315},
        {"timestamp":"2026-08-14T04:36:00Z","open":24315,"high":24340,"low":24310,"close":24335},
    ])
    decision = machine.evaluate_opposite_event(
        "BULLISH",
        close_price=24335,
        metrics={"momentum_ok":True,"ema_ok":True},
        setup_type="EARLY_1M_BULLISH_BREAK",
        candles=candles,
        moment="2026-08-14T10:06:00+05:30",
    )
    assert decision.provisional
    assert not decision.confirmed
    assert decision.state == ReversalState.PROVISIONAL_BULLISH_REVERSAL


def test_invalidation_break_upgrades_to_confirmed():
    machine = HistoricalDRIReversalStateMachine()
    machine.record_taken("BEARISH", invalidation_level=24320)
    candles = pd.DataFrame([
        {"timestamp":"2026-08-14T04:35:00Z","open":24300,"high":24320,"low":24295,"close":24315},
        {"timestamp":"2026-08-14T04:36:00Z","open":24315,"high":24340,"low":24310,"close":24335},
    ])
    decision = machine.evaluate_opposite_event(
        "BULLISH",
        close_price=24335,
        metrics={"momentum_ok":True,"ema_ok":True},
        setup_type="EARLY_1M_BULLISH_BREAK",
        candles=candles,
        moment="2026-08-14T10:06:00+05:30",
    )
    assert decision.confirmed
    assert not decision.provisional
    assert decision.state == ReversalState.ACTIVE_BULLISH


def test_trailing_reporting_columns_and_summary():
    audit = [{
        "signal_id":"HDRI-1",
        "entry_price":100.0,
        "baseline_exit":105.0,
        "exit_price":112.0,
        "return_pct":12.0,
        "exit_reason":"TRAILING_STOP",
        "activated":True,
        "protected_points":7.0,
    }]
    rows = [{"Bundle":"HDRI-1"}, {"Bundle":"HDRI-2"}]
    attach_trailing_columns(rows, audit)
    assert rows[0]["Trailing Exit"] == 112.0
    assert rows[1]["Trailing Exit"] is None
    summary = summarize_trailing_audit(audit)
    assert summary["trailing_net_points"] == 12.0
    assert summary["baseline_net_points_for_trailing_set"] == 5.0
