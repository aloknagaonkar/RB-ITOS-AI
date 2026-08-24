from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Protocol

from .models import PcrBias


class ExchangeSessionCalendar(Protocol):
    source_name: str
    verified: bool

    def sessions_between(self, start: date, end: date) -> tuple[date, ...]: ...


@dataclass(frozen=True, slots=True)
class StaticExchangeSessionCalendar:
    holidays: frozenset[date] = frozenset()
    source_name: str = "INJECTED_VERIFIED_CALENDAR"
    verified: bool = True

    def sessions_between(self, start: date, end: date) -> tuple[date, ...]:
        if not self.verified:
            raise ValueError("SESSION_POSITION_UNAVAILABLE")
        if end < start:
            return ()
        sessions: list[date] = []
        current = start
        while current <= end:
            if current.weekday() < 5 and current not in self.holidays:
                sessions.append(current)
            current += timedelta(days=1)
        return tuple(sessions)


@dataclass(frozen=True, slots=True)
class MarketTrendResearchPolicy:
    bearish_below: float = 0.70
    bullish_from: float = 1.25
    strongly_bullish_above: float = 1.50
    maximum_source_age_seconds: float = 30.0
    hard_deadline_seconds: float = 2.0
    reference_start: time = time(9, 8)
    reference_cutoff: time = time(9, 14, 59)
    oi_baseline_start: time = time(9, 15)
    minimum_window_steps: int = 1
    maximum_window_steps: int = 5

    def __post_init__(self) -> None:
        if not 0 < self.bearish_below < self.bullish_from:
            raise ValueError("PCR thresholds invalid")
        if self.strongly_bullish_above < self.bullish_from:
            raise ValueError("PCR thresholds invalid")
        if self.maximum_source_age_seconds <= 0:
            raise ValueError("maximum_source_age_seconds invalid")
        if self.hard_deadline_seconds <= 0:
            raise ValueError("hard_deadline_seconds invalid")
        if self.reference_cutoff < self.reference_start:
            raise ValueError("reference window invalid")
        if self.oi_baseline_start <= self.reference_start:
            raise ValueError("OI baseline start invalid")

    def classify(self, pcr: float) -> PcrBias:
        if pcr < self.bearish_below:
            return PcrBias.BEARISH
        if pcr < self.bullish_from:
            return PcrBias.NEUTRAL
        if pcr <= self.strongly_bullish_above:
            return PcrBias.BULLISH
        return PcrBias.STRONGLY_BULLISH

    @staticmethod
    def calendar_source(calendar: ExchangeSessionCalendar) -> str:
        if not getattr(calendar, "verified", False):
            raise ValueError("SESSION_POSITION_UNAVAILABLE")
        source = str(getattr(calendar, "source_name", "")).strip()
        if not source:
            raise ValueError("SESSION_POSITION_UNAVAILABLE")
        return source

    def sessions_to_expiry(
        self,
        trading_date: date,
        expiry: date,
        calendar: ExchangeSessionCalendar,
    ) -> int:
        self.calendar_source(calendar)
        sessions = calendar.sessions_between(trading_date, expiry)
        if not sessions or sessions[0] != trading_date or sessions[-1] != expiry:
            raise ValueError("SESSION_POSITION_UNAVAILABLE")
        return len(sessions) - 1

    def window_steps(
        self,
        trading_date: date,
        expiry: date,
        calendar: ExchangeSessionCalendar,
    ) -> int:
        remaining = self.sessions_to_expiry(trading_date, expiry, calendar)
        steps = remaining + 1
        if steps < self.minimum_window_steps or steps > self.maximum_window_steps:
            raise ValueError("SESSION_POSITION_UNAVAILABLE")
        return steps

    @staticmethod
    def expected_contract_count(window_steps: int) -> int:
        if type(window_steps) is not int or not 1 <= window_steps <= 5:
            raise ValueError("window_steps invalid")
        return ((2 * window_steps) + 1) * 2
