"""Risk plan for a Red Bar V2 entry: where the stop sits, and what follows.

A `RiskPlan` is built *before* the position is opened and is immutable
afterwards. That ordering matters: the stop defines `risk_points`, which is the
denominator of every R-multiple, so a trade whose stop is decided after entry
cannot be compared against any other trade.

The initial stop comes from the completed 5-minute candle that crossed one of
the two Red Bar V2 reference levels:

* the midpoint of the red reference bar, crossed by the *index*, or
* the session VWAP of the index future, crossed by the *future*.

Whichever crossing happened, the stop is always read off the **index** candle
for that 5-minute slot. The two levels live on different instruments roughly
130-150 index points apart, and that basis is not stable intraday, so mixing
them on one price axis would put the stop somewhere the index never traded.

There is no fixed profit target by default. A 2R target combined with a trail
that activates at 1R confines the trail to the 1R-to-2R window, where the target
always fires first -- so the trail can never do the thing it exists for, and a
single sustained trend gets chopped into a dozen small round trips. Pass an
explicit ``reward_multiple`` to reinstate a target for a specific study.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time

from .enums import Direction
from .exceptions import DomainValidationError

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python 3.10 compatibility
    from enum import Enum

    class StrEnum(str, Enum):
        """Compatibility implementation for Python 3.10."""


DEFAULT_REWARD_MULTIPLE: float | None = None
DEFAULT_MINIMUM_RISK_POINTS = 8.0
DEFAULT_MAXIMUM_RISK_POINTS = 60.0
DEFAULT_TRAIL_ACTIVATION_R = 1.0
DEFAULT_SESSION_FLAT_TIME = time(15, 15)
DEFAULT_QUANTITY_LOTS = 1

class StopTrigger(StrEnum):
    """Which reference level the 5-minute candle crossed."""

    MIDPOINT_CROSS = "MIDPOINT_CROSS"
    FUTURES_VWAP_CROSS = "FUTURES_VWAP_CROSS"
    # No completed 5-minute candle crossed either level, so the stop comes from
    # the one-minute candle that fired the entry. Named separately because the
    # distinction is the difference between a stop the setup earned and a stop of
    # last resort, and every R-multiple downstream should be readable as such.
    ENTRY_CANDLE = "ENTRY_CANDLE"


class TriggerResolution(StrEnum):
    """Which crossing wins when both levels were crossed.

    LATEST takes the crossing that completed the setup, giving the tighter stop
    that exits on partial invalidation. WIDEST keeps the position alive until
    both crossings are undone.
    """

    LATEST = "LATEST"
    WIDEST = "WIDEST"


class RiskPlanRejection(StrEnum):
    """Why a signal cannot be turned into a tradable plan."""

    NO_TRIGGER_CANDLE = "NO_TRIGGER_CANDLE"
    STOP_ON_WRONG_SIDE = "STOP_ON_WRONG_SIDE"
    RISK_BELOW_FLOOR = "RISK_BELOW_FLOOR"
    RISK_ABOVE_CAP = "RISK_ABOVE_CAP"


class RiskPlanRejected(DomainValidationError):
    """Raised when a signal cannot be sized. Carries a machine-readable code."""

    def __init__(self, rejection: RiskPlanRejection, detail: str) -> None:
        super().__init__(f"{rejection.value}: {detail}")
        self.rejection = rejection
        self.detail = detail


@dataclass(frozen=True)
class Bar:
    """One completed candle on a single instrument."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float

@dataclass(frozen=True)
class StopTriggerCandle:
    """The candle whose index high/low becomes the initial stop.

    Normally the 5-minute candle that crossed the reference level. When no such
    candle exists it is the one-minute candle that fired the entry -- see
    ``entry_candle_stop`` -- and ``trigger`` says which.
    """

    trigger: StopTrigger
    timestamp: datetime
    index_high: float
    index_low: float

    def stop_for(self, direction: Direction) -> float:
        return self.index_low if direction is Direction.BULLISH else self.index_high


def _crossed_up(previous: Bar | None, current: Bar, level: float) -> bool:
    """True when `current` closed above `level` having come from at or below it.

    The previous close is the primary evidence. `current.low <= level` is
    accepted as well so the very first bar of a series, and a bar that dipped
    through the level and recovered inside the same five minutes, still count.
    """
    if current.close <= level:
        return False
    if previous is not None and previous.close <= level:
        return True
    return current.low <= level


def _crossed_down(previous: Bar | None, current: Bar, level: float) -> bool:
    if current.close >= level:
        return False
    if previous is not None and previous.close >= level:
        return True
    return current.high >= level


