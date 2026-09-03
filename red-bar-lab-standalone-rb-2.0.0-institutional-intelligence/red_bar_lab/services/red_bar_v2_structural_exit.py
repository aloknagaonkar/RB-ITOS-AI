"""The two structural exits for a live Red Bar V2 position.

Both ask the same question -- *has the level this trade was taken on failed?* --
and they differ in which level they are allowed to see.

``execute_structural_stop_exits`` is the older of the two and has been live all
along, called once per ~32-second cycle from ``paper_monitor``. It exits a PE on
a completed 1-minute close above the reference **high** and a CE on a close below
the reference **low**: price has to clear the whole red bar band before it acts,
and it knows nothing about the working reference, so a position opened on a
deputy is judged against a band it was never taken on.

``evaluate_red_bar_v2_structural_exit`` is the rule from the agreed table --
*exit any open position on a completed 1-minute close against the governing
level* -- and it had no production caller at all. ``structure_failed`` existed,
was tested, and was reachable only from research code that threw its verdict
away. It is called per open row from ``automation.monitor_and_exit`` and its
verdict is ranked inside ``PaperExitEngine``, so it can be weighed against the
premium protections rather than firing beside them.

The midpoint rule subsumes the boundary rule wherever both may act: any close
beyond the high is also beyond the midpoint, so for an INITIAL or REVERSAL
position the boundary exit now only fires where the midpoint verdict declined --
no level published yet, a close too stale to trust, or a close the entry already
knew about. That is why the boundary rule stays: it is the backstop for exactly
the cases the new rule refuses, and for a deputy-born position it is the only
structural exit either rule can offer at all.

What is *not* covered by either, and is the reason this rule matters: for a V2
row the configured premium stop is deliberately excluded
(``red_bar_v2_external_initial_exit`` in the exit engine) on the stated grounds
that V2 carries its own initial-loss authority. That authority was a
completed-candle RSI exit (still live at ``paper_monitor``, on thresholds rather
than on structure) plus the boundary rule above -- a stop a full half-band away
from the level the trade was actually taken on. The midpoint rule is the missing
authority, at the distance the strategy actually reasons about.

Three things make it safe to act on:

*   **The level comes from the replay's ``rule_state``, not from an event.**
    ``index_close`` on the snapshot is read off the latest event, and events are
    emitted only on candidates, admissions, upgrades and closures -- so it
    freezes for as long as nothing happens, which on 2026-09-03 was 56 minutes.
    ``governing_close`` advances every candle.
*   **The direction is the position's own**, taken from the option it holds. The
    snapshot's ``direction`` field is the last *admitted* direction and is
    exactly the value that went stale; a CE row is long the index whatever the
    strategy currently thinks.
*   **A close the entry already knew about cannot invalidate the entry.** The
    close is only consulted if it became known after the order was placed.
*   **A level the entry was already on the failing side of is not that
    position's invalidation.** The replay retires a deputy the moment it produces
    an entry, so a WORKING position taken below the red bar band is published
    against the red bar midpoint from its first cycle onward. Without this the
    rule would close such a position on its very next completed close; with it,
    the position keeps the boundary backstop and the premium protections and
    waits for a level it was actually taken on. The same reasoning is now applied
    to the boundary rule, which had the identical exposure and no guard.

The practical shape of the two rules together, then: the midpoint rule is the
authority for INITIAL and REVERSAL positions, where the level sits behind the
entry by construction; the boundary rule remains the only structural authority a
deputy-born position has, and neither can be triggered by the geometry of its own
entry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable, Mapping

from red_bar_lab.execution.execution_policy import RED_BAR_V2_STRATEGY_SOURCE
from red_bar_lab.operations.red_bar_v2_ui_snapshot import RedBarV2UISnapshot
from red_bar_lab.strategy.red_bar_v2_working_reference import structure_failed

_OPEN_STATUSES = {"OPEN", "ACTIVE", "PENDING", "APPROVED", "EXECUTING"}

STRUCTURAL_EXIT_REASON = "RED_BAR_V2_STRUCTURE"
"""What the engine reports. ``monitor_and_exit`` prefixes it with ``AUTO_``."""

BAR_SECONDS = 60.0
"""One candle. The published close is stamped with the *start* of its minute."""

MAX_CLOSE_AGE_SECONDS = 240.0
"""How old a published close may be before it is refused.

Measured from the candle's own stamp, so a perfectly fresh close is already
``BAR_SECONDS`` old the instant it can be known, and the cycle that publishes it
runs every ~32 seconds. A healthy worst case is therefore around 92 seconds; the
bound leaves room for one slow pass and refuses anything beyond that rather than
closing a position against a level that may no longer govern.
"""

_OPTION_DIRECTION = {"CE": "BULLISH", "PE": "BEARISH"}

_ENTRY_INDEX_FIELDS = ("underlying_price_entry", "underlying_price", "entry_index_price")
"""Where the index level at order time is recorded, most authoritative first.

