"""Derived exits: let a research day close its own trades and carry on.

The replay owns the state machine, but nothing in it can close a trade. The one
path from ACTIVE to CLOSED is the injected-exit block, so a day replayed with no
injected exits opens one position and then refuses every later candidate with
``ACTIVE_TRADE_BLOCK`` until the close. A 375-minute session yields one entry,
and the midpoint wait and the working-reference search both sit idle for hours.

The exit policy itself is not missing -- it runs in the decision log, *after* the
replay has finished, so its verdict can never reach the state machine. This
module supplies the one edge that was absent: it resolves each admitted entry to
the moment the policy would have closed it, and feeds that moment back through
``exit_timestamps`` -- the same parameter the live path uses to carry real
premium-priced exits in from ``PAPER-STD`` orders. One mechanism for closing a
trade, two sources.

Resolution is an iterated replay:

1. replay the day with the exits resolved so far,
2. find the earliest admitted entry that has no exit yet,
3. price its stop, walk the one-minute bars through the policy, take the exit,
4. repeat until every admitted entry has one.

This terminates because the replay consumes an exit only when it reaches it, so
an exit at 10:00 cannot change any decision before 10:00: each pass leaves the
whole prefix of the day identical and only extends it. Exits are therefore
resolved in increasing time order, one per pass, bounded by the number of
entries the day can admit. The bound is asserted rather than trusted.

Two clocks meet here, and confusing them silently loses trades:

* The replay evaluates the candle stamped ``T`` at ``T + 1min`` -- the moment its
  close is known -- and stamps its events and trade rows with that later value.
  It also consumes exits at the *top* of that minute, before the block that
  creates a trade row.
* A ``TradeOutcome`` is stamped with the *start* of the bar the policy closed on.

So an outcome is converted to a replay exit by adding one minute: an exit priced
off the bar stamped 09:31 is knowable at 09:32 and must be fed as 09:32. Fed as
09:31 it would arrive one minute before the trade row it closes, find nothing
ACTIVE, and be dropped -- which is exactly what happens to a position stopped out
on the first bar it was held.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Iterable

import pandas as pd

from red_bar_lab.domain.red_bar_v2 import (
    Bar,
    Direction,
    RiskPlan,
    RiskPlanRejected,
    TradeOutcome,
    TriggerResolution,
    advance,
    build_risk_plan,
    find_stop_trigger,
    open_position,
)
from red_bar_lab.intelligence.market_context import session_vwap
from red_bar_lab.services.red_bar_v2_futures_historical_replay import (
    replay_red_bar_v2_day_with_futures_vwap,
)
from red_bar_lab.services.red_bar_v2_historical_replay import RedBarV2ReplayResult
from red_bar_lab.strategy.red_bar_v2_working_reference import structure_failed

ENTRY_EVENT = "CANDIDATE_ADMISSION"

#: An admitted entry whose event carries no price or no reference to price it
#: against. Not a risk rejection -- the evidence needed to judge it is absent --
#: so it is reported separately and never counted among the rejected plans.
MISSING_EVIDENCE = "MISSING_EVIDENCE"

#: A position the day ended holding. It has no exit to feed back, so resolution
#: stops rather than looping on an entry it can never satisfy.
OPEN_AT_END = "OPEN_AT_END"

#: The gap between the two clocks in the module docstring. Every exit crosses it.
KNOWN_AT_LAG = pd.Timedelta(minutes=1)


def _to_datetime(value: Any) -> datetime:
    """Accept the datetime shapes the replay emits and return a bare datetime."""
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed
    raise TypeError(f"unsupported timestamp: {value!r}")


def _align_to_index(frame_index: pd.DatetimeIndex, stamp: datetime) -> datetime:
    """Match the frame clock: naive stays naive, aware is stripped after check."""
    if frame_index.tz is None:
        return stamp.replace(tzinfo=None)
    return stamp


def _five_minute_bars(frame: pd.DataFrame) -> list[Bar]:
    """Aggregate one-minute OHLCV into five-minute bars, stamped at slot start."""
    aggregated = frame.resample("5min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["close"])
    return [
        Bar(
            timestamp=stamp.to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for stamp, row in aggregated.iterrows()
    ]


def _bars_known_at(frame: pd.DataFrame, entry_timestamp: datetime) -> list[Bar]:
    """Five-minute bars as they stood at the entry minute, last one partial.

    The entry fires on a one-minute close, so the 5-minute slot that crossed the
    reference level is still open when the stop is priced: an entry at 09:31 sits
    inside the 09:30-09:34 slot. Resampling the whole day first and then
    filtering by slot label -- which is what this used to do -- gave that slot
    its finished high and low, so a stop set at 09:31 could come from the 09:34
    low. The stop is the denominator of every R-multiple on the trade, so the
    lookahead did not just move one number, it rescaled the day's results.

    Truncating the frame instead keeps the slot but stops it at the entry, which
    is exactly what a live evaluator can see. In practice the crossing extreme is
    usually made by the crossing minute itself, so the stop is unchanged -- the
    difference is that it is now unchanged *because* of price the strategy had,
    not by luck.
    """
    return _five_minute_bars(frame.loc[frame.index <= entry_timestamp])


def _five_minute_vwap(futures_frame: pd.DataFrame) -> dict[datetime, float]:
    """Session VWAP sampled at each five-minute slot's close."""
    vwap = session_vwap(futures_frame)
    slots: dict[datetime, tuple[datetime, float]] = {}
    for stamp, value in vwap.items():
        slot = stamp.floor("5min")
        latest = slots.get(slot)
        if latest is None or stamp > latest[0]:
            slots[slot] = (stamp, float(value))
    return {slot: value for slot, (_, value) in slots.items() if pd.notna(value)}


