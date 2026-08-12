from dataclasses import dataclass

from red_bar_lab.execution.opportunity_engine import (
    OpportunityIntelligenceEngine,
)


@dataclass(frozen=True)
class _Contract:
    option_type: str = "PE"


@dataclass(frozen=True)
class _Candidate:
    contract: _Contract = _Contract()
    total_score: float = 95.0
    spread_score: float = 15.0
    liquidity_score: float = 20.0
    volume_score: float = 15.0
    oi_score: float = 10.0
    vwap_score: float = 10.0
    ema_score: float = 10.0
    momentum_score: float = 10.0


def _bearish_signal():
    return {
        "signal_id": "RB-TEST",
        "direction": "BEARISH",
        "confirmation_high": 25000.0,
        "confirmation_low": 24970.0,
        "confirmation_close": 24980.0,
    }


def test_old_strong_signal_can_be_opportunity_extension_eligible():
    result = OpportunityIntelligenceEngine().evaluate(
        signal=_bearish_signal(),
        candidate=_Candidate(),
        spot_price=24970.0,
        signal_age_seconds=480.0,
        opposite_red_bar_confirmed=False,
    )
    assert result.entry_mode == "OPPORTUNITY_EXTENSION"
    assert result.eligible is True
    assert result.decision == "BUY PE"
    assert result.opportunity_score >= 85.0
    assert result.reward_remaining_pct >= 40.0


def test_old_signal_is_rejected_when_structure_invalid():
    result = OpportunityIntelligenceEngine().evaluate(
        signal=_bearish_signal(),
        candidate=_Candidate(),
        spot_price=25010.0,
        signal_age_seconds=480.0,
        opposite_red_bar_confirmed=False,
    )
    assert result.eligible is False
    assert result.decision == "SKIP"
    assert "STRUCTURE_INVALID" in result.reason


def test_old_signal_is_rejected_when_opposite_red_bar_exists():
    result = OpportunityIntelligenceEngine().evaluate(
        signal=_bearish_signal(),
        candidate=_Candidate(),
        spot_price=24970.0,
        signal_age_seconds=480.0,
        opposite_red_bar_confirmed=True,
    )
    assert result.eligible is False
    assert "OPPOSITE_RED_BAR" in result.reason


def test_old_signal_is_rejected_when_reward_is_consumed():
    result = OpportunityIntelligenceEngine().evaluate(
        signal=_bearish_signal(),
        candidate=_Candidate(),
        spot_price=24915.0,
        signal_age_seconds=480.0,
        opposite_red_bar_confirmed=False,
    )
    assert result.eligible is False
    assert result.reward_remaining_pct < 40.0
    assert "REWARD_CONSUMED" in result.reason


def test_fresh_signal_is_classified_as_fresh_signal():
    result = OpportunityIntelligenceEngine().evaluate(
        signal=_bearish_signal(),
        candidate=_Candidate(),
        spot_price=24975.0,
        signal_age_seconds=120.0,
        opposite_red_bar_confirmed=False,
    )
    assert result.entry_mode == "FRESH_SIGNAL"


def test_time_is_penalty_not_hard_rejection():
    engine = OpportunityIntelligenceEngine()
    recent_old = engine.evaluate(
        signal=_bearish_signal(),
        candidate=_Candidate(),
        spot_price=24970.0,
        signal_age_seconds=300.0,
        opposite_red_bar_confirmed=False,
    )
    much_older = engine.evaluate(
        signal=_bearish_signal(),
        candidate=_Candidate(),
        spot_price=24970.0,
        signal_age_seconds=1000.0,
        opposite_red_bar_confirmed=False,
    )
    assert recent_old.time_score > much_older.time_score
    assert much_older.time_score == 0.0
