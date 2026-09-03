"""The structural exit for a live Red Bar V2 position.

It asks one question -- *has the level this trade was taken on failed?* -- and it
is the rule from the agreed table: *exit any open position on a completed
1-minute close against the governing level*. It is called per open row from
``automation.monitor_and_exit`` and its verdict is ranked inside
``PaperExitEngine``, so it is weighed against the premium protections rather than
firing beside them.

Why it has to exist at all: for a V2 row the configured entry-time premium stop
is deliberately excluded (``red_bar_v2_external_initial_exit`` in the exit
engine) on the grounds that V2 carries its own initial-loss authority. This is
that authority, at the distance the strategy actually reasons about. Together
with the earned premium stop and EOD it is the whole of a V2 row's exit set.

It replaced two rules that used to run beside it in ``paper_monitor``, both now
deleted. One was a reference-**boundary** sweep: it exited a PE on a close above
the red bar high and a CE on a close below the low, so price had to clear the
whole band, and it knew nothing about the working reference -- a deputy-born
position was judged against a band it was never taken on. The other was a
completed-candle RSI threshold exit, from a gate the strategy has since retired.
The midpoint rule subsumes the first (any close beyond the high is also beyond
the midpoint) and, once every open row carries a stamped entry level, does so on
the deputy's path too -- which is what made the deletion safe.

Four things make it safe to act on:

*   **The level is the entry's own, not the session's.** ``governing_level``
    prefers the reference stamped on the row at admission
    (``signal_attempts.governing_reference`` / ``governing_midpoint``, written by
    the paper signal bridge) over the snapshot's live block. The distinction is
    the whole reason a deputy-born position can be exited at all: the replay
    retires a deputy the instant it produces an entry, so the session's governing
    level for a WORKING position is a red bar it opened on the far side of.
*   **The close comes from the replay's ``rule_state``, not from an event.**
    ``index_close`` on the snapshot is read off the latest event, and events are
    emitted only on candidates, admissions, upgrades and closures -- so it
    freezes for as long as nothing happens, which on 2026-09-03 was 56 minutes.
    ``governing_close`` advances every candle.
*   **The direction is the position's own**, taken from the option it holds. The
    snapshot's ``direction`` field is the last *admitted* direction and is
    exactly the value that went stale; a CE row is long the index whatever the
    strategy currently thinks.
*   **A close the entry already knew about cannot invalidate the entry.** The
    close is only consulted if it became known after the order was placed, and a
    level the entry was already on the failing side of is refused outright --
    which is what protects a row from before the stamping existed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from red_bar_lab.execution.execution_policy import RED_BAR_V2_STRATEGY_SOURCE
from red_bar_lab.strategy.red_bar_v2_working_reference import structure_failed

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
    level_source: str = "SESSION"
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


def governing_level(
    position: Mapping[str, Any],
    signal: Mapping[str, Any] | None = None,
    snapshot: Any | None = None,
) -> tuple[float | None, str | None, str]:
    """The level this position is answerable to, and where that level came from.

    The order matters. A level recorded on the row itself was stamped at
    admission and is the level the trade was actually taken on. The snapshot's
    ``governing_*`` block is whichever level governs *now* -- which for a
    deputy-born position is a red bar it opened on the far side of, because the
    replay retires a deputy the instant it produces an entry. Preferring the
    recorded level is what gives a WORKING position a structural exit at all;
    without it the entry guard below correctly declines on every cycle and the
    position has no index-level authority whatsoever.

    Rows written before the columns existed carry nothing and fall back to the
    session level, which is exactly the previous behaviour.
    """
    for source in (position, signal):
        recorded = _float(_get(source, "governing_midpoint"))
        if recorded is not None and recorded > 0.0:
            name = _get(source, "governing_reference")
            return recorded, (str(name) if name else None), "ENTRY"
    return (
        _float(_get(snapshot, "governing_midpoint")),
        _get(snapshot, "governing_reference"),
        "SESSION",
    )


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
    caller does one snapshot read per cycle and asks this per open row. The level
    is resolved by ``governing_level`` -- the row's own stamped reference where it
    has one, the session's otherwise -- and the close always comes from the
    snapshot, since only the snapshot advances every minute.

    A non-V2 row, no level to judge against, an unreadable direction, a level the
    entry was already on the failing side of, an unrecorded entry level, a stale
    close, or a close the entry already knew about all return ``breached=False``
    with a status saying which -- never an exit on a guess.
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

    midpoint, reference, level_source = governing_level(position, signal, snapshot)
    close = _float(_get(snapshot, "governing_close"))
    close_stamp = _get(snapshot, "governing_close_timestamp")
    if midpoint is None or close is None or close_stamp is None:
        return RedBarV2StructuralExit(
            breached=False,
            status="LEVEL_UNAVAILABLE",
            governing_reference=reference,
            governing_midpoint=midpoint,
            level_source=level_source,
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
            level_source=level_source,
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
        level_source=level_source,
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
    # never justified the entry, so it cannot invalidate it. With the entry's own
    # level stamped on the row this is a no-op on every path -- admission required
    # the close to be on the winning side of whichever reference was in force --
    # and it stays as the guard that makes that claim checkable rather than
    # assumed. It is load-bearing for the ``SESSION`` fallback: a row written
    # before the stamping existed publishes a deputy-born position against the red
    # bar midpoint, and without this guard would be closed on its very next
    # completed close.
    #
    # Unreadable entry level refuses rather than proceeds. The asymmetry is
    # deliberate: acting on an unverified level risks closing a sound position
    # instantly, while declining leaves the premium protections in force.
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


__all__ = [
    "BAR_SECONDS",
    "MAX_CLOSE_AGE_SECONDS",
    "RedBarV2StructuralExit",
    "STRUCTURAL_EXIT_REASON",
    "entry_index_level",
    "evaluate_red_bar_v2_structural_exit",
    "governing_level",
    "position_direction",
]
