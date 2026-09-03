"""The working reference: a deputy level for the space outside the red bar.

Stage 1's red bar answers "where is the line?" once per session and then never
moves. That is what makes it trustworthy and also what makes it blind: after a
trade has run 500 points away from it, a level frozen hundreds of points
overhead cannot detect the counter-move, and the strategy sits flat through the
whole retracement.

The working reference fills that gap. When a trade closes, the first completed
5-minute candle of the *opposite* colour becomes a temporary reference --
Stage 1's own logic with the colour flipped -- and its high, low and midpoint
stand in for the red bar's while price is outside the red bar's own low-to-high
band.

Three rules constrain it -- the first keeps it subordinate to the red bar, the
other two decide whether a candle is allowed to become one at all:

* **Precedence by location.** The red bar is senior. The deputy governs only
  the side of the band it was born on, and a close back inside the band -- or
  out the far side -- discards it and returns control to the red bar. Only one
  reference is ever in force, so the system can never be long by one rule and
  short by another.
* **Body quality.** A candle qualifies only if its body is at least half its
  own high-to-low range. The first bounce off a low is usually a doji or a
  wick, and requiring real displacement is the cheapest available filter: the
  threshold is a ratio, so it is dimensionless and travels across instruments
  and volatility regimes without tuning.
* **Displacement against the recent range.** The candle must also close beyond
  the previous completed 5-minute candle's extreme -- above its high for a
  bullish deputy, below its low for a bearish one. The body ratio only says the
  candle was decisive about itself; a tall candle can still close inside the
  range it started in. This is the one entry path that runs with no futures VWAP
  gate behind it, so the candle that authorises it has to have taken something
  out.

A weak candle is skipped and waiting continues. If none ever qualifies there is
no working reference and no entry, which is the fail-closed direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import pandas as pd

from red_bar_lab.intelligence.market_context import (
    aggregate_completed_5m,
    completed_candles,
)
from red_bar_lab.strategy.red_bar_v2 import RedBarV2Reference

MINIMUM_BODY_RATIO = 0.5


class ZonePosition(str, Enum):
    """Where a price sits relative to the red bar's own low-to-high band."""

    ABOVE = "ABOVE"
    INSIDE = "INSIDE"
    BELOW = "BELOW"


@dataclass(frozen=True)
class RedBarV2WorkingReference:
    """A temporary reference built from one completed opposite-colour candle.

    `zone_side` records which side of the red bar's band the candle closed on.
    The deputy is only ever in force on that side, so the field is what makes
    the hand-back rule a single comparison rather than a state machine.
    """

    instrument_key: str
    trading_date: str
    reference_timestamp: datetime
    reference_open: float
    reference_high: float
    reference_low: float
    reference_close: float
    midpoint: float
    direction: str
    body_ratio: float
    zone_side: str
    interval_minutes: int = 5
    level_type: str = "WORKING_OPPOSITE_CANDLE"
    strategy_version: str = "RED_BAR_V2"


def body_ratio(open_price: float, high: float, low: float, close: float) -> float:
    """Body as a fraction of the candle's own range; 0.0 when the range is zero.

    A zero-range candle has no displacement to measure, so it can never
    qualify. Returning 0.0 rather than raising keeps the caller's filter a
    single comparison.
    """
    candle_range = float(high) - float(low)
    if candle_range <= 0.0:
        return 0.0
    return abs(float(close) - float(open_price)) / candle_range


def zone_position(reference: RedBarV2Reference, price: float) -> ZonePosition:
    """Locate a price against the red bar's band, edges inclusive.

    The edges belong to the zone. A close exactly on the reference high or low
    hands control back to the red bar, which is the conservative reading: the
    senior reference decides whenever there is any doubt about which side of its
    own range price is on.
    """
    if price > reference.reference_high:
        return ZonePosition.ABOVE
    if price < reference.reference_low:
        return ZonePosition.BELOW
    return ZonePosition.INSIDE


def select_governing_reference(
    red_bar: RedBarV2Reference,
    working: RedBarV2WorkingReference | None,
    close: float,
) -> tuple[RedBarV2Reference | RedBarV2WorkingReference, str]:
    """Return the reference in force for this close, and its name.

    The red bar wins inside its own band, on the far side of that band, and
    whenever no deputy exists. That is the whole of "precedence by location":
    no latch, no timer, no hysteresis, so the answer depends only on the
    current close and is recomputed from scratch on every candle.
    """
    if working is None:
        return red_bar, "RED_BAR"
    if zone_position(red_bar, close).value != working.zone_side:
        return red_bar, "RED_BAR"
    return working, "WORKING"