def _index_bar_at(index_bars: Sequence[Bar], timestamp: datetime) -> Bar | None:
    for bar in index_bars:
        if bar.timestamp == timestamp:
            return bar
    return None

def find_stop_trigger(
    *,
    direction: Direction,
    index_bars: Sequence[Bar],
    futures_bars: Sequence[Bar],
    futures_vwap: Mapping[datetime, float],
    reference_midpoint: float,
    reference_timestamp: datetime,
    entry_timestamp: datetime,
    resolution: TriggerResolution = TriggerResolution.LATEST,
) -> StopTriggerCandle | None:
    """Locate the 5-minute candle that crossed a reference level.

    Both series must be 5-minute bars in ascending order, stamped with the
    *start* of their slot, and only bars after the red reference bar and at or
    before the entry are considered.

    The caller owns a contract this function cannot check: the bars must hold
    only price that had printed by ``entry_timestamp``. The entry fires on a
    one-minute close, so the 5-minute slot that crossed the level is still open
    at that moment -- an entry at 09:31 sits inside the 09:30 bar -- and that
    bar has to be passed in truncated at the entry minute. Hand in the finished
    09:30-09:34 bar instead and the stop, which is the denominator of every
    R-multiple on the trade, is read off price the strategy had not seen.
    ``_bars_known_at`` in the decision log builds them this way.
    """
    crossed = _crossed_up if direction is Direction.BULLISH else _crossed_down
    window = (reference_timestamp, entry_timestamp)
    candidates: list[StopTriggerCandle] = []

    latest_index: StopTriggerCandle | None = None
    for position, bar in enumerate(index_bars):
        if not window[0] < bar.timestamp <= window[1]:
            continue
        previous = index_bars[position - 1] if position else None
        if crossed(previous, bar, reference_midpoint):
            latest_index = StopTriggerCandle(
                trigger=StopTrigger.MIDPOINT_CROSS,
                timestamp=bar.timestamp,
                index_high=bar.high,
                index_low=bar.low,
            )
    if latest_index is not None:
        candidates.append(latest_index)

    latest_futures: StopTriggerCandle | None = None
    for position, bar in enumerate(futures_bars):
        if not window[0] < bar.timestamp <= window[1]:
            continue
        level = futures_vwap.get(bar.timestamp)
        if level is None:
            continue
        previous = futures_bars[position - 1] if position else None
        if not crossed(previous, bar, level):
            continue
        # The trigger is a futures event; the stop is still an index level.
        index_bar = _index_bar_at(index_bars, bar.timestamp)
        if index_bar is None:
            continue
        latest_futures = StopTriggerCandle(
            trigger=StopTrigger.FUTURES_VWAP_CROSS,
            timestamp=bar.timestamp,
            index_high=index_bar.high,
            index_low=index_bar.low,
        )
    if latest_futures is not None:
        candidates.append(latest_futures)

    if not candidates:
        return None
    if resolution is TriggerResolution.LATEST:
        return max(candidates, key=lambda candle: candle.timestamp)
    if direction is Direction.BULLISH:
        return min(candidates, key=lambda candle: candle.index_low)
    return max(candidates, key=lambda candle: candle.index_high)


def entry_candle_stop(
    *,
    index_bars_1m: Sequence[Bar],
    entry_timestamp: datetime,
) -> StopTriggerCandle | None:
    """The stop of last resort: the one-minute candle that fired the entry.

    ``find_stop_trigger`` returns None whenever the setup completed without a
    *completed* 5-minute candle closing across the midpoint or the futures VWAP.
    That is common rather than exceptional -- on 2026-09-03 it was 5 of 8
    admissions -- and the old behaviour was to reject the entry outright, so the
    strategy's own admitted signals went unsized and unmeasured.

    The entry fires on a completed one-minute close, and that candle is the one
    that produced the decision. Its extreme is therefore the narrowest level
    whose loss means the decision was wrong, it is always available, and the risk
    number stays the strategy's own rather than borrowed from a candle that had
    nothing to do with the entry.

    ``entry_timestamp`` is the stamp the *decision* carries, which is one minute
    after the candle that produced it: the replay evaluates candle T once T has
    closed, at T+1min, and stamps the admission with the evaluation time. So the
    triggering candle is the last one to close strictly *before* that stamp --
    not the bar carrying it, which is the first bar the position is held and has
    not printed yet when the stop is priced. Reading that bar instead set the
    stop at an extreme the very same bar had already made, turning every
    fallback-priced entry into an instant -1R.

    Selecting the last bar before the stamp rather than subtracting a fixed
    minute keeps this correct across a gap in the series, and keeps the callers
    from having to know the replay's clock.

    Returns None only when no candle precedes the entry stamp, which is a data
    fault rather than a strategy verdict; ``build_risk_plan`` then rejects with
    NO_TRIGGER_CANDLE as before.
    """
    triggering: Bar | None = None
    for bar in index_bars_1m:
        if bar.timestamp >= entry_timestamp:
            continue
        if triggering is None or bar.timestamp > triggering.timestamp:
            triggering = bar
    if triggering is None:
        return None
    return StopTriggerCandle(
        trigger=StopTrigger.ENTRY_CANDLE,
        timestamp=triggering.timestamp,
        index_high=triggering.high,
        index_low=triggering.low,
    )


