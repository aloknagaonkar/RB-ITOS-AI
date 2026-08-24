from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from hashlib import sha256
from math import isfinite
import re

from red_bar_lab.domain.red_bar_v2 import OptionSide

SCHEMA_VERSION = "1.1"


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


class MarketDataReadinessStage(str, Enum):
    STARTUP = "STARTUP"
    UNDERLYING_QUOTE_COLLECTION = "UNDERLYING_QUOTE_COLLECTION"
    UNDERLYING_QUOTE_VALIDATION = "UNDERLYING_QUOTE_VALIDATION"
    OPTION_CONTRACT_COLLECTION = "OPTION_CONTRACT_COLLECTION"
    OPTION_CONTRACT_NORMALIZATION = "OPTION_CONTRACT_NORMALIZATION"
    COMMON_EXPIRY_SELECTION = "COMMON_EXPIRY_SELECTION"
    STRIKE_INTERVAL_DETECTION = "STRIKE_INTERVAL_DETECTION"
    ATM_WINDOW_CONSTRUCTION = "ATM_WINDOW_CONSTRUCTION"
    OPTION_QUOTE_COLLECTION = "OPTION_QUOTE_COLLECTION"
    OPTION_QUOTE_CORRELATION = "OPTION_QUOTE_CORRELATION"
    QUOTE_FRESHNESS_VALIDATION = "QUOTE_FRESHNESS_VALIDATION"
    QUOTE_QUALITY_VALIDATION = "QUOTE_QUALITY_VALIDATION"
    COMPLETED = "COMPLETED"


class ContractReadinessStatus(str, Enum):
    READY = "READY"
    QUOTE_MISSING = "QUOTE_MISSING"
    QUOTE_STALE = "QUOTE_STALE"
    BID_ASK_MISSING = "BID_ASK_MISSING"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    IDENTITY_INVALID = "IDENTITY_INVALID"


ALLOWED_DIAGNOSTIC_REASONS = frozenset({
    "UNDERLYING_QUOTE_UNAVAILABLE", "UNDERLYING_IDENTITY_MISMATCH",
    "UNDERLYING_TIMESTAMP_INVALID", "OPTION_CONTRACT_REQUEST_FAILED",
    "OPTION_CONTRACT_RESPONSE_MALFORMED", "OPTION_CONTRACT_ROW_MALFORMED",
    "CONTRACT_IDENTITY_MISSING", "DUPLICATE_CONTRACT_IDENTITY",
    "AMBIGUOUS_CONTRACT_TOKEN", "OPTION_SIDE_UNSUPPORTED",
    "OPTION_EXPIRY_INVALID", "OPTION_STRIKE_INVALID",
    "OPTION_LOT_SIZE_INVALID", "NO_NON_EXPIRED_COMMON_EXPIRY",
    "DUPLICATE_OPTION_CELL", "AMBIGUOUS_STRIKE_INTERVAL",
    "IRREGULAR_TARGET_WINDOW", "CHAIN_COVERAGE_INCOMPLETE",
    "OPTION_QUOTE_REQUEST_FAILED", "OPTION_QUOTE_RESPONSE_MALFORMED",
    "OPTION_QUOTE_ROW_NOT_MAPPING", "OPTION_QUOTE_IDENTITY_MISSING",
    "OPTION_QUOTE_IDENTITY_UNREQUESTED", "OPTION_QUOTE_IDENTITY_AMBIGUOUS",
    "OPTION_QUOTE_IDENTITY_CONFLICT", "OPTION_QUOTE_DUPLICATE",
    "OPTION_QUOTE_REQUIRED_FIELD_MISSING", "OPTION_QUOTE_COUNT_INCOMPLETE",
    "OPTION_QUOTE_TIMESTAMP_INVALID", "OPTION_QUOTE_DEPTH_MALFORMED",
    "OPTION_QUOTE_PRICE_INVALID", "OPTION_QUOTE_TOKEN_MISSING",
    "OPTION_QUOTE_STALE", "BID_ASK_INVALID",
    "AUTHENTICATION_FAILED", "RATE_LIMITED", "UNKNOWN_SANITIZED_FAILURE",
})
ALLOWED_REJECTED_FIELDS = frozenset({
    "instrument_key", "instrument_token", "trading_symbol", "option_side",
    "expiry", "strike", "lot_size", "response_shape", "duplicate_identity",
    "token_ownership", "common_expiry", "strike_interval", "target_window",
    "quote_identity", "quote_timestamp", "quote_price", "bid_ask", "unknown",
})
_SAFE_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")


def _text(name: str, value: object, *, maximum: int = 128) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be a bounded non-empty string")
    if any(token in value.lower() for token in ("http://", "https://", "authorization", "bearer ", "?")):
        raise ValueError(f"{name} contains unsafe content")
    return value


