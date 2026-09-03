from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time
from enum import Enum

import pandas as pd

from red_bar_lab.intelligence.market_context import (
    MarketContextError,
    MarketIndicatorSnapshot,
    aggregate_completed_5m,
    completed_candles,
    session_vwap,
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
    # The working reference's own signals. Named for what price did rather than
    # for "alignment", because this path consults no VWAP: clearing the deputy
    # candle's extreme is the entire trigger.
    WORKING_BULLISH_BREAKOUT = "WORKING_BULLISH_BREAKOUT"
    WORKING_BEARISH_BREAKDOWN = "WORKING_BEARISH_BREAKDOWN"
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
    # Where the futures price sat against the futures VWAP at the moment the
    # red bar completed. INFORMATIONAL ONLY -- no gate reads these fields, and
    # `build_red_bar_v2_reference` never sets them, so reference detection can
    # never be blocked by a missing or unhealthy futures feed. They are filled
    # in afterwards by `annotate_reference_vwap_position`.
    reference_vwap_value: float | None = None
    reference_vwap_comparison_price: float | None = None
    reference_vwap_position: str | None = None
    reference_vwap_timestamp: datetime | None = None


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
    reason: str
    # Re-entry validation (only set when the system is waiting for a
    # re-entry validation). State values: "waiting_midpoint" |
    # "waiting_vwap" | "validating" | "validated" | "failed".
    # alignment_passed=True means the next-candle VWAP check confirmed the
    # touch direction.
    reentry_state: str | None = None
    reentry_alignment_passed: bool = False
    # PCR (informational, do not gate admission)
    pcr_value: float | None = None            # current 5m candle overall PCR
    morning_pcr_value: float | None = None     # morning fixed-level PCR (None before ~9:20)
    # Combined RedBar + VWAP alignment (gating; replaces midpoint_aligned
    # as the canonical "RedBar reference check" in the UI)
    redbar_vwap_aligned: bool = True           # both aligned in same direction
    # Legacy fields (kept for backward compat; RedBar reference alignment
    # is now the "redbar_vwap_aligned" flag, but "midpoint_aligned" still
    # holds the underlying midpoint-touch result for diagnostics)
    rsi_aligned: bool = True                   # informational
    vwap_aligned: bool = True                 # gating (combined with RedBar)
    midpoint_aligned: bool = True             # gating
    context_fresh: bool = True                # gating
    # Stage 3 geometry. None of these gate on their own -- they record *where*
    # the decision was taken so a day can be measured after the fact, which the
    # audit trail previously could not reconstruct from the boolean flags alone.
    zone_position: str | None = None          # ABOVE | INSIDE | BELOW the red bar band
    governing_reference: str | None = None    # RED_BAR | WORKING
    midpoint_distance_points: float | None = None  # signed, in the trade's favour
    working_body_ratio: float | None = None   # set only for working-reference entries
    rsi_value: float | None = None            # 14-period RSI of the underlying close
    vwap_value: float | None = None           # 5m VWAP of the futures contract


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


def annotate_reference_vwap_position(
    reference: RedBarV2Reference,
    futures_candles: pd.DataFrame,
) -> RedBarV2Reference:
    """Record where futures price sat against futures VWAP at the red bar close.

    INFORMATIONAL ONLY. Nothing gates on the result: it exists so the audit
    trail can show whether the reference formed with or against the day's
    volume-weighted mean. When the futures data cannot support a reading the
    reference is returned unchanged, with the fields left as ``None`` -- a
    missing futures feed must never suppress a reference that the index alone
    already established.

    The VWAP is taken as of the red bar's own close rather than the current
    candle, so the annotation describes the reference bar and not whenever the
    caller happened to ask. `completed_candles` supplies the anti-lookahead
    cut, so no candle after the red bar can leak in.
    """
    if futures_candles is None or futures_candles.empty:
        return reference

    reference_close_time = pd.Timestamp(reference.reference_timestamp) + pd.Timedelta(
        minutes=reference.interval_minutes
    )
    try:
        completed = completed_candles(
            futures_candles,
            evaluation_time=reference_close_time,
            interval_minutes=1,
        )
    except MarketContextError:
        return reference
    if completed.empty:
        return reference

    vwap_raw = session_vwap(completed).iloc[-1]
    if pd.isna(vwap_raw):
        return reference

    vwap_value = float(vwap_raw)
    comparison_price = float(completed["close"].iloc[-1])
    if comparison_price > vwap_value:
        position = "ABOVE"
    elif comparison_price < vwap_value:
        position = "BELOW"
    else:
        position = "AT"

    return replace(
        reference,
        reference_vwap_value=vwap_value,
        reference_vwap_comparison_price=comparison_price,
        reference_vwap_position=position,
        reference_vwap_timestamp=pd.Timestamp(completed.index[-1]).to_pydatetime(),
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
        pcr_value=(
            getattr(context, "pcr_value", None) if context else None
        ),
        morning_pcr_value=(
            getattr(context, "morning_pcr_value", None) if context else None
        ),
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


def _valid_context(
    reference: RedBarV2Reference | None,
    context: MarketIndicatorSnapshot | None,
    timeframe: str,
) -> bool:
    """Is there enough evidence to evaluate on this candle?

    RSI is deliberately absent. It is informational under these rules, and
    requiring a reading here kept every evaluator on this path blind for the
    whole Wilder RSI(14) warm-up -- 15 candles of each session in which nothing
    was evaluated at all.
    """
    return bool(
        reference is not None
        and context is not None
        and context.timeframe == timeframe
        and context.data_quality == "VALID"
        and context.fresh
        and context.vwap_value is not None
        and context.trading_date == reference.trading_date
    )


def _rsi_aligned(
    context: MarketIndicatorSnapshot,
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


def grade_against_reference(
    *, bullish: bool, close: float, high: float, low: float
) -> tuple[str, bool]:
    """CONFIRMED once the close clears the reference candle's own extreme.

    Crossing the midpoint says a setup exists. Clearing the high (long) or the
    low (short) says price has taken out the whole candle -- and since the
    initial stop is measured from that same extreme, CONFIRMED lands at roughly
    +1R. The grade is therefore a fact about price rather than a label the code
    assigns itself.

    Both entry paths import this rather than each judging for themselves, so
    "CONFIRMED" cannot come to mean two different things in two modules. Exactly
    on the extreme is not through it: the strict comparison keeps ties
    fail-closed, matching how the midpoint gate already treats them.
    """
    cleared = close > high if bullish else close < low
    return ("CONFIRMED" if cleared else "PROVISIONAL"), cleared


def state_for_grade(bullish: bool, cleared: bool) -> RedBarV2State:
    """The directional state that goes with a grade."""
    if bullish:
        return (
            RedBarV2State.CONFIRMED_BULLISH
            if cleared
            else RedBarV2State.PROVISIONAL_BULLISH
        )
    return (
        RedBarV2State.CONFIRMED_BEARISH
        if cleared
        else RedBarV2State.PROVISIONAL_BEARISH
    )


def evaluate_initial_direction(
    reference: RedBarV2Reference | None,
    context: MarketIndicatorSnapshot | None,
    *,
    bullish_threshold: float = 55.0,
    bearish_threshold: float = 45.0,
) -> RedBarV2DirectionDecision:
    """Evaluate the initial Red Bar V2 direction from a completed 1-minute bar.

    The gates are the red bar's midpoint and VWAP, both on the same side. RSI is
    reported and never consulted. The grade comes from the reference candle's own
    extreme, so an entry that cleared the midpoint but stopped inside the candle
    is admitted as PROVISIONAL rather than mislabelled CONFIRMED.
    """
    if not _valid_context(reference, context, "1M"):
        return _invalid_context_decision(reference, context)
    assert reference is not None and context is not None
    assert context.vwap_value is not None

    bullish_vwap = context.candle_close > context.vwap_value
    bearish_vwap = context.candle_close < context.vwap_value
    bullish_midpoint = context.candle_close > reference.midpoint
    bearish_midpoint = context.candle_close < reference.midpoint
    rsi_aligned = _rsi_aligned(context, bullish_threshold, bearish_threshold)

    bullish = bullish_vwap and bullish_midpoint
    bearish = bearish_vwap and bearish_midpoint

    if bullish or bearish:
        strength, cleared = grade_against_reference(
            bullish=bullish,
            close=context.candle_close,
            high=reference.reference_high,
            low=reference.reference_low,
        )
        extreme = "high" if bullish else "low"
        return RedBarV2DirectionDecision(
            event_type=(
                RedBarV2EventType.INITIAL_BULLISH_ALIGNMENT
                if bullish
                else RedBarV2EventType.INITIAL_BEARISH_ALIGNMENT
            ),
            state=state_for_grade(bullish, cleared),
            direction="BULLISH" if bullish else "BEARISH",
            option_side="CE" if bullish else "PE",
            entry_type="INITIAL",
            trend_strength=strength,
            context_timestamp=context.candle_timestamp,
            reference_timestamp=reference.reference_timestamp,
            close_price=context.candle_close,
            rsi_value=context.rsi_value,
            vwap_value=context.vwap_value,
            rsi_aligned=rsi_aligned,
            vwap_aligned=True,
            midpoint_aligned=True,
            context_fresh=True,
            reason=(
                f"The completed 1-minute candle is "
                f"{'above' if bullish else 'below'} the midpoint and VWAP "
                f"({strength.lower()} by the reference candle's {extreme})."
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
        rsi_aligned=rsi_aligned,
        vwap_aligned=bullish_vwap or bearish_vwap,
        midpoint_aligned=bullish_midpoint or bearish_midpoint,
        context_fresh=True,
        reason="The completed 1-minute candle does not have both VWAP and midpoint alignment.",
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

    A reversal runs under the red bar's own authority, so it applies the red
    bar's own rule: the close must clear the frozen midpoint *and* sit on the
    matching side of VWAP. Taking direction from VWAP alone -- which this did,
    with the midpoint downgraded to a grade -- could report a bullish reversal
    with price below the very level the strategy is named for, and the admission
    policy would then refuse it. The grade comes from the reference candle's own
    extreme instead, which is what CONFIRMED means everywhere else. RSI is
    reported and never consulted.
    """
    # Validate the caller's argument before the context early-return, or a
    # typo'd direction is silently swallowed on every invalid-context candle
    # and only surfaces once the data happens to be good.
    prior = previous_direction.upper()
    if prior not in {"BULLISH", "BEARISH"}:
        raise ValueError("previous_direction must be BULLISH or BEARISH")

    if not _valid_context(reference, context, "5M"):
        return _invalid_context_decision(reference, context)
    assert reference is not None and context is not None
    assert context.vwap_value is not None

    bullish_vwap = context.candle_close > context.vwap_value
    bearish_vwap = context.candle_close < context.vwap_value
    bullish_midpoint = context.candle_close > reference.midpoint
    bearish_midpoint = context.candle_close < reference.midpoint
    bullish = bullish_vwap and bullish_midpoint
    bearish = bearish_vwap and bearish_midpoint
    rsi_aligned = _rsi_aligned(context, bullish_threshold, bearish_threshold)

    if (prior == "BEARISH" and bullish) or (prior == "BULLISH" and bearish):
        strength, cleared = grade_against_reference(
            bullish=bullish,
            close=context.candle_close,
            high=reference.reference_high,
            low=reference.reference_low,
        )
        extreme = "high" if bullish else "low"
        return RedBarV2DirectionDecision(
            event_type=(
                RedBarV2EventType.BULLISH_REVERSAL_DETECTED
                if bullish
                else RedBarV2EventType.BEARISH_REVERSAL_DETECTED
            ),
            state=state_for_grade(bullish, cleared),
            direction="BULLISH" if bullish else "BEARISH",
            option_side="CE" if bullish else "PE",
            entry_type="REVERSAL",
            trend_strength=strength,
            context_timestamp=context.candle_timestamp,
            reference_timestamp=reference.reference_timestamp,
            close_price=context.candle_close,
            rsi_value=context.rsi_value,
            vwap_value=context.vwap_value,
            rsi_aligned=rsi_aligned,
            # Both gates passed to get here, so their flags say so and the grade
            # lives in ``trend_strength`` alone. RSI reports itself and nothing
            # turns on it.
            vwap_aligned=True,
            midpoint_aligned=True,
            context_fresh=True,
            reason=(
                f"{'Bullish' if bullish else 'Bearish'} 5-minute reversal clears "
                f"the frozen midpoint and VWAP ({strength.lower()} by the "
                f"reference candle's {extreme})."
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
        # Report each gate as it actually reads. Flattening them all to False was
        # survivable while VWAP alone decided direction; now that a bullish VWAP
        # with a bearish midpoint lands here, the audit trail has to be able to
        # say which one failed.
        rsi_aligned=rsi_aligned,
        vwap_aligned=bullish_vwap or bearish_vwap,
        midpoint_aligned=bullish_midpoint or bearish_midpoint,
        context_fresh=True,
        reason=(
            "The completed 5-minute candle does not clear the frozen midpoint and "
            "VWAP together for an opposite reversal."
        ),
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
    # This evaluator reads no RSI threshold, so it must not inherit the RSI
    # warm-up blackout: a provisional state has to be upgradable the moment
    # the close clears the midpoint.
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

    # PCR + morning PCR (informational; defaults to None if not set)
    pcr_value = getattr(context, "pcr_value", None)
    morning_pcr_value = getattr(context, "morning_pcr_value", None)

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
            pcr_value=pcr_value,
            morning_pcr_value=morning_pcr_value,
            redbar_vwap_aligned=aligned,
            rsi_aligned=context.rsi_state in {"BULLISH", "BEARISH"},
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
        pcr_value=pcr_value,
        morning_pcr_value=morning_pcr_value,
        redbar_vwap_aligned=False,
        rsi_aligned=context.rsi_state in {"BULLISH", "BEARISH"},
        vwap_aligned=context.price_vs_vwap in {"ABOVE", "BELOW"},
        midpoint_aligned=False,
        context_fresh=True,
        reason=f"The provisional {direction.lower()} state has not yet crossed the Red Bar midpoint.",
    )
