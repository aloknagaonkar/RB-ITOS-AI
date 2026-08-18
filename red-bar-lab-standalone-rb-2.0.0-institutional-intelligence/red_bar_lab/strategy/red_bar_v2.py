from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum

import pandas as pd

from red_bar_lab.intelligence.market_context import (
    MarketIndicatorSnapshot,
    aggregate_completed_5m,
    completed_candles,
)


class RedBarV2State(str, Enum):
    REFERENCE_NOT_READY = "REFERENCE_NOT_READY"
    NEUTRAL = "NEUTRAL"
    INITIAL_BULLISH = "INITIAL_BULLISH"
    INITIAL_BEARISH = "INITIAL_BEARISH"
    PROVISIONAL_BULLISH = "PROVISIONAL_BULLISH"
    PROVISIONAL_BEARISH = "PROVISIONAL_BEARISH"
    CONFIRMED_BULLISH = "CONFIRMED_BULLISH"
    CONFIRMED_BEARISH = "CONFIRMED_BEARISH"


class RedBarV2EventType(str, Enum):
    REFERENCE_READY = "REFERENCE_READY"
    INITIAL_BULLISH_ALIGNMENT = "INITIAL_BULLISH_ALIGNMENT"
    INITIAL_BEARISH_ALIGNMENT = "INITIAL_BEARISH_ALIGNMENT"
    BULLISH_REVERSAL_DETECTED = "BULLISH_REVERSAL_DETECTED"
    BEARISH_REVERSAL_DETECTED = "BEARISH_REVERSAL_DETECTED"
    FULL_DIRECTIONAL_ALIGNMENT = "FULL_DIRECTIONAL_ALIGNMENT"
    NO_DIRECTIONAL_ALIGNMENT = "NO_DIRECTIONAL_ALIGNMENT"
    CONTEXT_INVALID = "CONTEXT_INVALID"


@dataclass(frozen=True)
class RedBarV2Reference:
    instrument_key: str
    trading_date: str
    reference_timestamp: datetime
    reference_open: float
    reference_high: float
    reference_low: float
    reference_close: float
    midpoint: float
    interval_minutes: int = 5
    level_type: str = "NEXT_RED_CANDLE"
    strategy_version: str = "RED_BAR_V2"


@dataclass(frozen=True)
class RedBarV2DirectionDecision:
    event_type: RedBarV2EventType
    state: RedBarV2State
    direction: str | None
    option_side: str | None
    entry_type: str | None
    trend_strength: str | None
    context_timestamp: datetime | None
    reference_timestamp: datetime | None
    close_price: float | None
    rsi_value: float | None
    vwap_value: float | None
    rsi_aligned: bool
    vwap_aligned: bool
    midpoint_aligned: bool
    context_fresh: bool
    reason: str


def build_red_bar_v2_reference(
    candles: pd.DataFrame,
    *,
    instrument_key: str,
    evaluation_time: datetime | pd.Timestamp,
) -> RedBarV2Reference | None:
    """Build the fixed NEXT_RED_CANDLE reference from completed candles only.

    The first completed 5-minute candle of the session (09:15-09:20) is always
    ignored, regardless of colour. The first later completed red 5-minute candle
    is selected and remains deterministic for the session.
    """
    completed_1m = completed_candles(
        candles,
        evaluation_time=evaluation_time,
        interval_minutes=1,
    )
    if completed_1m.empty:
        return None

    bars = aggregate_completed_5m(completed_1m)
    if bars.empty:
        return None

    evaluated_at = pd.Timestamp(evaluation_time)
    trading_date = evaluated_at.date()
    session = bars[
        (bars.index.date == trading_date)
        & (bars.index.time >= time(9, 20))
        & (bars["close"] < bars["open"])
    ]
    if session.empty:
        return None

    row = session.iloc[0]
    timestamp = pd.Timestamp(session.index[0]).to_pydatetime()
    high = float(row["high"])
    low = float(row["low"])
    return RedBarV2Reference(
        instrument_key=instrument_key,
        trading_date=timestamp.date().isoformat(),
        reference_timestamp=timestamp,
        reference_open=float(row["open"]),
        reference_high=high,
        reference_low=low,
        reference_close=float(row["close"]),
        midpoint=(high + low) / 2.0,
    )


