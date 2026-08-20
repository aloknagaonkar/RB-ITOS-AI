from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Iterable


LONG_BUILDUP = "LONG_BUILDUP"
SHORT_BUILDUP = "SHORT_BUILDUP"
SHORT_COVERING = "SHORT_COVERING"
LONG_UNWINDING = "LONG_UNWINDING"
NEUTRAL = "NEUTRAL"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class NiftyFuturesPositioning:
    status: str
    reason: str
    state: str
    price_change: float | None = None
    price_change_pct: float | None = None
    oi_change: float | None = None
    oi_change_pct: float | None = None
    relative_volume: float | None = None
    baseline_volume: float | None = None
    baseline_samples: int = 0


def _number(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100.0


def classify_nifty_futures_positioning(
    *,
    latest_close: object,
    previous_close: object,
    latest_oi: object,
    previous_oi: object,
    latest_volume: object,
    prior_volumes: Iterable[object] = (),
    price_change_threshold_pct: float = 0.0,
    oi_change_threshold_pct: float = 0.0,
) -> NiftyFuturesPositioning:
    """Classify futures price/OI positioning from completed candles only.

    Price up + OI up identifies long buildup; price down + OI up identifies
    short buildup; price up + OI down identifies short covering; price down +
    OI down identifies long unwinding. Relative volume is informational and is
    calculated against positive prior completed-candle volumes, excluding the
    latest candle. This result has no execution authority.
    """

    current_close = _number(latest_close)
    prior_close = _number(previous_close)
    current_oi = _number(latest_oi)
    prior_oi = _number(previous_oi)
    current_volume = _number(latest_volume)

    if None in (current_close, prior_close, current_oi, prior_oi):
        return NiftyFuturesPositioning(
            status=INSUFFICIENT_DATA,
            reason="Two completed futures candles with close and OI are required.",
            state=NEUTRAL,
        )

    price_change = current_close - prior_close
    oi_change = current_oi - prior_oi
    price_change_pct = _pct_change(current_close, prior_close)
    oi_change_pct = _pct_change(current_oi, prior_oi)

    baseline_values = [
        value
        for raw in prior_volumes
        if (value := _number(raw)) is not None and value > 0
    ]
    baseline_volume = fmean(baseline_values) if baseline_values else None
    relative_volume = (
        current_volume / baseline_volume
        if current_volume is not None
        and current_volume >= 0
        and baseline_volume is not None
        and baseline_volume > 0
        else None
    )

    price_up = (
        price_change_pct is not None
        and price_change_pct > abs(float(price_change_threshold_pct))
    )
    price_down = (
        price_change_pct is not None
        and price_change_pct < -abs(float(price_change_threshold_pct))
    )
    oi_up = (
        oi_change_pct is not None
        and oi_change_pct > abs(float(oi_change_threshold_pct))
    )
    oi_down = (
        oi_change_pct is not None
        and oi_change_pct < -abs(float(oi_change_threshold_pct))
    )

    if price_up and oi_up:
        state = LONG_BUILDUP
    elif price_down and oi_up:
        state = SHORT_BUILDUP
    elif price_up and oi_down:
        state = SHORT_COVERING
    elif price_down and oi_down:
        state = LONG_UNWINDING
    else:
        state = NEUTRAL

    return NiftyFuturesPositioning(
        status="READY",
        reason="Completed-candle futures price, OI and relative volume were assessed.",
        state=state,
        price_change=price_change,
        price_change_pct=price_change_pct,
        oi_change=oi_change,
        oi_change_pct=oi_change_pct,
        relative_volume=relative_volume,
        baseline_volume=baseline_volume,
        baseline_samples=len(baseline_values),
    )
