from __future__ import annotations

from dataclasses import dataclass

from red_bar_lab.services.nifty_futures_positioning import (
    INSUFFICIENT_DATA,
    NEUTRAL,
    NiftyFuturesPositioning,
)


STRONG = "STRONG"
MODERATE = "MODERATE"
WEAK = "WEAK"
INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True)
class NiftyFuturesPositioningStrength:
    status: str
    reason: str
    strength: str
    state: str
    price_change_pct: float | None = None
    oi_change_pct: float | None = None
    relative_volume: float | None = None
    price_threshold_pct: float = 0.02
    oi_threshold_pct: float = 0.02
    moderate_relative_volume: float = 0.8
    strong_relative_volume: float = 1.2


def assess_nifty_futures_positioning_strength(
    positioning: NiftyFuturesPositioning,
    *,
    price_threshold_pct: float = 0.02,
    oi_threshold_pct: float = 0.02,
    moderate_relative_volume: float = 0.8,
    strong_relative_volume: float = 1.2,
) -> NiftyFuturesPositioningStrength:
    """Grade completed-candle futures positioning without execution authority.

    Directional states require minimum absolute price and OI changes. Relative
    volume then separates strong, moderate and weak participation. Neutral or
    incomplete positioning never receives a directional strength grade.
    """

    price_threshold = abs(float(price_threshold_pct))
    oi_threshold = abs(float(oi_threshold_pct))
    moderate_rvol = max(0.0, float(moderate_relative_volume))
    strong_rvol = max(moderate_rvol, float(strong_relative_volume))

    state = str(getattr(positioning, "state", NEUTRAL) or NEUTRAL)
    status = str(getattr(positioning, "status", INSUFFICIENT_DATA) or INSUFFICIENT_DATA)
    price_pct = getattr(positioning, "price_change_pct", None)
    oi_pct = getattr(positioning, "oi_change_pct", None)
    relative_volume = getattr(positioning, "relative_volume", None)

    common = {
        "state": state,
        "price_change_pct": price_pct,
        "oi_change_pct": oi_pct,
        "relative_volume": relative_volume,
        "price_threshold_pct": price_threshold,
        "oi_threshold_pct": oi_threshold,
        "moderate_relative_volume": moderate_rvol,
        "strong_relative_volume": strong_rvol,
    }

    if status != "READY" or price_pct is None or oi_pct is None:
        return NiftyFuturesPositioningStrength(
            status=INSUFFICIENT_DATA,
            reason="Completed-candle price and OI changes are required for strength assessment.",
            strength=INSUFFICIENT,
            **common,
        )

    if state == NEUTRAL:
        return NiftyFuturesPositioningStrength(
            status="READY",
            reason="Neutral positioning has no directional strength grade.",
            strength=WEAK,
            **common,
        )

    if abs(float(price_pct)) < price_threshold or abs(float(oi_pct)) < oi_threshold:
        return NiftyFuturesPositioningStrength(
            status="READY",
            reason="Directional state is below the minimum price or OI change threshold.",
            strength=WEAK,
            **common,
        )

    if relative_volume is None:
        return NiftyFuturesPositioningStrength(
            status=INSUFFICIENT_DATA,
            reason="Relative volume is unavailable for participation strength assessment.",
            strength=INSUFFICIENT,
            **common,
        )

    rvol = float(relative_volume)
    if rvol >= strong_rvol:
        strength = STRONG
        reason = "Directional price and OI change are confirmed by strong relative volume."
    elif rvol >= moderate_rvol:
        strength = MODERATE
        reason = "Directional price and OI change have moderate relative-volume participation."
    else:
        strength = WEAK
        reason = "Directional price and OI change have weak relative-volume participation."

    return NiftyFuturesPositioningStrength(
        status="READY",
        reason=reason,
        strength=strength,
        **common,
    )


def futures_positioning_strength_log_values(
    result: NiftyFuturesPositioningStrength,
) -> tuple[str, ...]:
    return (
        result.status,
        result.reason,
        result.strength,
        result.state,
        "NA" if result.price_change_pct is None else f"{result.price_change_pct:.4f}",
        "NA" if result.oi_change_pct is None else f"{result.oi_change_pct:.4f}",
        "NA" if result.relative_volume is None else f"{result.relative_volume:.4f}",
    )
