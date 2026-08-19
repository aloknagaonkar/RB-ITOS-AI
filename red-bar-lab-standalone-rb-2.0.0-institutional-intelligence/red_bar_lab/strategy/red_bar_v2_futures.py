from __future__ import annotations

from red_bar_lab.intelligence.red_bar_v2_futures_context import (
    RedBarV2FuturesSnapshot,
)
from red_bar_lab.strategy.red_bar_v2 import (
    RedBarV2DirectionDecision,
    RedBarV2EventType,
    RedBarV2Reference,
    RedBarV2State,
    evaluate_midpoint_upgrade,
)


def _invalid(
    reference: RedBarV2Reference | None,
    context: RedBarV2FuturesSnapshot | None,
) -> RedBarV2DirectionDecision:
    reason = "The NEXT_RED_CANDLE reference is not ready."
    state = RedBarV2State.REFERENCE_NOT_READY
    if reference is not None:
        state = RedBarV2State.NEUTRAL
        reason = (
            "Market context is unavailable."
            if context is None
            else f"Market context is not valid: {context.data_quality}."
        )
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


def _valid(
    reference: RedBarV2Reference | None,
    context: RedBarV2FuturesSnapshot | None,
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


def evaluate_initial_direction_futures(
    reference: RedBarV2Reference | None,
    context: RedBarV2FuturesSnapshot | None,
    *,
    bullish_threshold: float = 55.0,
    bearish_threshold: float = 45.0,
) -> RedBarV2DirectionDecision:
    if not _valid(reference, context, "1M"):
        return _invalid(reference, context)
    assert reference is not None and context is not None
    assert context.rsi_value is not None and context.vwap_value is not None

    bullish_rsi = context.rsi_value > bullish_threshold
    bearish_rsi = context.rsi_value < bearish_threshold
    bullish_vwap = context.vwap_comparison_price > context.vwap_value
    bearish_vwap = context.vwap_comparison_price < context.vwap_value
    bullish_midpoint = context.candle_close > reference.midpoint
    bearish_midpoint = context.candle_close < reference.midpoint

    if bullish_rsi and bullish_vwap and bullish_midpoint:
        event = RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT
        state = RedBarV2State.CONFIRMED_BULLISH
        direction, side = "BULLISH", "CE"
    elif bearish_rsi and bearish_vwap and bearish_midpoint:
        event = RedBarV2EventType.INITIAL_BEARISH_ALIGNMENT
        state = RedBarV2State.CONFIRMED_BEARISH
        direction, side = "BEARISH", "PE"
    else:
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
            reason="The completed 1-minute index/futures context is not fully aligned.",
        )

    return RedBarV2DirectionDecision(
        event_type=event,
        state=state,
        direction=direction,
        option_side=side,
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
        reason=(
            "Index RSI/midpoint and futures price/VWAP are fully aligned "
            f"for {direction.lower()} direction."
        ),
    )


def evaluate_reversal_direction_futures(
    reference: RedBarV2Reference | None,
    context: RedBarV2FuturesSnapshot | None,
    *,
    previous_direction: str,
    bullish_threshold: float = 55.0,
    bearish_threshold: float = 45.0,
) -> RedBarV2DirectionDecision:
    if not _valid(reference, context, "5M"):
        return _invalid(reference, context)
    assert reference is not None and context is not None
    assert context.rsi_value is not None and context.vwap_value is not None

    prior = previous_direction.upper()
    if prior not in {"BULLISH", "BEARISH"}:
        raise ValueError("previous_direction must be BULLISH or BEARISH")

    bullish = (
        context.rsi_value > bullish_threshold
        and context.vwap_comparison_price > context.vwap_value
    )
    bearish = (
        context.rsi_value < bearish_threshold
        and context.vwap_comparison_price < context.vwap_value
    )

    if prior == "BEARISH" and bullish:
        direction, side = "BULLISH", "CE"
        aligned = context.candle_close > reference.midpoint
        event = RedBarV2EventType.BULLISH_REVERSAL_DETECTED
        confirmed = RedBarV2State.CONFIRMED_BULLISH
        provisional = RedBarV2State.PROVISIONAL_BULLISH
    elif prior == "BULLISH" and bearish:
        direction, side = "BEARISH", "PE"
        aligned = context.candle_close < reference.midpoint
        event = RedBarV2EventType.BEARISH_REVERSAL_DETECTED
        confirmed = RedBarV2State.CONFIRMED_BEARISH
        provisional = RedBarV2State.PROVISIONAL_BEARISH
    else:
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
            reason="The completed 5-minute split-source context does not confirm an opposite reversal.",
        )

    return RedBarV2DirectionDecision(
        event_type=event,
        state=confirmed if aligned else provisional,
        direction=direction,
        option_side=side,
        entry_type="REVERSAL",
        trend_strength="CONFIRMED" if aligned else "PROVISIONAL",
        context_timestamp=context.candle_timestamp,
        reference_timestamp=reference.reference_timestamp,
        close_price=context.candle_close,
        rsi_value=context.rsi_value,
        vwap_value=context.vwap_value,
        rsi_aligned=True,
        vwap_aligned=True,
        midpoint_aligned=aligned,
        context_fresh=True,
        reason=(
            f"{direction.title()} futures VWAP reversal is detected "
            + ("with" if aligned else "before")
            + " index midpoint confirmation."
        ),
    )


__all__ = [
    "evaluate_initial_direction_futures",
    "evaluate_reversal_direction_futures",
    "evaluate_midpoint_upgrade",
]
