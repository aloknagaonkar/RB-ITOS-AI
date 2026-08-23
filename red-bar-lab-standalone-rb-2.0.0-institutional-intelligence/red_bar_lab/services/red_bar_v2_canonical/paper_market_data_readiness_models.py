from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from hashlib import sha256
from math import isfinite

from red_bar_lab.domain.red_bar_v2 import OptionSide

SCHEMA_VERSION = "1.0"


class MarketDataReadinessStatus(str, Enum):
    DISABLED = "DISABLED"
    CONFIGURATION_INVALID = "CONFIGURATION_INVALID"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    DATA_CORRUPT = "DATA_CORRUPT"
    SPOT_UNAVAILABLE = "SPOT_UNAVAILABLE"
    CHAIN_UNAVAILABLE = "CHAIN_UNAVAILABLE"
    CHAIN_COVERAGE_INCOMPLETE = "CHAIN_COVERAGE_INCOMPLETE"
    QUOTES_UNAVAILABLE = "QUOTES_UNAVAILABLE"
    QUOTES_STALE = "QUOTES_STALE"
    QUOTE_QUALITY_PARTIAL = "QUOTE_QUALITY_PARTIAL"
    READY = "READY"


class ContractReadinessStatus(str, Enum):
    READY = "READY"
    QUOTE_MISSING = "QUOTE_MISSING"
    QUOTE_STALE = "QUOTE_STALE"
    BID_ASK_MISSING = "BID_ASK_MISSING"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    IDENTITY_INVALID = "IDENTITY_INVALID"


def _text(name: str, value: object) -> str:
    if type(value) is not str or not value.strip(): raise ValueError(f"{name} must be non-empty")
    return value


def _aware(name: str, value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None: raise ValueError(f"{name} must be timezone-aware")
    return value


def _finite_optional(name: str, value: object | None, *, positive: bool = True) -> float | None:
    if value is None: return None
    if type(value) not in (int, float): raise ValueError(f"{name} must be finite")
    number = float(value)
    if not isfinite(number) or (positive and number <= 0) or (not positive and number < 0): raise ValueError(f"{name} must be finite")
    return number


def build_probe_id(*, provider: str, underlying: str, evaluated_at: datetime, expiry: date | None, atm_strike: float | None, schema_version: str = SCHEMA_VERSION) -> str:
    evaluated = _aware("evaluated_at", evaluated_at).astimezone(timezone.utc).isoformat()
    payload = "|".join((provider, underlying, evaluated, expiry.isoformat() if expiry else "", "" if atm_strike is None else f"{float(atm_strike):.10g}", schema_version))
    return "MDR-" + sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class MarketDataReadinessPolicy:
    max_quote_age_seconds: float = 30.0
    strike_steps: int = 4
    min_ce_coverage: int = 9
    min_pe_coverage: int = 9
    maximum_spread_percentage: float = 10.0

    def __post_init__(self) -> None:
        _finite_optional("max_quote_age_seconds", self.max_quote_age_seconds)
        _finite_optional("maximum_spread_percentage", self.maximum_spread_percentage, positive=False)
        for name in ("strike_steps", "min_ce_coverage", "min_pe_coverage"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0: raise ValueError(f"{name} must be positive integer")


@dataclass(frozen=True, slots=True)
class ContractReadinessEvidence:
    instrument_key: str
    trading_symbol: str
    option_side: OptionSide
    strike: float
    expiry: date
    moneyness: str
    distance_steps: int
    lot_size: int
    last_price: float | None
    bid_price: float | None
    ask_price: float | None
    spread_percentage: float | None
    quote_timestamp: datetime | None
    status: ContractReadinessStatus
    reason_code: str

    def __post_init__(self) -> None:
        _text("instrument_key", self.instrument_key); _text("trading_symbol", self.trading_symbol); _text("moneyness", self.moneyness); _text("reason_code", self.reason_code)
        if type(self.option_side) is not OptionSide: raise ValueError("option_side invalid")
        _finite_optional("strike", self.strike)
        if type(self.expiry) is not date: raise ValueError("expiry invalid")
        if type(self.distance_steps) is not int: raise ValueError("distance_steps invalid")
        if type(self.lot_size) is not int or self.lot_size <= 0: raise ValueError("lot_size invalid")
        for name in ("last_price", "bid_price", "ask_price"): _finite_optional(name, getattr(self, name))
        _finite_optional("spread_percentage", self.spread_percentage, positive=False)
        if self.quote_timestamp is not None: _aware("quote_timestamp", self.quote_timestamp)
        if type(self.status) is not ContractReadinessStatus: raise ValueError("status invalid")


@dataclass(frozen=True, slots=True)
class MarketDataReadinessReport:
    probe_id: str
    provider: str
    underlying: str
    underlying_instrument_key: str | None
    evaluated_at: datetime
    spot_price: float | None
    spot_timestamp: datetime | None
    expiry: date | None
    strike_interval: float | None
    atm_strike: float | None
    expected_contract_count: int
    observed_contract_count: int
    ready_contract_count: int
    ce_coverage: int
    pe_coverage: int
    status: MarketDataReadinessStatus
    reason_code: str
    contracts: tuple[ContractReadinessEvidence, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _text("provider", self.provider); _text("underlying", self.underlying); _text("reason_code", self.reason_code)
        if self.underlying_instrument_key is not None: _text("underlying_instrument_key", self.underlying_instrument_key)
        _aware("evaluated_at", self.evaluated_at)
        for name in ("spot_price", "strike_interval", "atm_strike"): _finite_optional(name, getattr(self, name))
        if self.spot_timestamp is not None: _aware("spot_timestamp", self.spot_timestamp)
        if self.expiry is not None and type(self.expiry) is not date: raise ValueError("expiry invalid")
        for name in ("expected_contract_count", "observed_contract_count", "ready_contract_count", "ce_coverage", "pe_coverage"):
            value = getattr(self, name)
            if type(value) is not int or value < 0: raise ValueError(f"{name} invalid")
        if self.observed_contract_count > self.expected_contract_count or self.ready_contract_count > self.observed_contract_count: raise ValueError("count ordering invalid")
        if len(self.contracts) > 18: raise ValueError("contracts exceeds 18")
        if type(self.status) is not MarketDataReadinessStatus: raise ValueError("status invalid")
        expected_id = build_probe_id(provider=self.provider, underlying=self.underlying, evaluated_at=self.evaluated_at, expiry=self.expiry, atm_strike=self.atm_strike, schema_version=self.schema_version)
        if self.probe_id != expected_id: raise ValueError("probe_id invalid")
        if self.status is MarketDataReadinessStatus.READY:
            if self.expected_contract_count != self.observed_contract_count or self.ready_contract_count != self.expected_contract_count or self.spot_price is None or self.spot_timestamp is None: raise ValueError("READY evidence incomplete")