def _vwap_known_at(
    futures_frame: pd.DataFrame, entry_timestamp: datetime
) -> dict[datetime, float]:
    """Slot VWAPs as they stood at the entry minute.

    Session VWAP is cumulative from the open, so truncating the frame leaves
    every retained minute's value untouched and only stops the open slot from
    being sampled at a close that had not happened. See ``_bars_known_at``.
    """
    return _five_minute_vwap(futures_frame.loc[futures_frame.index <= entry_timestamp])


def replay_frame(candles: pd.DataFrame) -> pd.DataFrame:
    """Normalise candles exactly as the replay does before touching them."""
    from red_bar_lab.services.red_bar_v2_historical_replay import _normalise

    return _normalise(candles)


def one_minute_bars(frame: pd.DataFrame) -> list[Bar]:
    """The whole day as one-minute bars, for walking a position forward."""
    return [
        Bar(
            timestamp=stamp.to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for stamp, row in frame.iterrows()
    ]


def _walk_to_outcome(
    plan: RiskPlan,
    index_bars_1m: list[Bar],
    entry_timestamp: datetime,
    governing_midpoint: float,
) -> tuple[TradeOutcome | None, datetime | None]:
    """Advance the position bar by bar until the policy closes it.

    `governing_midpoint` is the level the entry was taken against, so a close
    back through it is a structural break. The entry bar itself cannot break it:
    admission required that bar's close to be beyond the level already.
    """
    position = open_position(plan)
    outcome = None
    last_timestamp: datetime | None = None
    for bar in index_bars_1m:
        if bar.timestamp < entry_timestamp:
            continue
        last_timestamp = bar.timestamp
        position, closed = advance(
            position,
            bar,
            structure_failed=structure_failed(
                governing_midpoint,
                direction=plan.direction.value,
                close=bar.close,
            ),
        )
        if closed is not None:
            outcome = closed
            break
    if outcome is None:
        return None, last_timestamp
    return outcome, outcome.exit_timestamp


@dataclass(frozen=True)
class DerivedExit:
    """One admitted entry and the moment the policy took it off.

    ``exit_timestamp`` is the outcome's own stamp -- the start of the bar the
    policy closed on -- and is what a reader should see. ``fed_at`` is that value
    moved onto the replay's known-at clock, and is what the replay was actually
    given. They differ by one minute for every resolved trade; see the module
    docstring for why conflating them loses same-bar stop-outs.
    """

    entry_timestamp: datetime
    trade_id: str | None
    direction: str
    plan: RiskPlan | None
    rejection: str | None
    outcome: TradeOutcome | None
    exit_timestamp: datetime | None
    fed_at: datetime | None
    status: str | None = None
    rejection_detail: str | None = None

    @property
    def planned(self) -> bool:
        """A real position: it was sized and stopped, so its R means something."""
        return self.plan is not None


@dataclass(frozen=True)
class DerivedExitResolution:
    """Everything the loop settled, plus what it cost to settle it."""

    exit_timestamps: tuple[datetime, ...]
    trades: tuple[DerivedExit, ...]
    iterations: int

    def by_entry(self) -> dict[datetime, DerivedExit]:
        """Keyed for joining onto a replay's events. Entry stamps are unique."""
        return {trade.entry_timestamp: trade for trade in self.trades}


def _known_at(stamp: datetime) -> datetime:
    """Move a bar-start stamp onto the replay's known-at clock."""
    return (pd.Timestamp(stamp) + KNOWN_AT_LAG).to_pydatetime()


def _admitted_entries(
    replay: RedBarV2ReplayResult, frame_index: pd.DatetimeIndex
) -> list[tuple[datetime, Any]]:
    """Admitted entries in event order, stamped on the frame's clock.

    An admission with no trade id opened no trade row, so it can neither be
    closed nor block anything, and is skipped -- the same rule the decision log
    applies.
    """
    found: list[tuple[datetime, Any]] = []
    for event in replay.events:
        if event.event_type != ENTRY_EVENT or not event.candidate_allowed:
            continue
        if event.trade_id is None:
            continue
        found.append((_align_to_index(frame_index, _to_datetime(event.timestamp)), event))
    return found


def _policy_overrides(
    reward_multiple: float | None,
    minimum_risk_points: float | None,
    maximum_risk_points: float | None,
    trail_activation_r: float | None,
    session_flat_time: time | None,
) -> dict[str, Any]:
    """Only the knobs the caller set, so the rest keep their domain defaults."""
    policy: dict[str, Any] = {}
    if reward_multiple is not None:
        policy["reward_multiple"] = reward_multiple
    if minimum_risk_points is not None:
        policy["minimum_risk_points"] = minimum_risk_points
    if maximum_risk_points is not None:
        policy["maximum_risk_points"] = maximum_risk_points
    if trail_activation_r is not None:
        policy["trail_activation_r"] = trail_activation_r
    if session_flat_time is not None:
        policy["session_flat_time"] = session_flat_time
    return policy


def _resolve_entry(
    event: Any,
    entry_timestamp: datetime,
    *,
    frame: pd.DataFrame,
    futures_frame: pd.DataFrame,
    index_bars_1m: list[Bar],
    trigger_resolution: TriggerResolution,
    policy: dict[str, Any],
) -> DerivedExit:
    """Price one admitted entry and walk it to the exit the policy would take.

    Every path returns a ``DerivedExit``; the two that produce no position still
    carry a ``fed_at``, because a row the replay opened has to be closed or the
    rest of the day is spent under ``ACTIVE_TRADE_BLOCK``. Closing it at the next
    minute is the earliest the replay can act on, and the REJECT row says why it
    was never a real trade.
    """
    def unplannable(rejection: str, detail: str | None = None) -> DerivedExit:
        return DerivedExit(
            entry_timestamp=entry_timestamp,
            trade_id=event.trade_id,
            direction=event.direction,
            plan=None,
            rejection=rejection,
            outcome=None,
            exit_timestamp=None,
            fed_at=_known_at(entry_timestamp),
            rejection_detail=detail,
        )

    entry_price = event.details.get("index_close")
    reference_timestamp = event.details.get("reference_timestamp")
    reference_midpoint = event.details.get("reference_midpoint")
    if entry_price is None or reference_timestamp is None or reference_midpoint is None:
        return unplannable(MISSING_EVIDENCE)

    try:
        trigger = find_stop_trigger(
            direction=Direction(event.direction),
            # As known at the entry minute, not as the day finished. The
            # crossing slot is still open when the stop is priced.
            index_bars=_bars_known_at(frame, entry_timestamp),
            futures_bars=_bars_known_at(futures_frame, entry_timestamp),
            futures_vwap=_vwap_known_at(futures_frame, entry_timestamp),
            reference_midpoint=float(reference_midpoint),
            reference_timestamp=_align_to_index(
                frame.index, _to_datetime(reference_timestamp)
            ),
            entry_timestamp=entry_timestamp,
            resolution=trigger_resolution,
        )
        plan = build_risk_plan(
            direction=Direction(event.direction),
            entry_timestamp=entry_timestamp,
            entry_price=float(entry_price),
            trigger_candle=trigger,
            **policy,
        )
    except RiskPlanRejected as rejected:
        return unplannable(rejected.rejection.value, rejected.detail)

    outcome, _ = _walk_to_outcome(
        plan, index_bars_1m, entry_timestamp, float(reference_midpoint)
    )
    if outcome is None:
        # The day ended holding it. There is no exit to feed, and no later
        # candidate could have been admitted anyway.
        return DerivedExit(
            entry_timestamp=entry_timestamp,
            trade_id=event.trade_id,
            direction=event.direction,
            plan=plan,
            rejection=None,
            outcome=None,
            exit_timestamp=None,
            fed_at=None,
            status=OPEN_AT_END,
        )
    return DerivedExit(
        entry_timestamp=entry_timestamp,
        trade_id=event.trade_id,
        direction=event.direction,
        plan=plan,
        rejection=None,
        outcome=outcome,
        exit_timestamp=outcome.exit_timestamp,
        fed_at=_known_at(outcome.exit_timestamp),
    )


class DerivedExitsDidNotConverge(RuntimeError):
    """The loop hit its bound. Monotonicity is broken; do not trust the numbers."""


def _assert_prefix_unchanged(
    order: list[datetime], admitted: list[tuple[datetime, Any]]
) -> None:
    """The whole point of the loop, checked every pass instead of argued once.

    Feeding an exit at 10:00 must not disturb any decision before 10:00. If it
    did, the entries resolved so far could stop being the entries the day makes,
    and every exit derived from them would be priced against a day that no longer
    exists. Cheaper to check than to debug.
    """
    if len(admitted) < len(order):
        raise DerivedExitsDidNotConverge(
            f"feeding {len(order)} exits dropped an earlier entry: "
            f"{len(admitted)} admitted, {len(order)} already resolved"
        )
    for expected, (found, _event) in zip(order, admitted):
        if expected != found:
            raise DerivedExitsDidNotConverge(
                f"feeding exits moved a resolved entry: expected {expected}, found {found}"
            )


def resolve_red_bar_v2_derived_exits(
    index_candles: pd.DataFrame,
    futures_candles: pd.DataFrame,
    *,
    instrument_key: str,
    vwap_instrument_key: str,
    reward_multiple: float | None = None,
    minimum_risk_points: float | None = None,
    maximum_risk_points: float | None = None,
    trail_activation_r: float | None = None,
    session_flat_time: time | None = None,
    trigger_resolution: TriggerResolution = TriggerResolution.LATEST,
) -> DerivedExitResolution:
    """Resolve one day's exits from the policy, by iterated replay.

    Returns the exit timestamps to feed a final replay, in the replay's own
    known-at clock, plus one ``DerivedExit`` per admitted entry in the order they
    were resolved -- which is the order they happened.

    ``iterations`` counts replays performed. In the ordinary case it is one more
    than the number of trades: one pass resolves each entry, and a last pass
    finds nothing left. It is *not* an efficiency knob to tune -- it is the number
    the termination argument predicts, so a test can check the argument held.
    """
    frame = replay_frame(index_candles)
    futures_frame = replay_frame(futures_candles)
    index_bars_1m = one_minute_bars(frame)
    policy = _policy_overrides(
        reward_multiple,
        minimum_risk_points,
        maximum_risk_points,
        trail_activation_r,
        session_flat_time,
    )

    order: list[datetime] = []
    resolved: dict[datetime, DerivedExit] = {}
    fed: list[datetime] = []
    # One pass per entry the day could possibly admit, plus the pass that finds
    # nothing left. A day cannot admit more entries than it has minutes.
    bound = len(frame.index) + 1

    for iteration in range(1, bound + 1):
        replay, _health = replay_red_bar_v2_day_with_futures_vwap(
            index_candles,
            futures_candles,
            instrument_key=instrument_key,
            vwap_instrument_key=vwap_instrument_key,
            exit_timestamps=tuple(fed),
        )
        admitted = _admitted_entries(replay, frame.index)
        _assert_prefix_unchanged(order, admitted)

        pending = next(
            ((stamp, event) for stamp, event in admitted if stamp not in resolved),
            None,
        )
        if pending is None:
            return DerivedExitResolution(
                exit_timestamps=tuple(fed),
                trades=tuple(resolved[stamp] for stamp in order),
                iterations=iteration,
            )

        stamp, event = pending
        trade = _resolve_entry(
            event,
            stamp,
            frame=frame,
            futures_frame=futures_frame,
            index_bars_1m=index_bars_1m,
            trigger_resolution=trigger_resolution,
            policy=policy,
        )
        order.append(stamp)
        resolved[stamp] = trade
        if trade.fed_at is None:
            return DerivedExitResolution(
                exit_timestamps=tuple(fed),
                trades=tuple(resolved[key] for key in order),
                iterations=iteration,
            )
        fed.append(trade.fed_at)

    raise DerivedExitsDidNotConverge(
        f"{bound} replays did not settle every admitted entry; "
        f"{len(resolved)} resolved, last fed exit {fed[-1] if fed else None}"
    )


def resolve_next_derived_exit(
    replay: RedBarV2ReplayResult,
    index_candles: pd.DataFrame,
    futures_candles: pd.DataFrame,
    *,
    resolved_entries: Iterable[Any] = (),
    reward_multiple: float | None = None,
    minimum_risk_points: float | None = None,
    maximum_risk_points: float | None = None,
    trail_activation_r: float | None = None,
    session_flat_time: time | None = None,
    trigger_resolution: TriggerResolution = TriggerResolution.LATEST,
) -> DerivedExit | None:
    """One pass of the loop, against a replay the caller already ran.

    ``resolve_red_bar_v2_derived_exits`` runs the replay itself, once per entry,
    because it has to settle a finished day in a single call. A live cycle is not
    in that position: it replays the session every pass anyway, and the cycles
    *are* the iteration. So this resolves the earliest admitted entry that has no
    exit yet and costs no replay of its own -- the caller feeds the result back on
    its next pass, and one entry is settled per cycle until none are left.

    Returns ``None`` when every admitted entry is already resolved, which is the
    steady state and therefore the cheap one. A returned exit with ``fed_at is
    None`` is a position still open on the data available; on a live session that
    means "not closed yet", not "held to the close", so it must not be recorded as
    settled -- ask again next cycle.
    """
    frame = replay_frame(index_candles)
    futures_frame = replay_frame(futures_candles)
    already = {
        _align_to_index(frame.index, _to_datetime(stamp)) for stamp in resolved_entries
    }
    pending = next(
        (
            (stamp, event)
            for stamp, event in _admitted_entries(replay, frame.index)
            if stamp not in already
        ),
        None,
    )
    if pending is None:
        return None

    stamp, event = pending
    return _resolve_entry(
        event,
        stamp,
        frame=frame,
        futures_frame=futures_frame,
        index_bars_1m=one_minute_bars(frame),
        trigger_resolution=trigger_resolution,
        policy=_policy_overrides(
            reward_multiple,
            minimum_risk_points,
            maximum_risk_points,
            trail_activation_r,
            session_flat_time,
        ),
    )


__all__ = [
    "DerivedExit",
    "DerivedExitResolution",
    "DerivedExitsDidNotConverge",
    "ENTRY_EVENT",
    "KNOWN_AT_LAG",
    "MISSING_EVIDENCE",
    "OPEN_AT_END",
    "one_minute_bars",
    "replay_frame",
    "resolve_next_derived_exit",
    "resolve_red_bar_v2_derived_exits",
]
