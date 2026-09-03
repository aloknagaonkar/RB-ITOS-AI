"""Exit policy for a Red Bar V2 position, evaluated bar by bar.

Four exits are active, in this fixed priority:

1. stop loss — the initial structural stop, which ratchets into a trailing
   stop once the trade reaches its activation threshold
2. session flat — no position is carried past `plan.session_flat_time`
3. target — `plan.reward_multiple` times the initial risk, and only when a
   reward multiple was requested; there is no target by default
4. structure — the governing reference has been broken on a completed close

Priority is not cosmetic. When a bar's range contains both the stop and the
target, OHLC alone cannot say which was touched first, so the stop wins. That
biases every ambiguous bar against the strategy, which is the direction an
honest backtest should lean. Structure comes last for a different reason: it is
the only close-based exit here, so it is already known to have happened at the
end of the bar, while the three above it can trigger anywhere inside it.

A structural break closes the position on price alone. New entries need the full
gate — the close against the reference *and* the futures against their VWAP —
but reducing exposure should never be harder than adding it, so nothing about
the futures feed can keep a broken position open.

The trailing stop is advanced from a bar's extreme only *after* that bar has
been tested against the stop already in force. Advancing first would let a
favourable wick inside the same bar rescue a position that had already been
stopped out, which is the most common way a replay flatters itself.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from .enums import Direction
from .risk import Bar, RiskPlan, StopTrigger

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python 3.10 compatibility
    from enum import Enum

    class StrEnum(str, Enum):
        """Compatibility implementation for Python 3.10."""


class ExitReason(StrEnum):
    """Why an index-level V2 position was closed.

    Deliberately *not* ``strategy.trade_models.ExitReason``, and the two must not
    be merged on the grounds that they look similar. This one names index-level
    outcomes of the V2 risk plan; that one names option-premium outcomes of the
    legacy trade engine, has ``OPEN``/``NOT_EVALUABLE``/``BREAK_EVEN`` states
    this one has no use for, and has no ``STRUCTURE`` because the legacy engine
    cannot see a reference level. No value crosses between them today: the live
    structural exit records the free-text ``AUTO_RED_BAR_V2_STRUCTURE`` on the
    order row, and the only ``ExitReason(...)`` parse of a stored string
    (``red_bar_v2_decision_log``) reads rows this enum wrote. A single enum
    becomes the right answer when ``TradeOutcome`` is persisted into
    ``paper_trade_outcomes`` alongside premium outcomes -- until then it would
    just add members nothing can produce.
    """

    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    TARGET = "TARGET"
    SESSION_FLAT = "SESSION_FLAT"
    STRUCTURE = "STRUCTURE"

@dataclass(frozen=True)
class OpenPosition:
    """Mutable-by-replacement state of a live position."""

    plan: RiskPlan
    stop_in_force: float
    trailing_active: bool
    extreme_favourable: float
    extreme_adverse: float
    bars_held: int

    @property
    def bullish(self) -> bool:
        return self.plan.direction is Direction.BULLISH


@dataclass(frozen=True)
class TradeOutcome:
    """One closed trade, in the terms that make trades comparable."""

    direction: Direction
    trigger: StopTrigger
    entry_timestamp: datetime
    entry_price: float
    exit_timestamp: datetime
    exit_price: float
    stop_price: float
    target_price: float | None
    risk_points: float
    exit_reason: ExitReason
    points: float
    r_multiple: float
    mfe_points: float
    mae_points: float
    mfe_r: float
    mae_r: float
    holding_minutes: float
    bars_held: int
    quantity_lots: int


def open_position(plan: RiskPlan) -> OpenPosition:
    return OpenPosition(
        plan=plan,
        stop_in_force=plan.stop_price,
        trailing_active=False,
        extreme_favourable=plan.entry_price,
        extreme_adverse=plan.entry_price,
        bars_held=0,
    )

def _advance_trail(position: OpenPosition, bar: Bar) -> OpenPosition:
    """Move the stop up (long) or down (short) once the trade is far enough on.

    At the activation threshold the stop goes to breakeven, and from there it
    follows the trade's best price by `trail_distance_points`. The stop never
    retreats.
    """
    plan = position.plan
    if position.bullish:
        extreme = max(position.extreme_favourable, bar.high)
        adverse = min(position.extreme_adverse, bar.low)
        activated = position.trailing_active or extreme >= plan.trail_activation_price
        stop = position.stop_in_force
        if activated:
            stop = max(stop, plan.entry_price, extreme - plan.trail_distance_points)
    else:
        extreme = min(position.extreme_favourable, bar.low)
        adverse = max(position.extreme_adverse, bar.high)
        activated = position.trailing_active or extreme <= plan.trail_activation_price
        stop = position.stop_in_force
        if activated:
            stop = min(stop, plan.entry_price, extreme + plan.trail_distance_points)
    return replace(
        position,
        stop_in_force=stop,
        trailing_active=activated,
        extreme_favourable=extreme,
        extreme_adverse=adverse,
        bars_held=position.bars_held + 1,
    )


def _stop_touched(position: OpenPosition, bar: Bar) -> bool:
    if position.bullish:
        return bar.low <= position.stop_in_force
    return bar.high >= position.stop_in_force


def _target_touched(position: OpenPosition, bar: Bar) -> bool:
    """False whenever no target was requested, so the trail is left to work."""
    target = position.plan.target_price
    if target is None:
        return False
    if position.bullish:
        return bar.high >= target
    return bar.low <= target

def _close(
    position: OpenPosition,
    bar: Bar,
    exit_price: float,
    reason: ExitReason,
) -> TradeOutcome:
    """Build the outcome record, folding the closing bar into MFE and MAE."""
    plan = position.plan
    bullish = position.bullish
    if bullish:
        extreme_favourable = max(position.extreme_favourable, bar.high)
        extreme_adverse = min(position.extreme_adverse, bar.low)
        points = exit_price - plan.entry_price
        mfe = extreme_favourable - plan.entry_price
        mae = plan.entry_price - extreme_adverse
    else:
        extreme_favourable = min(position.extreme_favourable, bar.low)
        extreme_adverse = max(position.extreme_adverse, bar.high)
        points = plan.entry_price - exit_price
        mfe = plan.entry_price - extreme_favourable
        mae = extreme_adverse - plan.entry_price
    risk = plan.risk_points
    held = (bar.timestamp - plan.entry_timestamp).total_seconds() / 60.0
    return TradeOutcome(
        direction=plan.direction,
        trigger=plan.trigger,
        entry_timestamp=plan.entry_timestamp,
        entry_price=plan.entry_price,
        exit_timestamp=bar.timestamp,
        exit_price=float(exit_price),
        stop_price=plan.stop_price,
        target_price=plan.target_price,
        risk_points=risk,
        exit_reason=reason,
        points=round(float(points), 2),
        r_multiple=round(float(points) / risk, 4),
        mfe_points=round(max(0.0, float(mfe)), 2),
        mae_points=round(max(0.0, float(mae)), 2),
        mfe_r=round(max(0.0, float(mfe)) / risk, 4),
        mae_r=round(max(0.0, float(mae)) / risk, 4),
        holding_minutes=round(held, 2),
        bars_held=position.bars_held + 1,
        quantity_lots=plan.quantity_lots,
    )


def advance(
    position: OpenPosition,
    bar: Bar,
    *,
    structure_failed: bool = False,
) -> tuple[OpenPosition, TradeOutcome | None]:
    """Evaluate one completed bar against the plan.

    Returns the position to carry into the next bar and, when the position
    closed on this bar, its outcome. The session-flat exit fills at the open of
    the first bar starting at or after the flat time, which is the price at
    exactly that moment rather than five minutes later.

    ``structure_failed`` is the caller's verdict on the governing reference for
    this bar: True when the close has broken back through the level the position
    was entered against. It fills at ``bar.close``, because a close-based signal
    is not known until the bar is complete and filling anywhere better would be
    inventing a price.
    """
    plan = position.plan
    if _stop_touched(position, bar):
        reason = (
            ExitReason.TRAILING_STOP if position.trailing_active else ExitReason.STOP_LOSS
        )
        return position, _close(position, bar, position.stop_in_force, reason)
    if bar.timestamp.timetz().replace(tzinfo=None) >= plan.session_flat_time:
        return position, _close(position, bar, bar.open, ExitReason.SESSION_FLAT)
    if _target_touched(position, bar):
        assert plan.target_price is not None
        return position, _close(position, bar, plan.target_price, ExitReason.TARGET)
    if structure_failed:
        return position, _close(position, bar, bar.close, ExitReason.STRUCTURE)
    return _advance_trail(position, bar), None
