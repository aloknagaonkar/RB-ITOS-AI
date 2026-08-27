from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Protocol

from .models import (
    PcrBias,
    PcrDirectionEvidence,
    PcrMarketDirection,
)


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
    def direction_for_bias(classification: PcrBias) -> PcrMarketDirection:
        return {
            PcrBias.BEARISH: PcrMarketDirection.BEARISH,
            PcrBias.NEUTRAL: PcrMarketDirection.NEUTRAL,
            PcrBias.BULLISH: PcrMarketDirection.BULLISH,
            PcrBias.STRONGLY_BULLISH: PcrMarketDirection.BULLISH,
            PcrBias.UNAVAILABLE: PcrMarketDirection.UNAVAILABLE,
        }[classification]

    def direction_evidence(
        self,
        pcr: float | None,
        *,
        classification: PcrBias | None = None,
    ) -> PcrDirectionEvidence:
        if pcr is None:
            bias = PcrBias.UNAVAILABLE
            return PcrDirectionEvidence(
                direction=PcrMarketDirection.UNAVAILABLE,
                classification=bias,
                pcr=None,
                lower_bound=None,
                upper_bound=None,
                reason_code="PCR_UNAVAILABLE",
                explanation="PCR could not be calculated.",
            )
        bias = classification or self.classify(pcr)
        direction = self.direction_for_bias(bias)
        if bias is PcrBias.BEARISH:
            return PcrDirectionEvidence(
                direction, bias, pcr, None, self.bearish_below,
                "PCR_BELOW_BEARISH_THRESHOLD",
                f"PCR {pcr:.3f} is below {self.bearish_below:.2f}.",
            )
        if bias is PcrBias.NEUTRAL:
            return PcrDirectionEvidence(
                direction, bias, pcr, self.bearish_below, self.bullish_from,
                "PCR_WITHIN_NEUTRAL_RANGE",
                f"PCR {pcr:.3f} is between {self.bearish_below:.2f} and {self.bullish_from:.2f}.",
            )
        if bias is PcrBias.BULLISH:
            return PcrDirectionEvidence(
                direction, bias, pcr, self.bullish_from, self.strongly_bullish_above,
                "PCR_WITHIN_BULLISH_RANGE",
                f"PCR {pcr:.3f} is between {self.bullish_from:.2f} and {self.strongly_bullish_above:.2f}.",
            )
        return PcrDirectionEvidence(
            direction, bias, pcr, self.strongly_bullish_above, None,
            "PCR_ABOVE_STRONG_BULLISH_THRESHOLD",
            f"PCR {pcr:.3f} is above {self.strongly_bullish_above:.2f}.",
        )

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
        if steps < self.minimum_window_steps:
            raise ValueError("SESSION_POSITION_UNAVAILABLE")
        # Monthly index and stock options can be many sessions from expiry.
        # Retain bounded ATM coverage instead of rejecting otherwise valid
        # option-chain evidence merely because the expiry is farther away.
        return min(steps, self.maximum_window_steps)

    @staticmethod
    def expected_contract_count(window_steps: int) -> int:
        if type(window_steps) is not int or not 1 <= window_steps <= 5:
            raise ValueError("window_steps invalid")
        return ((2 * window_steps) + 1) * 2
