from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import isfinite
from typing import Protocol

from red_bar_lab.domain.red_bar_v2 import OptionSide


class PaperMarketDataError(Exception):
    pass


class PaperMarketDataConfigurationError(PaperMarketDataError):
    pass


class PaperMarketDataUnavailableError(PaperMarketDataError):
    pass


class PaperMarketDataStaleError(PaperMarketDataUnavailableError):
    pass


class PaperMarketDataCorruptionError(PaperMarketDataError):
    pass


class PaperMarketDataRateLimitError(PaperMarketDataError):
    pass


class PaperMarketDataAuthenticationError(PaperMarketDataError):
    pass


def _text(name: str, value: object) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def finite_positive_number(name: str, value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite positive number")
    number = float(value)
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return number


def finite_non_negative_number(name: str, value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite non-negative number")
    number = float(value)
    if not isfinite(number) or number < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return number


def _aware(name: str, value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class PaperUnderlyingQuote:
    instrument_key: str
    underlying: str
    last_price: float
    quote_timestamp: datetime
    provider: str

    def __post_init__(self) -> None:
        _text("instrument_key", self.instrument_key)
        _text("underlying", self.underlying)
        finite_positive_number("last_price", self.last_price)
        _aware("quote_timestamp", self.quote_timestamp)
        _text("provider", self.provider)


@dataclass(frozen=True, slots=True)
class PaperMarketQuote:
    instrument_key: str
    instrument_token: int | str
    last_price: float
    bid_price: float | None
    ask_price: float | None
    quote_timestamp: datetime
    provider: str

    def __post_init__(self) -> None:
        _text("instrument_key", self.instrument_key)
        if type(self.instrument_token) not in (int, str) or isinstance(self.instrument_token, bool):
            raise ValueError("instrument_token must be int or str")
        if type(self.instrument_token) is int and self.instrument_token <= 0:
            raise ValueError("instrument_token must be positive")
        if type(self.instrument_token) is str and not self.instrument_token.strip():
            raise ValueError("instrument_token must be non-empty")
        finite_positive_number("last_price", self.last_price)
        for name, value in (("bid_price", self.bid_price), ("ask_price", self.ask_price)):
            if value is not None:
                finite_positive_number(name, value)
        if (
            self.bid_price is not None
            and self.ask_price is not None
            and float(self.bid_price) > float(self.ask_price)
        ):
            raise ValueError("bid_price cannot exceed ask_price")
        _aware("quote_timestamp", self.quote_timestamp)
        _text("provider", self.provider)


@dataclass(frozen=True, slots=True)
class PaperOptionInstrument:
    instrument_key: str
    instrument_token: int | str
    trading_symbol: str
    underlying: str
    expiry: date
    strike: float
    option_side: OptionSide
    lot_size: int
    provider: str

    def __post_init__(self) -> None:
        _text("instrument_key", self.instrument_key)
        if type(self.instrument_token) not in (int, str) or isinstance(self.instrument_token, bool):
            raise ValueError("instrument_token must be int or str")
        if type(self.instrument_token) is int and self.instrument_token <= 0:
            raise ValueError("instrument_token must be positive")
        if type(self.instrument_token) is str and not self.instrument_token.strip():
            raise ValueError("instrument_token must be non-empty")
        _text("trading_symbol", self.trading_symbol)
        _text("underlying", self.underlying)
        if type(self.expiry) is not date:
            raise ValueError("expiry must be date")
        finite_positive_number("strike", self.strike)
        if type(self.option_side) is not OptionSide:
            raise ValueError("option_side must be OptionSide")
        if type(self.lot_size) is not int or self.lot_size <= 0:
            raise ValueError("lot_size must be a positive integer")
        _text("provider", self.provider)


class PaperCanaryMarketData(Protocol):
    @property
    def provider_name(self) -> str: ...

    def underlying_quote(
        self,
        *,
        underlying: str,
        evaluated_at: datetime,
    ) -> PaperUnderlyingQuote: ...

    def option_instruments(
        self,
        *,
        underlying: str,
        evaluated_at: datetime,
    ) -> tuple[PaperOptionInstrument, ...]: ...

    def quotes(
        self,
        *,
        instrument_keys: tuple[str, ...],
        evaluated_at: datetime,
    ) -> tuple[PaperMarketQuote, ...]: ...


def verify_timestamp_freshness(
    *,
    timestamp: datetime,
    evaluated_at: datetime,
    maximum_age_seconds: float,
    future_tolerance_seconds: float = 2.0,
) -> None:
    _aware("timestamp", timestamp)
    _aware("evaluated_at", evaluated_at)
    maximum_age = finite_positive_number(
        "maximum_age_seconds",
        maximum_age_seconds,
    )
    future_tolerance = finite_non_negative_number(
        "future_tolerance_seconds",
        future_tolerance_seconds,
    )
    age = (
        evaluated_at.astimezone(timezone.utc)
        - timestamp.astimezone(timezone.utc)
    ).total_seconds()
    if not isfinite(age):
        raise PaperMarketDataCorruptionError(
            "provider evidence age is not finite"
        )
    if age < -future_tolerance:
        raise PaperMarketDataCorruptionError(
            "provider timestamp is in the future"
        )
    if age > maximum_age:
        raise PaperMarketDataStaleError("provider evidence is stale")


def verify_quote_freshness(
    quote: PaperMarketQuote,
    *,
    evaluated_at: datetime,
    maximum_age_seconds: float,
    future_tolerance_seconds: float = 2.0,
) -> None:
    verify_timestamp_freshness(
        timestamp=quote.quote_timestamp,
        evaluated_at=evaluated_at,
        maximum_age_seconds=maximum_age_seconds,
        future_tolerance_seconds=future_tolerance_seconds,
    )
