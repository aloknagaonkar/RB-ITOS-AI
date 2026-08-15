import inspect
from pathlib import Path

import pandas as pd

from red_bar_lab.execution.attribution_automation import (
    AttributionAwarePaperAutomationService,
)
from red_bar_lab.execution.trend_automation import (
    EMA10OpportunityIntelligenceEngine,
    TrendAwarePaperAutomationService,
)
from red_bar_lab.execution.exit_engine import PaperExitEngine
from red_bar_lab.services.historical_decision_replay import (
    HistoricalDecisionReplayService,
)


def _position():
    return {
        "entry_price": 100.0,
        "current_price": 103.0,
        "stop_price": 85.0,
        "initial_stop_price": 85.0,
        "target1_price": None,
        "target2_price": None,
        "mfe_points": 0.0,
    }


def _healthy_candle():
    return {
        "close": 103.0,
        "vwap": 100.0,
        "ema9": 102.0,
        "ema21": 101.0,
        "momentum_pct": 0.5,
        "relative_volume": 1.2,
    }


def _valid_signal():
    return {
        "direction": "BULLISH",
        "confirmation_high": 24600.0,
        "confirmation_low": 24500.0,
        "_ema10_5m_ready": True,
        "_ema10_5m_close": 24560.0,
        "_ema10_5m_value": 24550.0,
    }


def test_shadow_exit_warnings_do_not_change_operational_health_or_action():
    engine = PaperExitEngine()
    baseline = engine.evaluate(
        position=_position(),
        option_candle=_healthy_candle(),
        signal=_valid_signal(),
        current_underlying=24560.0,
    )
    shadow_warning = engine.evaluate(
        position=_position(),
        option_candle=_healthy_candle(),
        signal=_valid_signal(),
        current_underlying=24560.0,
        pcr_supportive=False,
        oi_supportive=False,
        greeks_supportive=False,
    )

    assert shadow_warning.shadow_oi_pcr == "WARNING"
    assert shadow_warning.shadow_greeks == "WARNING"
    assert shadow_warning.health_score == baseline.health_score
    assert shadow_warning.action == baseline.action
    assert shadow_warning.hard_exit_reason == baseline.hard_exit_reason


def test_historical_replay_uses_ema10_opportunity_engine_and_live_lookback():
    service = HistoricalDecisionReplayService(None)
    assert isinstance(
        service.opportunity_engine,
        EMA10OpportunityIntelligenceEngine,
    )

    source = inspect.getsource(
        HistoricalDecisionReplayService._run_live_parity_day
    )
    assert "trading_date - timedelta(days=7)" in source


def test_replay_ema10_uses_completed_5m_bars_only():
    timestamps = pd.date_range(
        "2026-08-07 09:15",
        periods=8,
        freq="1min",
        tz="Asia/Kolkata",
    )
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "close": [100, 101, 102, 103, 104, 200, 201, 202],
        }
    )

    snapshot = HistoricalDecisionReplayService._point_in_time_ema10(
        frame,
        pd.Timestamp("2026-08-07 09:22", tz="Asia/Kolkata"),
    )

    assert snapshot["_ema10_5m_ready"] is True
    assert snapshot["_ema10_5m_close"] == 104.0
    assert snapshot["_ema10_5m_value"] == 104.0
    assert "09:15:00" in snapshot["_ema10_5m_timestamp"]


def test_workspace_wires_foreground_to_attribution_aware_trend_service():
    workspace = (
        Path(__file__).parents[1]
        / "ui"
        / "workspace.py"
    ).read_text(encoding="utf-8")

    assert (
        "paper_trading.RedBarPaperAutomationService = "
        "AttributionAwarePaperAutomationService"
    ) in workspace
    assert issubclass(
        AttributionAwarePaperAutomationService,
        TrendAwarePaperAutomationService,
    )


def test_low_fidelity_replay_does_not_use_expectancy_as_execution_gate():
    source = inspect.getsource(HistoricalDecisionReplayService.run_day)

    assert "elif expectancy <= 0" not in source
    assert 'blocker = f"EXPECTANCY=' not in source
