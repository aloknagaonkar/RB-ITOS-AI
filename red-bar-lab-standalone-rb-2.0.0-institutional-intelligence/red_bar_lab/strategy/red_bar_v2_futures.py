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

    # RSI is now informational; the gates are RedBar reference + VWAP
    # both pointing the same direction.
    bullish_vwap = context.vwap_comparison_price > context.vwap_value
    bearish_vwap = context.vwap_comparison_price < context.vwap_value
    bullish_midpoint = context.candle_close > reference.midpoint
    bearish_midpoint = context.candle_close < reference.midpoint
    bullish_redbar_vwap = bullish_vwap and bullish_midpoint
    bearish_redbar_vwap = bearish_vwap and bearish_midpoint
    rsi_aligned = context.rsi_value > bullish_threshold or context.rsi_value < bearish_threshold

    # Mid-session 12:45 - 1:15 rule. Only active if the 12:45-1:15
    # 30-min candle has completed. Evaluates the 12:50 5-min close
    # (the close of the 12:45-12:50 candle) against the day's
    # reference midpoint. Outside the window, the rule is inactive.
    mid_session_active = _is_mid_session_window(context.candle_timestamp)
    mid_session_passed: bool | None = None
    mid_session_reason: str | None = None
    if mid_session_active:
        mid_session_passed, mid_session_reason = _evaluate_mid_session(
            context.candle_timestamp, reference.midpoint, context.candle_close
        )

    if bullish_redbar_vwap and (mid_session_passed is not False):
        event = RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT
        state = RedBarV2State.CONFIRMED_BULLISH
        direction, side = "BULLISH", "CE"
    elif bearish_redbar_vwap and (mid_session_passed is not False):
        event = RedBarV2EventType.INITIAL_BEARISH_ALIGNMENT
        state = RedBarV2State.CONFIRMED_BEARISH
        direction, side = "BEARISH", "PE"
    else:
        reason_parts = [
            "The completed 1-minute index/futures context is not fully aligned."
        ]
        if mid_session_passed is False:
            reason_parts.append(f"Mid-session 12:45 rule blocked: {mid_session_reason}")
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
            pcr_value=context.pcr_value,
            morning_pcr_value=context.morning_pcr_value,
            redbar_vwap_aligned=bullish_redbar_vwap or bearish_redbar_vwap,
            rsi_aligned=rsi_aligned,
            vwap_aligned=bullish_vwap or bearish_vwap,
            midpoint_aligned=bullish_midpoint or bearish_midpoint,
            context_fresh=True,
            mid_session_active=mid_session_active,
            mid_session_passed=mid_session_passed,
            mid_session_reason=mid_session_reason,
            reason=" ".join(reason_parts),
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
        pcr_value=context.pcr_value,
        morning_pcr_value=context.morning_pcr_value,
        redbar_vwap_aligned=True,
        rsi_aligned=rsi_aligned,
        vwap_aligned=True,
        midpoint_aligned=True,
        context_fresh=True,
        mid_session_active=mid_session_active,
        mid_session_passed=mid_session_passed,
        mid_session_reason=mid_session_reason,
        reason=(
            "Index and futures price/VWAP are fully aligned "
            f"for {direction.lower()} direction."
            + (
                f" Mid-session 12:45 confirmed: {mid_session_reason}."
                if mid_session_passed
                else ""
            )
        ),
    )


def _is_mid_session_window(candle_timestamp) -> bool:
    """True if the 5m candle is between 12:45 PM and 1:15 PM IST."""
    from datetime import time
    if candle_timestamp is None:
        return False
    ts = candle_timestamp
    if hasattr(ts, "time"):
        t = ts.time()
    else:
        return False
    return time(12, 45) <= t <= time(13, 15)


def _evaluate_mid_session(candle_timestamp, midpoint: float, candle_close: float):
    """Check the 12:50 5m candle close against the day's midpoint.

    When the 5m candle timestamp is 12:50, the close is the close of
    the 12:45-12:50 5-min window, which is also the first 5-min bar
    of the 12:45-13:15 30-min candle.
    """
    from datetime import time
    if candle_timestamp is None:
        return None, None
    if hasattr(candle_timestamp, "time"):
        t = candle_timestamp.time()
    else:
        return None, None
    if not (time(12, 50) <= t <= time(13, 15)):
        # Outside the 12:50-1:15 window inside the 12:45-1:15 active zone;
        # the rule is implicitly passed (no check).
        return True, None
    if t > time(12, 50):
        # The 12:50 close is fixed at 12:50. Subsequent 5m candles
        # within the window don't re-check the 12:50 close.
        # We mark the rule as passed.
        return True, "12:50 close preserved as confirmed by subsequent candles"
    if candle_close > midpoint:
        return True, "12:50 close above midpoint (BULLISH confirmed)"
    if candle_close < midpoint:
        return True, "12:50 close below midpoint (BEARISH confirmed)"
    return False, "12:50 close matched midpoint exactly (no direction)"


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

    # Reversal gates are now RedBar + VWAP combined (RSI informational).
    bullish = (
        context.vwap_comparison_price > context.vwap_value
    )
    bearish = (
        context.vwap_comparison_price < context.vwap_value
    )
    rsi_aligned = context.rsi_value > bullish_threshold or context.rsi_value < bearish_threshold

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
            pcr_value=context.pcr_value,
            morning_pcr_value=context.morning_pcr_value,
            redbar_vwap_aligned=False,
            # RSI is informational, so report the real reading even on the
            # rejection row. The gating flags below stay False because no
            # opposite reversal was confirmed.
            rsi_aligned=rsi_aligned,
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
        pcr_value=context.pcr_value,
        morning_pcr_value=context.morning_pcr_value,
        redbar_vwap_aligned=aligned,
        rsi_aligned=rsi_aligned,
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