def build_working_reference(
    candles: pd.DataFrame,
    *,
    instrument_key: str,
    evaluation_time: datetime | pd.Timestamp,
    red_bar: RedBarV2Reference,
    after: datetime | pd.Timestamp,
    required_direction: str,
    minimum_body_ratio: float = MINIMUM_BODY_RATIO,
) -> RedBarV2WorkingReference | None:
    """First completed 5-minute candle after `after` that can act as a deputy.

    `required_direction` is the direction the deputy would trade: BULLISH looks
    for a green candle, BEARISH for a red one. Only candles closing outside the
    red bar's band are considered -- inside it the red bar is already in charge,
    so a deputy there would have nothing to govern.

    Three tests, in order of increasing cost: the candle must close outside the
    band, its body must be at least `minimum_body_ratio` of its own range, and
    its close must be beyond the *immediately preceding* completed 5-minute
    candle's extreme. That last comparison is taken from the unfiltered frame,
    not from the colour-filtered candidates: the point is to have cleared
    whatever the market last did, and against the previous same-colour candle it
    would be a far weaker claim. A candle with nothing before it in the frame is
    skipped, because there is nothing it can have broken out of.

    `after` is normally the moment the previous trade closed. The comparison is
    strict, so the candle a trade exited on cannot immediately become the
    reference for re-entering it.
    """
    wanted = required_direction.upper()
    if wanted not in {"BULLISH", "BEARISH"}:
        raise ValueError("required_direction must be BULLISH or BEARISH")

    completed_1m = completed_candles(
        candles, evaluation_time=evaluation_time, interval_minutes=1
    )
    if completed_1m.empty:
        return None
    bars = aggregate_completed_5m(completed_1m)
    if bars.empty:
        return None

    green = bars["close"] > bars["open"]
    colour = green if wanted == "BULLISH" else bars["close"] < bars["open"]
    eligible = bars[(bars.index > pd.Timestamp(after)) & colour]
    # Position in the *unfiltered* frame, so the breakout test below can reach
    # the candle that actually preceded a candidate rather than the previous
    # candidate. `eligible` has both a timestamp and a colour filter applied, so
    # its own neighbour is the previous same-colour candle -- a green candle
    # closing above the last green candle's high proves much less than one
    # closing above the high of the red candle that just printed.
    offsets = {stamp: offset for offset, stamp in enumerate(bars.index)}

    for timestamp, row in eligible.iterrows():
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        side = zone_position(red_bar, close)
        if side is ZonePosition.INSIDE:
            continue
        ratio = body_ratio(open_price, high, low, close)
        if ratio < minimum_body_ratio:
            continue
        offset = offsets[timestamp]
        if offset == 0:
            # Nothing precedes it, so there is no range it can be shown to have
            # taken out. Skipping is the fail-closed reading.
            continue
        previous = bars.iloc[offset - 1]
        broke_out = (
            close > float(previous["high"])
            if wanted == "BULLISH"
            else close < float(previous["low"])
        )
        if not broke_out:
            continue
        stamp = pd.Timestamp(timestamp)
        return RedBarV2WorkingReference(
            instrument_key=instrument_key,
            trading_date=stamp.date().isoformat(),
            reference_timestamp=stamp.to_pydatetime(),
            reference_open=open_price,
            reference_high=high,
            reference_low=low,
            reference_close=close,
            midpoint=(high + low) / 2.0,
            direction=wanted,
            body_ratio=ratio,
            zone_side=side.value,
        )
    return None


def structure_failed(
    midpoint: float,
    *,
    direction: str,
    close: float,
) -> bool:
    """Has a completed close broken back through the level the trade was taken on?

    `midpoint` is the governing reference's own midpoint -- pass
    ``select_governing_reference(...)[0].midpoint``. It is taken as a number
    rather than as a reference object so that a caller holding only the level,
    such as the decision log reading it back out of a replay row, does not have
    to fabricate a reference to ask the question.

    A long is broken by a close below the level, a short by a close above it, and
    a close exactly on it is not a break -- the same strict comparison the entry
    gate uses, so a price that cannot open a position cannot close one either.

    No VWAP appears here on purpose. Entries need the close *and* the futures
    against their VWAP; exits need only the close. Reducing exposure must never be
    harder than adding it, so a stale or missing futures feed cannot trap a
    position whose reason for existing has already gone.
    """
    wanted = direction.upper()
    if wanted not in {"BULLISH", "BEARISH"}:
        raise ValueError("direction must be BULLISH or BEARISH")
    if wanted == "BULLISH":
        return close < midpoint
    return close > midpoint


__all__ = [
    "MINIMUM_BODY_RATIO",
    "RedBarV2WorkingReference",
    "ZonePosition",
    "body_ratio",
    "build_working_reference",
    "select_governing_reference",
    "structure_failed",
    "zone_position",
]