``paper_execution_orders.underlying_price_entry`` is written at every paper order
creation from the spot read in the same pass, so it is present on every live V2
row; the others are accepted so a caller can pass a lighter mapping.
"""


@dataclass(frozen=True)
class RedBarV2StructuralExit:
    """Whether the level a position was taken on has been closed through.

    ``status`` carries the reason even when ``breached`` is false, because "the
    level was never published" and "the level held" are different facts and the
    exit audit has to be able to tell them apart.
    """

    breached: bool
    status: str
    governing_reference: str | None = None
    governing_midpoint: float | None = None
    direction: str | None = None
    close: float | None = None
    close_timestamp: str | None = None
    distance_points: float | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get(source: Any, name: str) -> Any:
    if source is None:
        return None
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _moment(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _seconds_between(later: datetime, earlier: datetime) -> float | None:
    """Signed seconds, or None when the two moments cannot be compared.

    Mixing an aware moment with a naive one raises, and a raise inside the exit
    monitor would stop every other open row from being evaluated. Returning None
    lets each caller decide, and both of them decide the same way: a freshness
    or ordering claim that cannot be checked is not granted.
    """
    if (later.tzinfo is None) != (earlier.tzinfo is None):
        return None
    return (later - earlier).total_seconds()


def position_direction(
    position: Mapping[str, Any],
    signal: Mapping[str, Any] | None = None,
) -> str | None:
    """The direction of the position's own exposure, or None if unreadable.

    The option type is preferred over any recorded direction because it is a
    property of the instrument held rather than metadata about why it was
    bought: a CE gains when the index rises, and no amount of drift in the
    strategy's current view can change that. Everything here is long-only, as
    the whole exit engine already assumes.
    """
    option_type = str(_get(position, "option_type") or "").strip().upper()
    if option_type in _OPTION_DIRECTION:
        return _OPTION_DIRECTION[option_type]
    for source in (position, signal):
        recorded = str(_get(source, "direction") or "").strip().upper()
        if recorded in {"BULLISH", "BEARISH"}:
            return recorded
    return None


def entry_index_level(
    position: Mapping[str, Any],
    signal: Mapping[str, Any] | None = None,
) -> float | None:
    """The index level the position was opened at, or None if unrecorded."""
    for source in (position, signal):
        for field in _ENTRY_INDEX_FIELDS:
            level = _float(_get(source, field))
            if level is not None and level > 0.0:
                return level
    return None


def evaluate_red_bar_v2_structural_exit(
    *,
    position: Mapping[str, Any],
    signal: Mapping[str, Any] | None = None,
    snapshot: Any | None = None,
    now: datetime | None = None,
    max_close_age_seconds: float = MAX_CLOSE_AGE_SECONDS,
) -> RedBarV2StructuralExit:
    """Ask whether this position's governing level has been closed through.

    Pure: every input is already fetched, nothing is read or written here. The
    caller does one snapshot read per cycle and asks this per open row.

    A non-V2 row, a snapshot with no governing level, an unreadable direction, a
    level the entry was already on the failing side of, an unrecorded entry level,
    a stale close, or a close the entry already knew about all return
    ``breached=False`` with a status saying which -- never an exit on a guess.
    """
    source = str(_get(position, "execution_strategy_source") or "").strip()
    if not source:
        source = str(_get(signal, "execution_strategy_source") or "").strip()
    if source != RED_BAR_V2_STRATEGY_SOURCE:
        return RedBarV2StructuralExit(
            breached=False,
            status="NOT_RED_BAR_V2",
            detail=f"strategy source {source or 'UNKNOWN'} is not Red Bar V2",
        )

    midpoint = _float(_get(snapshot, "governing_midpoint"))
    close = _float(_get(snapshot, "governing_close"))
    close_stamp = _get(snapshot, "governing_close_timestamp")
    reference = _get(snapshot, "governing_reference")
    if midpoint is None or close is None or close_stamp is None:
        return RedBarV2StructuralExit(
            breached=False,
            status="LEVEL_UNAVAILABLE",
            governing_reference=reference,
            governing_midpoint=midpoint,
            close=close,
            close_timestamp=close_stamp,
            detail="no governing level published for this session yet",
        )

    direction = position_direction(position, signal)
    if direction is None:
        return RedBarV2StructuralExit(
            breached=False,
            status="DIRECTION_UNAVAILABLE",
            governing_reference=reference,
            governing_midpoint=midpoint,
            close=close,
            close_timestamp=close_stamp,
            detail="position carries no readable option type or direction",
        )

    distance = round(close - midpoint, 2)
    resolved = RedBarV2StructuralExit(
        breached=False,
        status="HOLDING",
        governing_reference=reference,
        governing_midpoint=midpoint,
        direction=direction,
        close=close,
        close_timestamp=(
            close_stamp.isoformat()
            if isinstance(close_stamp, datetime)
            else str(close_stamp)
        ),
        distance_points=distance,
    )

    # A level the position was *already* on the failing side of when it opened
    # never justified the entry, so it cannot invalidate it. This is not a corner
    # case: a deputy is retired the moment it produces an entry, so a WORKING
    # position taken below the red bar band is published against the red bar
    # midpoint from its first cycle onward, and without this guard would be closed
    # on the very next completed close. Reusing ``structure_failed`` on the entry
    # level is exactly the right test -- the question is the same question, asked
    # of the entry instead of the current close.
    #
    # Unreadable entry level refuses rather than proceeds. The asymmetry is
    # deliberate: acting on an unverified level risks closing a sound position
    # instantly, while declining leaves the reference-boundary backstop and the
    # premium protections in force. For an INITIAL entry the guard is a no-op by
    # construction -- admission required the close to be on the winning side --
    # apart from a straddle of a tick or two between the candle close and the spot
    # read at order time, which resolves as a decline to act.
    entry_level = entry_index_level(position, signal)
    if entry_level is None:
        return RedBarV2StructuralExit(
            **{
                **resolved.as_dict(),
                "status": "ENTRY_LEVEL_UNAVAILABLE",
                "detail": (
                    "position records no index level at entry, so the "
                    f"{reference or 'governing'} midpoint {midpoint:,.2f} cannot "
                    "be shown to have been behind the trade"
                ),
            }
        )
    if structure_failed(midpoint, direction=direction, close=entry_level):
        side = "below" if direction == "BULLISH" else "above"
        return RedBarV2StructuralExit(
            **{
                **resolved.as_dict(),
                "status": "ENTRY_ON_FAILING_SIDE",
                "detail": (
                    f"the {direction} position opened at {entry_level:,.2f}, "
                    f"already {side} the {reference or 'governing'} midpoint "
                    f"{midpoint:,.2f}, so that level is not this position's "
                    "invalidation"
                ),
            }
        )

    completed = _moment(close_stamp)
    if completed is None:
        return RedBarV2StructuralExit(
            **{
                **resolved.as_dict(),
                "status": "CLOSE_TIMESTAMP_UNREADABLE",
                "detail": f"cannot read a moment from {close_stamp!r}",
            }
        )
    # The close became knowable one bar after the minute it is stamped with.
    known_at = completed + timedelta(seconds=BAR_SECONDS)
    reference_now = now or (
        datetime.now(known_at.tzinfo) if known_at.tzinfo else datetime.now()
    )
    age = _seconds_between(reference_now, known_at)
    if age is None or age > float(max_close_age_seconds):
        measured = "unmeasurable against" if age is None else f"{age:.0f}s old, past"
        return RedBarV2StructuralExit(
            **{
                **resolved.as_dict(),
                "status": "CLOSE_STALE",
                "detail": (
                    f"close known at {known_at.isoformat()} is {measured} the "
                    f"{float(max_close_age_seconds):.0f}s bound"
                ),
            }
        )

    entry = _moment(_get(position, "entry_timestamp") or _get(position, "entry_time"))
    if entry is not None:
        after_entry = _seconds_between(known_at, entry)
        if after_entry is None or after_entry < 0.0:
            return RedBarV2StructuralExit(
                **{
                    **resolved.as_dict(),
                    "status": "CLOSE_PRECEDES_ENTRY",
                    "detail": (
                        f"close known at {known_at.isoformat()} is not shown to "
                        f"follow the {entry.isoformat()} entry, so the position "
                        "was opened already knowing it"
                    ),
                }
            )

    if not structure_failed(midpoint, direction=direction, close=close):
        held = "above" if direction == "BULLISH" else "below"
        return RedBarV2StructuralExit(
            **{
                **resolved.as_dict(),
                "detail": (
                    f"{close:,.2f} still {held} the {reference or 'governing'} "
                    f"midpoint {midpoint:,.2f} ({distance:+.2f} pts)"
                ),
            }
        )

    broke = "below" if direction == "BULLISH" else "above"
    return RedBarV2StructuralExit(
        **{
            **resolved.as_dict(),
            "breached": True,
            "status": "BREACHED",
            "detail": (
                f"completed {completed.isoformat()} close {close:,.2f} is "
                f"{broke} the {reference or 'governing'} midpoint "
                f"{midpoint:,.2f} ({distance:+.2f} pts), so the {direction} "
                "position's reason for existing has gone"
            ),
        }
    )


@dataclass(frozen=True)
class RedBarV2StructuralExitResult:
    """What the reference-boundary sweep did across every open row.

    Kept distinct from :class:`RedBarV2StructuralExit`, which is one verdict for
    one position and fires nothing itself. This one closed orders.
    """

    status: str
    reason: str
    completed_close: float | None = None
    exited_orders: int = 0
    errors: tuple[str, ...] = ()


def _exit_reason(
    order: Mapping[str, Any], *, close: float, high: float, low: float
) -> str | None:
    if str(order.get("execution_strategy_source") or "").upper() != "RED_BAR_V2":
        return None
    if str(order.get("status") or "").upper() not in _OPEN_STATUSES:
        return None
    option_type = str(order.get("option_type") or "").upper()
    # A position opened outside the band is on the far side of this boundary from
    # the moment it exists -- a deputy-born CE taken below the red bar low is the
    # standing case -- and closing it on the next completed close would be reading
    # the entry itself as the invalidation. Only skip when the entry level is
    # readable and provably outside; an unrecorded level keeps the older
    # behaviour, so this can only ever prevent an exit, never cause one.
    entry_level = entry_index_level(order)
    if option_type == "PE" and close > high:
        if entry_level is not None and entry_level > high:
            return None
        return "AUTO_REFERENCE_HIGH_INVALIDATION"
    if option_type == "CE" and close < low:
        if entry_level is not None and entry_level < low:
            return None
        return "AUTO_REFERENCE_LOW_INVALIDATION"
    return None


def execute_structural_stop_exits(
    *,
    snapshot: RedBarV2UISnapshot | None,
    completed_1m_close: float | None,
    completed_1m_timestamp: str | None,
    open_orders: Iterable[Mapping[str, Any]],
    close_position: Callable[[str, str], Any],
) -> RedBarV2StructuralExitResult:
    """Exit V2 positions after a completed 1m close beyond reference geometry.

    The backstop described in the module docstring: a full band away from the
    level the trade was taken on, red bar only, and unaware of any deputy. It
    stays because it is the one of the two rules that still acts when no
    governing level has been published for the session.
    """
    if snapshot is None or snapshot.reference_high is None or snapshot.reference_low is None:
        return RedBarV2StructuralExitResult("NO_ACTION", "REFERENCE_GEOMETRY_UNAVAILABLE")
    if completed_1m_close is None or not completed_1m_timestamp:
        return RedBarV2StructuralExitResult("NO_ACTION", "COMPLETED_1M_CLOSE_UNAVAILABLE")
    try:
        reference_date = datetime.fromisoformat(
            str(snapshot.reference_timestamp).replace("Z", "+00:00")
        ).date()
        completed_date = datetime.fromisoformat(
            str(completed_1m_timestamp).replace("Z", "+00:00")
        ).date()
    except (TypeError, ValueError):
        return RedBarV2StructuralExitResult(
            "NO_ACTION", "REFERENCE_SESSION_UNAVAILABLE"
        )
    if reference_date != completed_date:
        return RedBarV2StructuralExitResult(
            "NO_ACTION", "REFERENCE_SESSION_MISMATCH"
        )

    close = float(completed_1m_close)
    high = float(snapshot.reference_high)
    low = float(snapshot.reference_low)
    exited = 0
    errors: list[str] = []
    triggered = False
    for raw_order in open_orders:
        order = dict(raw_order)
        reason = _exit_reason(order, close=close, high=high, low=low)
        if reason is None:
            continue
        triggered = True
        order_id = str(order.get("order_id") or "")
        if not order_id:
            errors.append("MISSING_ORDER_ID")
            continue
        try:
            close_position(order_id, reason)
            exited += 1
        except Exception as exc:
            errors.append(f"{order_id}:{type(exc).__name__}:{exc}")

    if not triggered:
        return RedBarV2StructuralExitResult(
            "NO_ACTION", "REFERENCE_BOUNDARY_HELD", completed_close=close
        )
    return RedBarV2StructuralExitResult(
        status="EXITED" if exited and not errors else "PARTIAL" if exited else "ERROR",
        reason="RED_BAR_V2_STRUCTURAL_STOP",
        completed_close=close,
        exited_orders=exited,
        errors=tuple(errors),
    )


__all__ = [
    "BAR_SECONDS",
    "MAX_CLOSE_AGE_SECONDS",
    "RedBarV2StructuralExit",
    "RedBarV2StructuralExitResult",
    "STRUCTURAL_EXIT_REASON",
    "entry_index_level",
    "evaluate_red_bar_v2_structural_exit",
    "execute_structural_stop_exits",
    "position_direction",
]
