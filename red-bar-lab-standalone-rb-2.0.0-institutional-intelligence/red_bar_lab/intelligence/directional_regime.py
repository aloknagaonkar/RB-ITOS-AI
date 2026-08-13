from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from red_bar_lab.intelligence.directional_features import DirectionalFeatureSnapshot


class DirectionalRegime(str, Enum):
    TRENDING_BULLISH = "TRENDING_BULLISH"
    TRENDING_BEARISH = "TRENDING_BEARISH"
    RANGE = "RANGE"
    COMPRESSION = "COMPRESSION"
    EXPANSION = "EXPANSION"
    PULLBACK = "PULLBACK"
    REVERSAL_RISK = "REVERSAL_RISK"
    UNSTABLE = "UNSTABLE"


@dataclass(frozen=True)
class RegimeEvaluation:
    regime: DirectionalRegime
    confidence: float
    reason: str


def classify_directional_regime(
    features: DirectionalFeatureSnapshot,
) -> RegimeEvaluation:
    """Classify the current completed-candle regime with explicit evidence."""
    if features.compression_ratio <= 0.65 and features.adx < 22:
        return RegimeEvaluation(
            DirectionalRegime.COMPRESSION,
            min(100.0, 70.0 + (0.65 - features.compression_ratio) * 60.0),
            "NARROW_RANGE_AND_WEAK_ADX",
        )

    if features.range_atr >= 1.35 or abs(features.displacement_atr) >= 1.5:
        return RegimeEvaluation(
            DirectionalRegime.EXPANSION,
            min(100.0, 65.0 + max(features.range_atr - 1.0, 0.0) * 25.0),
            "ATR_NORMALIZED_RANGE_EXPANSION",
        )

    bullish_alignment = (
        features.price_above_fast
        and features.price_above_slow
        and features.ema_fast_slope_atr > 0
        and features.ema_slow_slope_atr >= 0
        and features.plus_di > features.minus_di
    )
    bearish_alignment = (
        not features.price_above_fast
        and not features.price_above_slow
        and features.ema_fast_slope_atr < 0
        and features.ema_slow_slope_atr <= 0
        and features.minus_di > features.plus_di
    )

    if bullish_alignment and features.adx >= 20:
        return RegimeEvaluation(
            DirectionalRegime.TRENDING_BULLISH,
            min(100.0, 55.0 + features.adx),
            "EMA_DMI_ADX_BULLISH_ALIGNMENT",
        )

    if bearish_alignment and features.adx >= 20:
        return RegimeEvaluation(
            DirectionalRegime.TRENDING_BEARISH,
            min(100.0, 55.0 + features.adx),
            "EMA_DMI_ADX_BEARISH_ALIGNMENT",
        )

    if features.ema_spread_atr > 0 and not features.price_above_fast:
        return RegimeEvaluation(
            DirectionalRegime.PULLBACK,
            70.0,
            "PRICE_PULLBACK_INSIDE_BULLISH_EMA_STRUCTURE",
        )

    if features.ema_spread_atr < 0 and features.price_above_fast:
        return RegimeEvaluation(
            DirectionalRegime.PULLBACK,
            70.0,
            "PRICE_PULLBACK_INSIDE_BEARISH_EMA_STRUCTURE",
        )

    if (
        features.ema_spread_atr > 0
        and features.ema_fast_slope_atr < 0
        and features.minus_di > features.plus_di
    ) or (
        features.ema_spread_atr < 0
        and features.ema_fast_slope_atr > 0
        and features.plus_di > features.minus_di
    ):
        return RegimeEvaluation(
            DirectionalRegime.REVERSAL_RISK,
            72.0,
            "EMA_STRUCTURE_AND_CURRENT_PRESSURE_DIVERGE",
        )

    if features.adx < 18 and abs(features.displacement_atr) < 0.8:
        return RegimeEvaluation(
            DirectionalRegime.RANGE,
            70.0,
            "WEAK_ADX_AND_LIMITED_DISPLACEMENT",
        )

    return RegimeEvaluation(
        DirectionalRegime.UNSTABLE,
        50.0,
        "MIXED_DIRECTIONAL_EVIDENCE",
    )
