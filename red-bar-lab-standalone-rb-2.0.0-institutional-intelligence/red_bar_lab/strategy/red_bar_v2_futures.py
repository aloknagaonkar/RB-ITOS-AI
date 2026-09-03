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
    grade_against_reference,
    state_for_grade,
)
from red_bar_lab.strategy.red_bar_v2_working_reference import (
    RedBarV2WorkingReference,
    zone_position,
)


Reference = RedBarV2Reference | RedBarV2WorkingReference


def _invalid(
    reference: Reference | None,
    context: RedBarV2FuturesSnapshot | None,
) -> RedBarV2DirectionDecision:
    reason = "The governing reference is not ready."
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
        # The canonical gating flag defaults to True on the dataclass, so an
        # invalid-context decision that leaves it unset reports the RedBar +
        # VWAP check as *passing*. Say False out loud.
        redbar_vwap_aligned=False,
        context_fresh=bool(context and context.fresh),
        reason=reason,
    )


def _valid(
    reference: Reference | None,
    context: RedBarV2FuturesSnapshot | None,
    timeframe: str,
    *,
    require_vwap: bool = True,
) -> bool:
    """Is there enough evidence to evaluate a direction on this candle?

    RSI is deliberately absent: it is informational, and requiring it here
    kept the strategy blind for the whole Wilder RSI(14) warm-up.

    ``require_vwap`` is False on the working-reference path, which consults no
    VWAP at all. Demanding a value that path never reads would let a futures
    outage suppress a purely structural entry -- the same defect in a new
    costume.
    """
    return bool(
        reference is not None
        and context is not None
        and context.timeframe == timeframe
        and context.data_quality == "VALID"
        and context.fresh
        and (context.vwap_value is not None or not require_vwap)
        and context.trading_date == reference.trading_date
    )


def _rsi_aligned(
    context: RedBarV2FuturesSnapshot,
    bullish_threshold: float,
    bearish_threshold: float,
) -> bool:
    """Informational only: is RSI decisively off the midline either way?"""
    if context.rsi_value is None:
        return False
    return (
        context.rsi_value > bullish_threshold
        or context.rsi_value < bearish_threshold
    )


def _grade(*, bullish: bool, close: float, high: float, low: float) -> tuple[str, bool]:
    """Thin alias so both entry paths grade against one definition.

    The rule itself lives with the decision dataclass and the enums it feeds, in
    ``red_bar_v2``, because a grade that meant one thing here and another there
    would make ``trend_strength`` unreadable across the two modules.
    """
    return grade_against_reference(bullish=bullish, close=close, high=high, low=low)