def _invalid_context_decision(
    reference: RedBarV2Reference | None,
    context: MarketIndicatorSnapshot | None,
) -> RedBarV2DirectionDecision:
    reason = "The NEXT_RED_CANDLE reference is not ready."
    state = RedBarV2State.REFERENCE_NOT_READY
    if reference is not None:
        state = RedBarV2State.NEUTRAL
        if context is None:
            reason = "Market context is unavailable."
        else:
            reason = f"Market context is not valid: {context.data_quality}."
    return RedBarV2DirectionDecision(
        event_type=RedBarV2EventType.CONTEXT_INVALID,
        state=state,
        direction=None,
        option_side=None,
        entry_type=None,
        trend_strength=None,
        context_timestamp=context.candle_timestamp if context else None,
        reference_timestamp=reference.reference_timestamp if reference else None,
        close_price=context.candle_close if context else None,
        rsi_value=context.rsi_value if context else None,
        vwap_value=context.vwap_value if context else None,
        rsi_aligned=False,
        vwap_aligned=False,
        midpoint_aligned=False,
        context_fresh=bool(context and context.fresh),
        reason=reason,
    )


def _valid_context(
    reference: RedBarV2Reference | None,
    context: MarketIndicatorSnapshot | None,
    timeframe: str,
) -> bool:
    return bool(
        reference is not None
        and context is not None
        and context.timeframe == timeframe
        and context.data_quality == "VALID"
        and context.fresh
        and context.rsi_value is not None
        and context.vwap_value is not None
        and context.trading_date == reference.trading_date
    )


def evaluate_initial_direction(
    reference: RedBarV2Reference | None,
    context: MarketIndicatorSnapshot | None,
    *,
    bullish_threshold: float = 55.0,
    bearish_threshold: float = 45.0,
) -> RedBarV2DirectionDecision:
    """Evaluate the initial Red Bar V2 direction from a completed 1-minute bar."""
    if not _valid_context(reference, context, "1M"):
        return _invalid_context_decision(reference, context)
    assert reference is not None and context is not None
    assert context.rsi_value is not None and context.vwap_value is not None

    bullish_rsi = context.rsi_value > bullish_threshold
    bearish_rsi = context.rsi_value < bearish_threshold
    bullish_vwap = context.candle_close > context.vwap_value
    bearish_vwap = context.candle_close < context.vwap_value
    bullish_midpoint = context.candle_close > reference.midpoint
    bearish_midpoint = context.candle_close < reference.midpoint

    if bullish_rsi and bullish_vwap and bullish_midpoint:
        return RedBarV2DirectionDecision(
            event_type=RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT,
            state=RedBarV2State.CONFIRMED_BULLISH,
            direction="BULLISH",
            option_side="CE",
            entry_type="INITIAL",
            trend_strength="CONFIRMED",
            context_timestamp=context.candle_timestamp,
            reference_timestamp=reference.reference_timestamp,
            close_price=context.candle_close,
            rsi_value=context.rsi_value,
            vwap_value=context.vwap_value,
            rsi_aligned=True,
            vwap_aligned=True,
            midpoint_aligned=True,
            context_fresh=True,
            reason="The completed 1-minute candle is above midpoint and VWAP with RSI above 55.",
        )

    if bearish_rsi and bearish_vwap and bearish_midpoint:
        return RedBarV2DirectionDecision(
            event_type=RedBarV2EventType.INITIAL_BEARISH_ALIGNMENT,
            state=RedBarV2State.CONFIRMED_BEARISH,
            direction="BEARISH",
            option_side="PE",
            entry_type="INITIAL",
            trend_strength="CONFIRMED",
            context_timestamp=context.candle_timestamp,
            reference_timestamp=reference.reference_timestamp,
            close_price=context.candle_close,
            rsi_value=context.rsi_value,
            vwap_value=context.vwap_value,
            rsi_aligned=True,
            vwap_aligned=True,
            midpoint_aligned=True,
            context_fresh=True,
            reason="The completed 1-minute candle is below midpoint and VWAP with RSI below 45.",
        )

    return RedBarV2DirectionDecision(
        event_type=RedBarV2EventType.NO_DIRECTIONAL_ALIGNMENT,
        state=RedBarV2State.NEUTRAL,
        direction=None,
        option_side=None,
        entry_type=None,
        trend_strength=None,
        context_timestamp=context.candle_timestamp,
        reference_timestamp=reference.reference_timestamp,
        close_price=context.candle_close,
        rsi_value=context.rsi_value,
        vwap_value=context.vwap_value,
        rsi_aligned=bullish_rsi or bearish_rsi,
        vwap_aligned=bullish_vwap or bearish_vwap,
        midpoint_aligned=bullish_midpoint or bearish_midpoint,
        context_fresh=True,
        reason="The completed 1-minute candle does not have full RSI, VWAP, and midpoint alignment.",
    )


