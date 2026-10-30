"""C and PM_E entry state machines using completed one-minute evidence only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Literal

from .structure import ReferenceStructure, boundary_broken


@dataclass(frozen=True)
class EntryAction:
    event_type: str
    timestamp: datetime
    direction: str | None = None
    reason: str | None = None


@dataclass
class CRearmCandidate:
    """One-shot C re-arm for a completed B/E origin trade."""

    reference: ReferenceStructure
    origin_family: str
    origin_entry_timestamp: datetime
    midpoint_touch_timestamp: datetime | None = None
    origin_closed_timestamp: datetime | None = None
    consumed: bool = False

    def observe_active_bar(
        self, *, timestamp: datetime, high: float, low: float
    ) -> EntryAction | None:
        if self.consumed or self.midpoint_touch_timestamp is not None:
            return None
        if timestamp <= self.origin_entry_timestamp:
            return None
        if low <= self.reference.midpoint <= high:
            self.midpoint_touch_timestamp = timestamp
            return EntryAction(
                "C_MIDPOINT_TOUCH_ARMED",
                timestamp,
                self.reference.direction,
                "INTRABAR_TOUCH_OF_ORIGINAL_MIDPOINT",
            )
        return None

    def mark_origin_closed(self, timestamp: datetime) -> None:
        if self.origin_closed_timestamp is None:
            self.origin_closed_timestamp = timestamp

    def observe_after_close(
        self, *, timestamp: datetime, previous_close: float, close: float
    ) -> EntryAction | None:
        if self.consumed:
            return None
        if self.midpoint_touch_timestamp is None or self.origin_closed_timestamp is None:
            return None
        if timestamp <= max(
            self.midpoint_touch_timestamp, self.origin_closed_timestamp
        ):
            return None
        fresh = boundary_broken(self.reference, close) and not boundary_broken(
            self.reference, previous_close
        )
        if not fresh:
            return None
        self.consumed = True
        return EntryAction(
            "C_FRESH_BOUNDARY_BREAK",
            timestamp,
            self.reference.direction,
            "LATER_COMPLETED_CLOSE_FRESHLY_BROKE_ORIGINAL_BOUNDARY",
        )


PMState = Literal[
    "WAITING_MIDPOINT_BREAK",
    "WAITING_BOUNDARY_BREAK",
    "CONSUMED",
    "EXPIRED",
]


@dataclass
class PMMidpointBECandidate:
    """12:45-13:14 reference using canonical Midpoint B/E sequencing.

    The first completed close on either side of the PM midpoint establishes
    direction.  A same-direction boundary close then invokes the shared B/E
    owner classifier.  The candidate itself is deliberately owner-agnostic.
    """

    session_date: str
    reference_start: datetime
    reference_end: datetime
    high: float
    low: float
    state: PMState = "WAITING_MIDPOINT_BREAK"
    direction: str | None = None
    bearish_midpoint_break_timestamp: datetime | None = None
    bullish_midpoint_break_timestamp: datetime | None = None
    boundary_break_timestamp: datetime | None = None

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2.0

    def directional_reference(
        self, direction: str | None = None
    ) -> ReferenceStructure:
        selected = direction or self.direction
        if selected not in {"BULLISH", "BEARISH"}:
            raise ValueError("PM midpoint direction is not known")
        return ReferenceStructure(
            session_date=self.session_date,
            reference_type="RED" if selected == "BEARISH" else "GREEN",
            start_timestamp=self.reference_start.isoformat(),
            end_timestamp=self.reference_end.isoformat(),
            high=self.high,
            low=self.low,
        )

    def observe(
        self, *, timestamp: datetime, previous_close: float, close: float
    ) -> list[EntryAction]:
        del previous_close  # Direction uses the same non-fresh midpoint rule as B/E.
        if timestamp <= self.reference_end or self.state in {"CONSUMED", "EXPIRED"}:
            return []
        actions: list[EntryAction] = []
        if timestamp.time() >= time(15, 15):
            self.state = "EXPIRED"
            actions.append(
                EntryAction(
                    "PM_ENTRY_WINDOW_EXPIRED",
                    timestamp,
                    self.direction,
                    "NO_PM_ENTRY_AT_OR_AFTER_1515",
                )
            )
            return actions

        if close < self.midpoint and self.bearish_midpoint_break_timestamp is None:
            self.bearish_midpoint_break_timestamp = timestamp
            self.state = "WAITING_BOUNDARY_BREAK"
            actions.append(
                EntryAction(
                    "PM_MIDPOINT_BREAK",
                    timestamp,
                    "BEARISH",
                    "COMPLETED_CLOSE_BEYOND_PM_MIDPOINT",
                )
            )
        elif close > self.midpoint and self.bullish_midpoint_break_timestamp is None:
            self.bullish_midpoint_break_timestamp = timestamp
            self.state = "WAITING_BOUNDARY_BREAK"
            actions.append(
                EntryAction(
                    "PM_MIDPOINT_BREAK",
                    timestamp,
                    "BULLISH",
                    "COMPLETED_CLOSE_BEYOND_PM_MIDPOINT",
                )
            )

        boundary_direction = None
        if close < self.low and self.bearish_midpoint_break_timestamp is not None:
            boundary_direction = "BEARISH"
        elif close > self.high and self.bullish_midpoint_break_timestamp is not None:
            boundary_direction = "BULLISH"
        if boundary_direction is not None:
            self.direction = boundary_direction
            self.boundary_break_timestamp = timestamp
            self.state = "CONSUMED"
            actions.append(
                EntryAction(
                    "PM_BOUNDARY_BREAK",
                    timestamp,
                    boundary_direction,
                    "COMPLETED_CLOSE_BEYOND_PM_BOUNDARY",
                )
            )
        return actions


# Compatibility import for older research runners. Semantics intentionally
# follow the revised midpoint-first PM B/E model.
PMEReversalCandidate = PMMidpointBECandidate
