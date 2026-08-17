from types import SimpleNamespace

from red_bar_lab.execution.execution_policy import (
    RSI_EXIT_MODE,
    resolve_execution_policy,
)
from red_bar_lab.execution.exit_engine import PaperExitEngine
from red_bar_lab.execution.paper_engine import PaperContract
from red_bar_lab.execution.trend_automation import EMA10OpportunityIntelligenceEngine


def _rsi_signal(direction="BULLISH"):
    return {
        "signal_id": "RSI-TEST-1",
        "direction": direction,
        "signal_source": "RSI_EXTREME_REVERSAL_V1",
        "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
        "confirmation_high": 110.0,
        "confirmation_low": 90.0,
        "confirmation_close": 100.0,
        "underlying_entry": 100.0,
        "_ema10_5m_ready": False,
        "_ema10_5m_close": None,
        "_ema10_5m_value": None,
    }


def _candidate(option_type="CE"):
    return SimpleNamespace(
        contract=PaperContract(
            instrument_token=1,
            tradingsymbol=f"NIFTYTEST{option_type}",
            exchange="NFO",
            option_type=option_type,
            strike=24000.0,
            expiry="2026-08-20",
            lot_size=75,
        ),
        total_score=70.0,
        spread_score=10.0,
        liquidity_score=15.0,
        volume_score=0.0,
        oi_score=0.0,
        vwap_score=0.0,
        ema_score=0.0,
        momentum_score=0.0,
    )


def _position(current, *, peak=None, stop=93.0):
    peak = current if peak is None else peak
    return {
        "entry_price": 100.0,
        "current_price": current,
        "initial_stop_price": 93.0,
        "stop_price": stop,
        "protected_stop_price": stop,
        "effective_stop": stop,
        "mfe_points": peak - 100.0,
        "target1_price": None,
        "target2_price": None,
    }


def test_reversal_exit_policy_is_unified_across_strategy_sources():
    rsi = resolve_execution_policy(_rsi_signal())
    assert rsi.stop_loss_pct == 7.0
    assert rsi.target_pct is None
    assert rsi.exit_mode == RSI_EXIT_MODE

    red_bar = resolve_execution_policy({
        "signal_id": "REF-1",
        "execution_strategy_source": "REFERENCE_LEVEL",
    })
    assert red_bar.stop_loss_pct == 7.0
    assert red_bar.target_pct is None
    assert red_bar.exit_mode == RSI_EXIT_MODE
    assert red_bar.directional_conflicts_observational is True


def test_rsi_entry_does_not_require_ema10_or_red_bar():
    result = EMA10OpportunityIntelligenceEngine(
        minimum_opportunity_score=85.0
    ).evaluate(
        signal=_rsi_signal(),
        candidate=_candidate(),
        spot_price=50.0,
        signal_age_seconds=60.0,
        opposite_red_bar_confirmed=True,
    )
    assert result.eligible is True
    assert "EMA10_DATA_UNAVAILABLE" not in result.reason
    assert "OPPOSITE_RED_BAR" not in result.reason
    assert "EMA10_INFORMATIONAL_ONLY" in result.reason


def test_non_rsi_still_requires_ema10():
    signal = _rsi_signal()
    signal.update({
        "signal_id": "REF-1",
        "signal_source": "REFERENCE_LEVEL",
        "execution_strategy_source": "REFERENCE_LEVEL",
    })
    result = EMA10OpportunityIntelligenceEngine(
        minimum_opportunity_score=0.0
    ).evaluate(
        signal=signal,
        candidate=_candidate(),
        spot_price=100.0,
        signal_age_seconds=60.0,
        opposite_red_bar_confirmed=False,
    )
    assert result.eligible is False
    assert "EMA10_DATA_UNAVAILABLE" in result.reason


def test_rsi_technical_exits_are_shadow_only():
    signal = _rsi_signal()
    signal.update({
        "_ema10_5m_ready": True,
        "_ema10_5m_close": 90.0,
        "_ema10_5m_value": 100.0,
    })
    health = PaperExitEngine().evaluate(
        position=_position(104.0),
        option_candle={
            "close": 90.0,
            "vwap": 100.0,
            "ema9": 90.0,
            "ema21": 100.0,
            "momentum_pct": -1.0,
            "relative_volume": 0.5,
        },
        signal=signal,
        current_underlying=80.0,
        opposite_red_bar_confirmed=True,
        exit_mode=RSI_EXIT_MODE,
    )
    assert health.hard_exit_reason is None
    assert health.action == "HOLD"
    assert any(x.startswith("SHADOW_EXIT_WARNINGS=") for x in health.reasons)


def test_rsi_stop_and_eod_remain_authoritative():
    engine = PaperExitEngine()
    stop = engine.evaluate(
        position=_position(92.5, peak=100.0),
        signal=_rsi_signal(),
        exit_mode=RSI_EXIT_MODE,
    )
    assert stop.hard_exit_reason in {"HARD_STOP", "PROTECTED_STOP"}

    eod = engine.evaluate(
        position=_position(101.0),
        signal=_rsi_signal(),
        eod_due=True,
        exit_mode=RSI_EXIT_MODE,
    )
    assert eod.hard_exit_reason == "EOD_EXIT"


def test_rsi_protection_ladder():
    engine = PaperExitEngine()
    assert engine.evaluate(
        position=_position(105.0, peak=105.0),
        signal=_rsi_signal(),
        exit_mode=RSI_EXIT_MODE,
    ).effective_stop == 100.0
    assert engine.evaluate(
        position=_position(108.0, peak=108.0),
        signal=_rsi_signal(),
        exit_mode=RSI_EXIT_MODE,
    ).effective_stop == 102.0
    assert engine.evaluate(
        position=_position(112.0, peak=112.0),
        signal=_rsi_signal(),
        exit_mode=RSI_EXIT_MODE,
    ).effective_stop == 106.4
    assert engine.evaluate(
        position=_position(125.0, peak=125.0, stop=106.4),
        signal=_rsi_signal(),
        exit_mode=RSI_EXIT_MODE,
    ).effective_stop == 118.75
