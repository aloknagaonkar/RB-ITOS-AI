from __future__ import annotations

from collections.abc import Mapping, Sequence

from red_bar_lab.services.nifty_futures_market_data import NiftyFuturesMarketData
from red_bar_lab.services.nifty_futures_positioning import (
    INSUFFICIENT_DATA,
    NEUTRAL,
    NiftyFuturesPositioning,
    classify_nifty_futures_positioning,
)


def _value(candle: object, names: tuple[str, ...], index: int) -> object:
    if isinstance(candle, Mapping):
        for name in names:
            if name in candle:
                return candle.get(name)
        return None
    if isinstance(candle, Sequence) and not isinstance(candle, (str, bytes)):
        return candle[index] if len(candle) > index else None
    return None


def assess_futures_positioning(
    market_data: NiftyFuturesMarketData,
    *,
    baseline_window: int = 20,
) -> NiftyFuturesPositioning:
    """Assess completed-candle futures positioning without execution authority."""

    completed = list(market_data.completed_candles)
    if market_data.status != "READY" or len(completed) < 2:
        return NiftyFuturesPositioning(
            status=INSUFFICIENT_DATA,
            reason="At least two completed NIFTY futures candles are required.",
            state=NEUTRAL,
        )

    previous = completed[-2]
    latest = completed[-1]
    history = completed[:-1]
    if baseline_window > 0:
        history = history[-int(baseline_window):]

    return classify_nifty_futures_positioning(
        latest_close=_value(latest, ("close", "closing_price"), 4),
        previous_close=_value(previous, ("close", "closing_price"), 4),
        latest_oi=_value(latest, ("oi", "open_interest", "openInterest"), 6),
        previous_oi=_value(previous, ("oi", "open_interest", "openInterest"), 6),
        latest_volume=_value(latest, ("volume", "vol", "traded_volume"), 5),
        prior_volumes=[
            _value(candle, ("volume", "vol", "traded_volume"), 5)
            for candle in history
        ],
    )


def futures_positioning_log_values(
    result: NiftyFuturesPositioning,
) -> tuple[str, ...]:
    return (
        result.status,
        result.reason,
        result.state,
        "NA" if result.price_change is None else f"{result.price_change:.2f}",
        "NA" if result.price_change_pct is None else f"{result.price_change_pct:.4f}",
        "NA" if result.oi_change is None else f"{result.oi_change:.1f}",
        "NA" if result.oi_change_pct is None else f"{result.oi_change_pct:.4f}",
        "NA" if result.relative_volume is None else f"{result.relative_volume:.4f}",
        "NA" if result.baseline_volume is None else f"{result.baseline_volume:.1f}",
        str(result.baseline_samples),
    )