def evaluate_reversal_direction(
    reference: RedBarV2Reference | None,
    context: MarketIndicatorSnapshot | None,
    *,
    previous_direction: str,
    bullish_threshold: float = 55.0,
    bearish_threshold: float = 45.0,
) -> RedBarV2DirectionDecision:
    """Detect an opposite-direction reversal from a completed 5-minute bar.

    This function reports directional state only. It never closes a trade and
    does not determine whether an opposite candidate may be admitted.
    """
    if not _valid_context(reference, context, "5M"):
        return _invalid_context_decision(reference, context)
    assert reference is not None and context is not None
    assert context.rsi_value is not None and context.vwap_value is not None

    prior = previous_direction.upper()
    if prior not in {"BULLISH", "BEARISH"}:
        raise ValueError("previous_direction must be BULLISH or BEARISH")

    bullish = (
        context.rsi_value > bullish_threshold
        and context.candle_close > context.vwap_value
    )
    bearish = (
        context.rsi_value < bearish_threshold
        and context.candle_close < context.vwap_value
    )

    if prior == "BEARISH" and bullish:
        midpoint_aligned = context.candle_close > reference.midpoint
        return RedBarV2DirectionDecision(
            event_type=RedBarV2EventType.BULLISH_REVERSAL_DETECTED,
            state=(
                RedBarV2State.CONFIRMED_BULLISH
                if midpoint_aligned
                else RedBarV2State.PROVISIONAL_BULLISH
            ),
            direction="BULLISH",
            option_side="CE",
            entry_type="REVERSAL",
            trend_strength="CONFIRMED" if midpoint_aligned else "PROVISIONAL",
            context_timestamp=context.candle_timestamp,
            reference_timestamp=reference.reference_timestamp,
            close_price=context.candle_close,
            rsi_value=context.rsi_value,
            vwap_value=context.vwap_value,
            rsi_aligned=True,
            vwap_aligned=True,
            midpoint_aligned=midpoint_aligned,
            context_fresh=True,
            reason=(
                "Bullish 5-minute RSI/VWAP reversal is detected with midpoint confirmation."
                if midpoint_aligned
                else "Bullish 5-minute RSI/VWAP reversal is detected before midpoint confirmation."
            ),
        )

    if prior == "BULLISH" and bearish:
        midpoint_aligned = context.candle_close < reference.midpoint
        return RedBarV2DirectionDecision(
            event_type=RedBarV2EventType.BEARISH_REVERSAL_DETECTED,
            state=(
                RedBarV2State.CONFIRMED_BEARISH
                if midpoint_aligned
                else RedBarV2State.PROVISIONAL_BEARISH
            ),
            direction="BEARISH",
            option_side="PE",
            entry_type="REVERSAL",
            trend_strength="CONFIRMED" if midpoint_aligned else "PROVISIONAL",
            context_timestamp=context.candle_timestamp,
            reference_timestamp=reference.reference_timestamp,
            close_price=context.candle_close,
            rsi_value=context.rsi_value,
            vwap_value=context.vwap_value,
            rsi_aligned=True,
            vwap_aligned=True,
            midpoint_aligned=midpoint_aligned,
            context_fresh=True,
            reason=(
                "Bearish 5-minute RSI/VWAP reversal is detected with midpoint confirmation."
                if midpoint_aligned
                else "Bearish 5-minute RSI/VWAP reversal is detected before midpoint confirmation."
            ),
        )

    return RedBarV2DirectionDecision(
        event_type=RedBarV2EventType.NO_DIRECTIONAL_ALIGNMENT,
        state=RedBarV2State.NEUTRAL,
        direction=None,
        option_side=None,
        entry_type=None,
        trend_strength=None,
        context_timestamp=context.candle_timestamp,
        reference_timestamp=reference.reference_timestamp,
        close_price=context.candle_close,
        rsi_value=context.rsi_value,
        vwap_value=context.vwap_value,
        rsi_aligned=False,
        vwap_aligned=False,
        midpoint_aligned=False,
        context_fresh=True,
        reason="The completed 5-minute candle does not confirm an opposite RSI/VWAP reversal.",
    )


