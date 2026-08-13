from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from red_bar_lab.intelligence.directional_features import DirectionalFeatureSnapshot
from red_bar_lab.intelligence.directional_regime import (
    DirectionalRegime,
    RegimeEvaluation,
    classify_directional_regime,
)


class ShadowDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class TransitionType(str, Enum):
    BULLISH_BREAKOUT = "BULLISH_BREAKOUT"
    BEARISH_BREAKDOWN = "BEARISH_BREAKDOWN"
    BULLISH_PULLBACK_CONTINUATION = "BULLISH_PULLBACK_CONTINUATION"
    BEARISH_PULLBACK_CONTINUATION = "BEARISH_PULLBACK_CONTINUATION"
    BULLISH_TRANSITION = "BULLISH_TRANSITION"
    BEARISH_TRANSITION = "BEARISH_TRANSITION"
    NO_TRANSITION = "NO_TRANSITION"


class ShadowDecision(str, Enum):
    NO_TRANSITION = "NO_TRANSITION"
    WATCH = "WATCH"
    TRANSITION_FORMING = "TRANSITION_FORMING"
    SHADOW_SIGNAL = "SHADOW_SIGNAL"
    STRONG_SHADOW_SIGNAL = "STRONG_SHADOW_SIGNAL"


@dataclass(frozen=True)
class DirectionalScore:
    structure: float
    ema: float
    dmi: float
    adx: float
    displacement: float
    regime: float

    @property
    def total(self) -> float:
        return round(
            self.structure
            + self.ema
            + self.dmi
            + self.adx
            + self.displacement
            + self.regime,
            2,
        )


@dataclass(frozen=True)
class ShadowDirectionalTransition:
    timestamp: object
    direction: ShadowDirection
    transition_type: TransitionType
    decision: ShadowDecision
    confidence: float
    bullish_score: DirectionalScore
    bearish_score: DirectionalScore
    regime: DirectionalRegime
    regime_confidence: float
    red_bar_support: str
    evidence: tuple[str, ...]
    invalidation_reason: str | None
    execution_allowed: bool = False

    def as_record(self) -> dict[str, object]:
        return {
            "timestamp": str(self.timestamp),
            "direction": self.direction.value,
            "transition_type": self.transition_type.value,
            "decision": self.decision.value,
            "confidence": self.confidence,
            "bullish_score": self.bullish_score.total,
            "bearish_score": self.bearish_score.total,
            "regime": self.regime.value,
            "regime_confidence": self.regime_confidence,
            "red_bar_support": self.red_bar_support,
            "evidence": list(self.evidence),
            "invalidation_reason": self.invalidation_reason,
            "execution_allowed": False,
        }


def _clamp_component(value: float, maximum: float) -> float:
    return round(max(0.0, min(maximum, value)), 2)


def _decision(score: float) -> ShadowDecision:
    if score >= 85:
        return ShadowDecision.STRONG_SHADOW_SIGNAL
    if score >= 75:
        return ShadowDecision.SHADOW_SIGNAL
    if score >= 65:
        return ShadowDecision.TRANSITION_FORMING
    if score >= 50:
        return ShadowDecision.WATCH
    return ShadowDecision.NO_TRANSITION


def _red_bar_support(
    direction: ShadowDirection,
    red_bar_context: Mapping[str, object] | None,
) -> str:
    if not red_bar_context:
        return "NOT_AVAILABLE"
    raw = str(
        red_bar_context.get("direction")
        or red_bar_context.get("signal_direction")
        or ""
    ).upper()
    if direction is ShadowDirection.NEUTRAL or raw not in {"BULLISH", "BEARISH"}:
        return "NEUTRAL"
    return "ALIGNED" if raw == direction.value else "CONFLICTING"


