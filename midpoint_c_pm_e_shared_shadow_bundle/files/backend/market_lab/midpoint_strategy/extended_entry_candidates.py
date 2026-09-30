"""C and PM_E entry state machines using completed one-minute evidence only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    "WAITING_FIRST_BREAK",
    "WAITING_MIDPOINT_RECROSS",
    "WAITING_OPPOSITE_BREAK",
    "CONSUMED",
]


@dataclass
class PMEReversalCandidate:
    """Frozen 12:45-13:14 false-break reversal entry candidate."""

    session_date: str
    reference_start: datetime
    reference_end: datetime
    high: float
    low: float
    state: PMState = "WAITING_FIRST_BREAK"
    first_break_timestamp: datetime | None = None
    first_break_direction: str | None = None
    midpoint_recross_timestamp: datetime | None = None

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2.0

    def reversal_reference(self) -> ReferenceStructure:
        if self.first_break_direction not in {"BULLISH", "BEARISH"}:
            raise ValueError("PM reversal direction is not known")
        reversal = (
            "BEARISH" if self.first_break_direction == "BULLISH" else "BULLISH"
        )
        return ReferenceStructure(
            session_date=self.session_date,
            reference_type="RED" if reversal == "BEARISH" else "GREEN",
            start_timestamp=self.reference_start.isoformat(),
            end_timestamp=self.reference_end.isoformat(),
            high=self.high,
            low=self.low,
        )

    def observe(
        self, *, timestamp: datetime, previous_close: float, close: float
    ) -> list[EntryAction]:
        if timestamp <= self.reference_end or self.state == "CONSUMED":
            return []
        actions: list[EntryAction] = []
        if self.state == "WAITING_FIRST_BREAK":
            direction = None
            if close > self.high:
                direction = "BULLISH"
            elif close < self.low:
                direction = "BEARISH"
            if direction is None:
                return actions
            self.first_break_timestamp = timestamp
            self.first_break_direction = direction
            self.state = "WAITING_MIDPOINT_RECROSS"
            actions.append(
                EntryAction(
                    "PM_FALSE_BREAK_OBSERVED",
                    timestamp,
                    direction,
                    "FIRST_COMPLETED_CLOSE_OUTSIDE_PM_BOUNDARY",
                )
            )
            return actions

        if self.state == "WAITING_MIDPOINT_RECROSS":
            recrossed = (
                close < self.midpoint
                if self.first_break_direction == "BULLISH"
                else close > self.midpoint
            )
            if recrossed:
                self.midpoint_recross_timestamp = timestamp
                self.state = "WAITING_OPPOSITE_BREAK"
                actions.append(
                    EntryAction(
                        "PM_MIDPOINT_RECROSS_ARMED",
                        timestamp,
                        (
                            "BEARISH"
                            if self.first_break_direction == "BULLISH"
                            else "BULLISH"
                        ),
                        "COMPLETED_CLOSE_RECROSSED_PM_MIDPOINT",
                    )
                )
            return actions

        reversal = (
            "BEARISH" if self.first_break_direction == "BULLISH" else "BULLISH"
        )
        fresh = (
            close < self.low and previous_close >= self.low
            if reversal == "BEARISH"
            else close > self.high and previous_close <= self.high
        )
        if fresh and timestamp > self.midpoint_recross_timestamp:
            self.state = "CONSUMED"
            actions.append(
                EntryAction(
                    "PM_E_FRESH_BOUNDARY_BREAK",
                    timestamp,
                    reversal,
                    "LATER_COMPLETED_CLOSE_FRESHLY_BROKE_OPPOSITE_PM_BOUNDARY",
                )
            )
        return actions