def evaluate_midpoint_upgrade(
    reference: RedBarV2Reference | None,
    context: MarketIndicatorSnapshot | None,
    *,
    current_state: RedBarV2State,
) -> RedBarV2DirectionDecision:
    """Upgrade a provisional reversal state after midpoint alignment.

    The upgrade is a state event only and must not create a second trade.
    """
    if not _valid_context(reference, context, "1M"):
        return _invalid_context_decision(reference, context)
    assert reference is not None and context is not None

    if current_state == RedBarV2State.PROVISIONAL_BULLISH:
        aligned = context.candle_close > reference.midpoint
        direction = "BULLISH"
        option_side = "CE"
        confirmed_state = RedBarV2State.CONFIRMED_BULLISH
    elif current_state == RedBarV2State.PROVISIONAL_BEARISH:
        aligned = context.candle_close < reference.midpoint
        direction = "BEARISH"
        option_side = "PE"
        confirmed_state = RedBarV2State.CONFIRMED_BEARISH
    else:
        raise ValueError("current_state must be a provisional Red Bar V2 state")

    if aligned:
        return RedBarV2DirectionDecision(
            event_type=RedBarV2EventType.FULL_DIRECTIONAL_ALIGNMENT,
            state=confirmed_state,
            direction=direction,
            option_side=option_side,
            entry_type="STATE_UPGRADE",
            trend_strength="CONFIRMED",
            context_timestamp=context.candle_timestamp,
            reference_timestamp=reference.reference_timestamp,
            close_price=context.candle_close,
            rsi_value=context.rsi_value,
            vwap_value=context.vwap_value,
            rsi_aligned=context.bullish_context or context.bearish_context,
            vwap_aligned=context.price_vs_vwap in {"ABOVE", "BELOW"},
            midpoint_aligned=True,
            context_fresh=True,
            reason=f"The provisional {direction.lower()} state is now confirmed by the Red Bar midpoint.",
        )

    return RedBarV2DirectionDecision(
        event_type=RedBarV2EventType.NO_DIRECTIONAL_ALIGNMENT,
        state=current_state,
        direction=direction,
        option_side=option_side,
        entry_type="STATE_UPGRADE",
        trend_strength="PROVISIONAL",
        context_timestamp=context.candle_timestamp,
        reference_timestamp=reference.reference_timestamp,
        close_price=context.candle_close,
        rsi_value=context.rsi_value,
        vwap_value=context.vwap_value,
        rsi_aligned=context.bullish_context or context.bearish_context,
        vwap_aligned=context.price_vs_vwap in {"ABOVE", "BELOW"},
        midpoint_aligned=False,
        context_fresh=True,
        reason=f"The provisional {direction.lower()} state has not yet crossed the Red Bar midpoint.",
    )