def evaluate_shadow_directional_transition(
    features: DirectionalFeatureSnapshot,
    *,
    regime: RegimeEvaluation | None = None,
    red_bar_context: Mapping[str, object] | None = None,
) -> ShadowDirectionalTransition:
    """Evaluate one observation-only directional transition.

    Red Bar is optional supporting evidence and contributes zero points.
    """
    regime = regime or classify_directional_regime(features)
    bullish_evidence: list[str] = []
    bearish_evidence: list[str] = []

    bull_structure = 0.0
    bear_structure = 0.0
    if features.breakout:
        bull_structure += 18
        bullish_evidence.append("SWING_HIGH_BREAKOUT")
    if features.breakdown:
        bear_structure += 18
        bearish_evidence.append("SWING_LOW_BREAKDOWN")
    if features.bullish_structure:
        bull_structure += 7
        bullish_evidence.append("HIGHER_HIGH_HIGHER_LOW")
    if features.bearish_structure:
        bear_structure += 7
        bearish_evidence.append("LOWER_HIGH_LOWER_LOW")

    bull_ema = 0.0
    bear_ema = 0.0
    if features.ema_fast_slope_atr > 0:
        bull_ema += 7
        bullish_evidence.append("EMA_FAST_SLOPE_POSITIVE")
    else:
        bear_ema += 7
        bearish_evidence.append("EMA_FAST_SLOPE_NEGATIVE")
    if features.ema_slow_slope_atr > 0:
        bull_ema += 5
    elif features.ema_slow_slope_atr < 0:
        bear_ema += 5
    if features.ema_fast_acceleration_atr > 0:
        bull_ema += 4
        bullish_evidence.append("EMA_ACCELERATION_POSITIVE")
    elif features.ema_fast_acceleration_atr < 0:
        bear_ema += 4
        bearish_evidence.append("EMA_ACCELERATION_NEGATIVE")
    if features.ema_spread_atr > 0:
        bull_ema += 4
    elif features.ema_spread_atr < 0:
        bear_ema += 4

    di_gap = abs(features.plus_di - features.minus_di)
    dmi_points = _clamp_component(6.0 + di_gap * 0.3, 15.0)
    if features.plus_di > features.minus_di:
        bull_dmi = dmi_points
        bear_dmi = 0.0
        bullish_evidence.append("PLUS_DI_DOMINANT")
    elif features.minus_di > features.plus_di:
        bull_dmi = 0.0
        bear_dmi = dmi_points
        bearish_evidence.append("MINUS_DI_DOMINANT")
    else:
        bull_dmi = bear_dmi = 0.0

    adx_points = _clamp_component((features.adx - 15.0) * 0.5, 10.0)
    bull_adx = adx_points if features.plus_di > features.minus_di else 0.0
    bear_adx = adx_points if features.minus_di > features.plus_di else 0.0
    if features.adx_slope > 0:
        if bull_adx:
            bullish_evidence.append("ADX_RISING")
        if bear_adx:
            bearish_evidence.append("ADX_RISING")

    bull_displacement = _clamp_component(max(features.displacement_atr, 0.0) * 7.5, 15.0)
    bear_displacement = _clamp_component(max(-features.displacement_atr, 0.0) * 7.5, 15.0)
    if bull_displacement:
        bullish_evidence.append("POSITIVE_ATR_DISPLACEMENT")
    if bear_displacement:
        bearish_evidence.append("NEGATIVE_ATR_DISPLACEMENT")

    bullish_regimes = {
        DirectionalRegime.TRENDING_BULLISH: 15.0,
        DirectionalRegime.EXPANSION: 10.0 if features.displacement_atr > 0 else 0.0,
        DirectionalRegime.PULLBACK: 8.0 if features.ema_spread_atr > 0 else 0.0,
    }
    bearish_regimes = {
        DirectionalRegime.TRENDING_BEARISH: 15.0,
        DirectionalRegime.EXPANSION: 10.0 if features.displacement_atr < 0 else 0.0,
        DirectionalRegime.PULLBACK: 8.0 if features.ema_spread_atr < 0 else 0.0,
    }
    bull_regime = bullish_regimes.get(regime.regime, 0.0)
    bear_regime = bearish_regimes.get(regime.regime, 0.0)

    bull = DirectionalScore(
        _clamp_component(bull_structure, 25),
        _clamp_component(bull_ema, 20),
        bull_dmi,
        bull_adx,
        bull_displacement,
        bull_regime,
    )
    bear = DirectionalScore(
        _clamp_component(bear_structure, 25),
        _clamp_component(bear_ema, 20),
        bear_dmi,
        bear_adx,
        bear_displacement,
        bear_regime,
    )

    if bull.total > bear.total:
        direction = ShadowDirection.BULLISH
        winning = bull.total
        evidence = bullish_evidence
    elif bear.total > bull.total:
        direction = ShadowDirection.BEARISH
        winning = bear.total
        evidence = bearish_evidence
    else:
        direction = ShadowDirection.NEUTRAL
        winning = bull.total
        evidence = []

    confidence = round(max(0.0, min(100.0, winning)), 2)
    decision = _decision(confidence)
    invalidation: str | None = None

    if direction is ShadowDirection.BULLISH:
        if features.breakout:
            transition_type = TransitionType.BULLISH_BREAKOUT
        elif regime.regime is DirectionalRegime.PULLBACK and features.ema_spread_atr > 0:
            transition_type = TransitionType.BULLISH_PULLBACK_CONTINUATION
        else:
            transition_type = TransitionType.BULLISH_TRANSITION
        if features.breakdown:
            invalidation = "SIMULTANEOUS_BEARISH_STRUCTURE_BREAK"
    elif direction is ShadowDirection.BEARISH:
        if features.breakdown:
            transition_type = TransitionType.BEARISH_BREAKDOWN
        elif regime.regime is DirectionalRegime.PULLBACK and features.ema_spread_atr < 0:
            transition_type = TransitionType.BEARISH_PULLBACK_CONTINUATION
        else:
            transition_type = TransitionType.BEARISH_TRANSITION
        if features.breakout:
            invalidation = "SIMULTANEOUS_BULLISH_STRUCTURE_BREAK"
    else:
        transition_type = TransitionType.NO_TRANSITION
        decision = ShadowDecision.NO_TRANSITION
        invalidation = "DIRECTIONAL_SCORES_TIED"

    if regime.regime is DirectionalRegime.COMPRESSION and decision in {
        ShadowDecision.SHADOW_SIGNAL,
        ShadowDecision.STRONG_SHADOW_SIGNAL,
    }:
        decision = ShadowDecision.TRANSITION_FORMING
        invalidation = "COMPRESSION_REQUIRES_EXPANSION_CONFIRMATION"

    return ShadowDirectionalTransition(
        timestamp=features.timestamp,
        direction=direction,
        transition_type=transition_type,
        decision=decision,
        confidence=confidence,
        bullish_score=bull,
        bearish_score=bear,
        regime=regime.regime,
        regime_confidence=regime.confidence,
        red_bar_support=_red_bar_support(direction, red_bar_context),
        evidence=tuple(evidence),
        invalidation_reason=invalidation,
        execution_allowed=False,
    )