@dataclass(frozen=True)
class RiskPlan:
    """Everything decided before entry. Immutable for the life of the trade."""

    direction: Direction
    entry_timestamp: datetime
    entry_price: float
    stop_price: float
    # None means "run until the stop, the trail, or the session flat time takes
    # it out". A target is opt-in precisely because it silences the trail.
    target_price: float | None
    risk_points: float
    reward_multiple: float | None
    trigger: StopTrigger
    trigger_timestamp: datetime
    trail_activation_price: float
    trail_distance_points: float
    session_flat_time: time
    quantity_lots: int

    def r_multiple_at(self, price: float) -> float:
        """Signed R for an exit at `price`. Positive is a gain, either side."""
        moved = (
            price - self.entry_price
            if self.direction is Direction.BULLISH
            else self.entry_price - price
        )
        return round(moved / self.risk_points, 4)


def build_risk_plan(
    *,
    direction: Direction,
    entry_timestamp: datetime,
    entry_price: float,
    trigger_candle: StopTriggerCandle | None,
    reward_multiple: float | None = DEFAULT_REWARD_MULTIPLE,
    minimum_risk_points: float = DEFAULT_MINIMUM_RISK_POINTS,
    maximum_risk_points: float = DEFAULT_MAXIMUM_RISK_POINTS,
    trail_activation_r: float = DEFAULT_TRAIL_ACTIVATION_R,
    session_flat_time: time = DEFAULT_SESSION_FLAT_TIME,
    quantity_lots: int = DEFAULT_QUANTITY_LOTS,
) -> RiskPlan:
    """Turn a signal plus its trigger candle into a sized, stopped plan.

    Raises `RiskPlanRejected` rather than returning a plan the strategy should
    not trade, so a rejection carries a reason code into the decision log
    instead of silently becoming a trade with an arbitrary stop.
    """
    if trigger_candle is None:
        raise RiskPlanRejected(
            RiskPlanRejection.NO_TRIGGER_CANDLE,
            "no completed 5m candle crossed the midpoint or the futures VWAP",
        )
    stop_price = trigger_candle.stop_for(direction)
    bullish = direction is Direction.BULLISH
    risk_points = (
        entry_price - stop_price if bullish else stop_price - entry_price
    )
    if risk_points <= 0:
        raise RiskPlanRejected(
            RiskPlanRejection.STOP_ON_WRONG_SIDE,
            f"stop {stop_price} is not beyond entry {entry_price} for {direction.value}",
        )
    if risk_points < minimum_risk_points:
        raise RiskPlanRejected(
            RiskPlanRejection.RISK_BELOW_FLOOR,
            f"risk {risk_points:.2f} < floor {minimum_risk_points:.2f}",
        )
    if risk_points > maximum_risk_points:
        raise RiskPlanRejected(
            RiskPlanRejection.RISK_ABOVE_CAP,
            f"risk {risk_points:.2f} > cap {maximum_risk_points:.2f}",
        )

    activation = risk_points * trail_activation_r
    sign = 1.0 if bullish else -1.0
    return RiskPlan(
        direction=direction,
        entry_timestamp=entry_timestamp,
        entry_price=float(entry_price),
        stop_price=float(stop_price),
        target_price=(
            None
            if reward_multiple is None
            else float(entry_price + sign * risk_points * reward_multiple)
        ),
        risk_points=float(risk_points),
        reward_multiple=None if reward_multiple is None else float(reward_multiple),
        trigger=trigger_candle.trigger,
        trigger_timestamp=trigger_candle.timestamp,
        trail_activation_price=float(entry_price + sign * activation),
        trail_distance_points=float(risk_points),
        session_flat_time=session_flat_time,
        quantity_lots=int(quantity_lots),
    )