def _aware(name: str, value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _finite_optional(name: str, value: object | None, *, positive: bool = True) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be finite")
    number = float(value)
    if not isfinite(number) or (positive and number <= 0) or (not positive and number < 0):
        raise ValueError(f"{name} must be finite")
    return number


def _count(name: str, value: object | None) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def build_probe_id(
    *,
    provider: str,
    underlying: str,
    evaluated_at: datetime,
    expiry: date | None,
    atm_strike: float | None,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    evaluated = _aware("evaluated_at", evaluated_at).astimezone(timezone.utc).isoformat()
    payload = "|".join((
        provider,
        underlying,
        evaluated,
        expiry.isoformat() if expiry else "",
        "" if atm_strike is None else f"{float(atm_strike):.10g}",
        schema_version,
    ))
    return "MDR-" + sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class MarketDataReadinessDiagnostic:
    reason_code: str
    source_component: str
    received_count: int | None = None
    normalized_count: int | None = None
    rejected_count: int | None = None
    ce_count: int | None = None
    pe_count: int | None = None
    common_expiry_count: int | None = None
    unique_strike_count: int | None = None
    rejected_field: str | None = None
    rejected_type: str | None = None
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        _text("reason_code", self.reason_code, maximum=64)
        if self.reason_code not in ALLOWED_DIAGNOSTIC_REASONS:
            raise ValueError("diagnostic reason_code is not allowlisted")
        _text("source_component", self.source_component, maximum=64)
        for name in (
            "received_count", "normalized_count", "rejected_count",
            "ce_count", "pe_count", "common_expiry_count", "unique_strike_count",
        ):
            _count(name, getattr(self, name))
        if self.received_count is not None:
            for name in ("normalized_count", "rejected_count"):
                value = getattr(self, name)
                if value is not None and value > self.received_count:
                    raise ValueError(f"{name} cannot exceed received_count")
        if self.rejected_field is not None and self.rejected_field not in ALLOWED_REJECTED_FIELDS:
            raise ValueError("rejected_field is not allowlisted")
        if self.rejected_type is not None and not _SAFE_TYPE.fullmatch(self.rejected_type):
            raise ValueError("rejected_type is unsafe")
        if self.schema_version != "1.0":
            raise ValueError("diagnostic schema_version invalid")


@dataclass(frozen=True, slots=True)
class MarketDataReadinessPolicy:
    max_quote_age_seconds: float = 30.0
    strike_steps: int = 4
    min_ce_coverage: int = 9
    min_pe_coverage: int = 9
    maximum_spread_percentage: float = 10.0

    def __post_init__(self) -> None:
        _finite_optional("max_quote_age_seconds", self.max_quote_age_seconds)
        _finite_optional(
            "maximum_spread_percentage",
            self.maximum_spread_percentage,
            positive=False,
        )
        for name in ("strike_steps", "min_ce_coverage", "min_pe_coverage"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be positive integer")


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
        _text("instrument_key", self.instrument_key)
        _text("trading_symbol", self.trading_symbol)
        _text("moneyness", self.moneyness)
        _text("reason_code", self.reason_code)
        if type(self.option_side) is not OptionSide:
            raise ValueError("option_side invalid")
        _finite_optional("strike", self.strike)
        if type(self.expiry) is not date:
            raise ValueError("expiry invalid")
        if type(self.distance_steps) is not int:
            raise ValueError("distance_steps invalid")
        if type(self.lot_size) is not int or self.lot_size <= 0:
            raise ValueError("lot_size invalid")
        for name in ("last_price", "bid_price", "ask_price"):
            _finite_optional(name, getattr(self, name))
        _finite_optional("spread_percentage", self.spread_percentage, positive=False)
        if self.quote_timestamp is not None:
            _aware("quote_timestamp", self.quote_timestamp)
        if type(self.status) is not ContractReadinessStatus:
            raise ValueError("status invalid")


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
    failure_stage: MarketDataReadinessStage
    diagnostic: MarketDataReadinessDiagnostic | None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _text("provider", self.provider)
        _text("underlying", self.underlying)
        _text("reason_code", self.reason_code)
        if self.underlying_instrument_key is not None:
            _text("underlying_instrument_key", self.underlying_instrument_key)
        _aware("evaluated_at", self.evaluated_at)
        for name in ("spot_price", "strike_interval", "atm_strike"):
            _finite_optional(name, getattr(self, name))
        if self.spot_timestamp is not None:
            _aware("spot_timestamp", self.spot_timestamp)
        if self.expiry is not None and type(self.expiry) is not date:
            raise ValueError("expiry invalid")
        for name in (
            "expected_contract_count", "observed_contract_count",
            "ready_contract_count", "ce_coverage", "pe_coverage",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} invalid")
        if (
            self.observed_contract_count > self.expected_contract_count
            or self.ready_contract_count > self.observed_contract_count
        ):
            raise ValueError("count ordering invalid")
        if len(self.contracts) > 18:
            raise ValueError("contracts exceeds 18")
        if type(self.status) is not MarketDataReadinessStatus:
            raise ValueError("status invalid")
        if type(self.failure_stage) is not MarketDataReadinessStage:
            raise ValueError("failure_stage invalid")
        if (
            self.diagnostic is not None
            and type(self.diagnostic) is not MarketDataReadinessDiagnostic
        ):
            raise ValueError("diagnostic invalid")
        if self.status in {
            MarketDataReadinessStatus.READY,
            MarketDataReadinessStatus.QUOTE_QUALITY_PARTIAL,
        }:
            if self.failure_stage is not MarketDataReadinessStage.COMPLETED:
                raise ValueError("successful report must be COMPLETED")
        elif self.failure_stage is MarketDataReadinessStage.COMPLETED:
            raise ValueError("failed report cannot be COMPLETED")
        expected_id = build_probe_id(
            provider=self.provider,
            underlying=self.underlying,
            evaluated_at=self.evaluated_at,
            expiry=self.expiry,
            atm_strike=self.atm_strike,
            schema_version=self.schema_version,
        )
        if self.probe_id != expected_id:
            raise ValueError("probe_id invalid")
        if self.status is MarketDataReadinessStatus.READY:
            if (
                self.expected_contract_count != self.observed_contract_count
                or self.ready_contract_count != self.expected_contract_count
                or self.spot_price is None
                or self.spot_timestamp is None
            ):
                raise ValueError("READY evidence incomplete")
