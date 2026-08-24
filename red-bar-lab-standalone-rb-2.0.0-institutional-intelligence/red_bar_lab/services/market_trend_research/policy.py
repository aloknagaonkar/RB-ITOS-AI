from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from .models import PcrBias


class ExchangeSessionCalendar(Protocol):
    def sessions_between(self, start: date, end: date) -> tuple[date, ...]: ...


@dataclass(frozen=True, slots=True)
class MarketTrendResearchPolicy:
    bearish_below: float = 0.70
    bullish_from: float = 1.25
    strongly_bullish_above: float = 1.50
    maximum_source_age_seconds: float = 30.0
    hard_deadline_seconds: float = 2.0
    anchor_hour: int = 9
    anchor_minute: int = 16
    minimum_window_steps: int = 1
    maximum_window_steps: int = 5

    def classify(self, pcr: float) -> PcrBias:
        if pcr < self.bearish_below: return PcrBias.BEARISH
        if pcr < self.bullish_from: return PcrBias.NEUTRAL
        if pcr <= self.strongly_bullish_above: return PcrBias.BULLISH
        return PcrBias.STRONGLY_BULLISH

    def sessions_to_expiry(self, trading_date: date, expiry: date, calendar: ExchangeSessionCalendar) -> int:
        sessions = calendar.sessions_between(trading_date, expiry)
        if not sessions or sessions[0] != trading_date or sessions[-1] != expiry:
            raise ValueError("SESSION_POSITION_UNAVAILABLE")
        return len(sessions) - 1

    def window_steps(self, trading_date: date, expiry: date, calendar: ExchangeSessionCalendar) -> int:
        remaining = self.sessions_to_expiry(trading_date, expiry, calendar)
        steps = remaining + 1
        if steps < self.minimum_window_steps or steps > self.maximum_window_steps:
            raise ValueError("SESSION_POSITION_UNAVAILABLE")
        return steps

    @staticmethod
    def expected_contract_count(window_steps: int) -> int:
        if type(window_steps) is not int or window_steps < 1 or window_steps > 5:
            raise ValueError("window_steps invalid")
        return ((2 * window_steps) + 1) * 2