def _states(bullish: bool, cleared: bool) -> RedBarV2State:
    return state_for_grade(bullish, cleared)


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
    assert context.vwap_value is not None

    # RSI is now informational; the gates are RedBar reference + VWAP
    # both pointing the same direction.
    bullish_vwap = context.vwap_comparison_price > context.vwap_value
    bearish_vwap = context.vwap_comparison_price < context.vwap_value
    bullish_midpoint = context.candle_close > reference.midpoint
    bearish_midpoint = context.candle_close < reference.midpoint
    bullish_redbar_vwap = bullish_vwap and bullish_midpoint
    bearish_redbar_vwap = bearish_vwap and bearish_midpoint
    rsi_aligned = _rsi_aligned(context, bullish_threshold, bearish_threshold)

    zone = zone_position(reference, context.candle_close).value

    if bullish_redbar_vwap:
        event = RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT
        direction, side = "BULLISH", "CE"
    elif bearish_redbar_vwap:
        event = RedBarV2EventType.INITIAL_BEARISH_ALIGNMENT
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
            pcr_value=context.pcr_value,
            morning_pcr_value=context.morning_pcr_value,
            redbar_vwap_aligned=bullish_redbar_vwap or bearish_redbar_vwap,
            rsi_aligned=rsi_aligned,
            vwap_aligned=bullish_vwap or bearish_vwap,
            midpoint_aligned=bullish_midpoint or bearish_midpoint,
            context_fresh=True,
            zone_position=zone,
            governing_reference="RED_BAR",
            reason=(
                "The completed 1-minute index/futures context is not fully "
                "aligned."
            ),
        )

    bullish = direction == "BULLISH"
    strength, cleared = _grade(
        bullish=bullish,
        close=context.candle_close,
        high=reference.reference_high,
        low=reference.reference_low,
    )
    distance = (
        context.candle_close - reference.midpoint
        if bullish
        else reference.midpoint - context.candle_close
    )

    return RedBarV2DirectionDecision(
        event_type=event,
        state=_states(bullish, cleared),
        direction=direction,
        option_side=side,
        entry_type="INITIAL",
        trend_strength=strength,
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
        zone_position=zone,
        governing_reference="RED_BAR",
        midpoint_distance_points=round(float(distance), 4),
        reason=(
            "Index and futures price/VWAP are fully aligned "
            f"for {direction.lower()} direction "
            f"({strength.lower()} by the reference candle's own range)."
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
    # Validate the caller's argument before the context early-return, or a
    # typo'd direction is silently swallowed on every invalid-context candle
    # and only surfaces once the data happens to be good.
    prior = previous_direction.upper()
    if prior not in {"BULLISH", "BEARISH"}:
        raise ValueError("previous_direction must be BULLISH or BEARISH")

    if not _valid(reference, context, "5M"):
        return _invalid(reference, context)
    assert reference is not None and context is not None
    assert context.vwap_value is not None

    # The reversal path runs under the red bar's own authority, so it applies
    # the red bar's own rule: the index close must clear the midpoint *and* the
    # futures must sit on the matching side of their VWAP. Taking direction from
    # the VWAP alone -- which this did -- could enter with price on the wrong
    # side of the midpoint, so the two entry paths disagreed about what the
    # reference means. RSI stays informational on both.
    bullish_vwap = context.vwap_comparison_price > context.vwap_value
    bearish_vwap = context.vwap_comparison_price < context.vwap_value
    bullish_midpoint = context.candle_close > reference.midpoint
    bearish_midpoint = context.candle_close < reference.midpoint
    bullish = bullish_vwap and bullish_midpoint
    bearish = bearish_vwap and bearish_midpoint
    rsi_aligned = _rsi_aligned(context, bullish_threshold, bearish_threshold)
    zone = zone_position(reference, context.candle_close).value

    if prior == "BEARISH" and bullish:
        direction, side = "BULLISH", "CE"
        event = RedBarV2EventType.BULLISH_REVERSAL_DETECTED
    elif prior == "BULLISH" and bearish:
        direction, side = "BEARISH", "PE"
        event = RedBarV2EventType.BEARISH_REVERSAL_DETECTED
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
            # rejection row -- and report the two halves of the gate as they
            # actually read, rather than flattening both to False. A bullish
            # VWAP with a bearish midpoint is now a rejection, and the audit
            # trail has to be able to say which half failed.
            rsi_aligned=rsi_aligned,
            vwap_aligned=bullish_vwap or bearish_vwap,
            midpoint_aligned=bullish_midpoint or bearish_midpoint,
            context_fresh=True,
            zone_position=zone,
            governing_reference="RED_BAR",
            reason="The completed 5-minute split-source context does not confirm an opposite reversal.",
        )

    bullish_entry = direction == "BULLISH"
    strength, cleared = _grade(
        bullish=bullish_entry,
        close=context.candle_close,
        high=reference.reference_high,
        low=reference.reference_low,
    )
    distance = (
        context.candle_close - reference.midpoint
        if bullish_entry
        else reference.midpoint - context.candle_close
    )

    return RedBarV2DirectionDecision(
        event_type=event,
        state=_states(bullish_entry, cleared),
        direction=direction,
        option_side=side,
        entry_type="REVERSAL",
        trend_strength=strength,
        context_timestamp=context.candle_timestamp,
        reference_timestamp=reference.reference_timestamp,
        close_price=context.candle_close,
        rsi_value=context.rsi_value,
        vwap_value=context.vwap_value,
        pcr_value=context.pcr_value,
        morning_pcr_value=context.morning_pcr_value,
        # Both halves of the gate passed to get here, so all three read True and
        # the grade lives in ``trend_strength``. Previously this path set
        # ``redbar_vwap_aligned`` to the midpoint *grade*, which made the same
        # field mean "gate passed" on the initial path and "already at +1R"
        # here.
        redbar_vwap_aligned=True,
        rsi_aligned=rsi_aligned,
        vwap_aligned=True,
        midpoint_aligned=True,
        context_fresh=True,
        zone_position=zone,
        governing_reference="RED_BAR",
        midpoint_distance_points=round(float(distance), 4),
        reason=(
            f"{direction.title()} reversal is confirmed by the index close "
            "against the frozen midpoint and the futures against their VWAP "
            f"({strength.lower()} by the reference candle's own range)."
        ),
    )


def evaluate_working_reference_direction_futures(
    working: RedBarV2WorkingReference | None,
    context: RedBarV2FuturesSnapshot | None,
    *,
    red_bar: RedBarV2Reference,
) -> RedBarV2DirectionDecision:
    """Structure-only entry against the deputy reference, outside the red bar band.

    No VWAP appears anywhere below, and that is the point. The session-cumulative
    futures VWAP is dragged away from price on a trend day -- roughly 205 points
    above it at a day's low -- so at the exact moment a turn is worth trading the
    gate is structurally unsatisfiable, and it only opens once a large part of the
    move is already gone. The deputy candle is instead minutes old and built out
    of the turn itself, so clearing its own extreme *is* the timing signal, and
    the 50%-body filter that admitted it already did the screening the VWAP would
    otherwise have done.

    The deputy also holds no authority inside the red bar's band or on the far
    side of it. When the close moves there this returns a no-direction row naming
    the red bar as governing, so the caller switches back to the full gate rather
    than trading a level that no longer applies.
    """
    if not _valid(working, context, "1M", require_vwap=False):
        return _invalid(working, context)
    assert working is not None and context is not None

    close = context.candle_close
    zone = zone_position(red_bar, close)
    bullish = working.direction == "BULLISH"

    def no_direction(reason: str, *, governing: str) -> RedBarV2DirectionDecision:
        return RedBarV2DirectionDecision(
            event_type=RedBarV2EventType.NO_DIRECTIONAL_ALIGNMENT,
            state=RedBarV2State.NEUTRAL,
            direction=None,
            option_side=None,
            entry_type=None,
            trend_strength=None,
            context_timestamp=context.candle_timestamp,
            reference_timestamp=working.reference_timestamp,
            close_price=close,
            rsi_value=context.rsi_value,
            vwap_value=context.vwap_value,
            pcr_value=context.pcr_value,
            morning_pcr_value=context.morning_pcr_value,
            # This path never reads the VWAP, so it cannot claim the RedBar +
            # VWAP gate passed. False is the honest reading of a check that was
            # not performed, and it keeps the flag from being taken as evidence.
            redbar_vwap_aligned=False,
            rsi_aligned=False,
            vwap_aligned=False,
            midpoint_aligned=False,
            context_fresh=True,
            zone_position=zone.value,
            governing_reference=governing,
            working_body_ratio=working.body_ratio,
            reason=reason,
        )

    if zone.value != working.zone_side:
        return no_direction(
            (
                "The close has left the side of the band the working reference "
                f"was born on ({working.zone_side} -> {zone.value}), so the "
                "frozen Red Bar reference governs again."
            ),
            governing="RED_BAR",
        )

    beyond_midpoint = (
        close > working.midpoint if bullish else close < working.midpoint
    )
    if not beyond_midpoint:
        return no_direction(
            (
                "The completed 1-minute close has not crossed the working "
                f"reference midpoint for {working.direction.lower()} direction."
            ),
            governing="WORKING",
        )

    strength, cleared = _grade(
        bullish=bullish,
        close=close,
        high=working.reference_high,
        low=working.reference_low,
    )
    distance = close - working.midpoint if bullish else working.midpoint - close
    event = (
        RedBarV2EventType.WORKING_BULLISH_BREAKOUT
        if bullish
        else RedBarV2EventType.WORKING_BEARISH_BREAKDOWN
    )

    extreme = "high" if bullish else "low"
    took_out = (
        f"is beyond the working reference {extreme}"
        if cleared
        else (
            "is beyond the working reference midpoint but has not taken out "
            f"its {extreme}"
        )
    )

    return RedBarV2DirectionDecision(
        event_type=event,
        state=_states(bullish, cleared),
        direction=working.direction,
        option_side="CE" if bullish else "PE",
        entry_type="WORKING",
        # PROVISIONAL rows are emitted rather than swallowed: the admission
        # policy is what refuses them, so the audit trail keeps a record of every
        # candle that crossed the deputy midpoint without taking out its extreme.
        trend_strength=strength,
        context_timestamp=context.candle_timestamp,
        reference_timestamp=working.reference_timestamp,
        close_price=close,
        rsi_value=context.rsi_value,
        vwap_value=context.vwap_value,
        pcr_value=context.pcr_value,
        morning_pcr_value=context.morning_pcr_value,
        redbar_vwap_aligned=False,
        rsi_aligned=False,
        vwap_aligned=False,
        midpoint_aligned=True,
        context_fresh=True,
        zone_position=zone.value,
        governing_reference="WORKING",
        midpoint_distance_points=round(float(distance), 4),
        working_body_ratio=working.body_ratio,
        reason=(
            f"The completed 1-minute close {took_out} "
            f"({strength.lower()}, {zone.value} the Red Bar band, "
            f"body ratio {working.body_ratio:.2f})."
        ),
    )


__all__ = [
    "evaluate_initial_direction_futures",
    "evaluate_reversal_direction_futures",
    "evaluate_working_reference_direction_futures",
    "evaluate_midpoint_upgrade",
]
