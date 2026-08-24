from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from hashlib import sha256
from math import isfinite

SCHEMA_VERSION = "1.0"
AUTHORITY = "OBSERVATIONAL_ONLY"


class ResearchState(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    TIMEOUT = "TIMEOUT"
    INCOMPLETE = "INCOMPLETE"
    DATA_INVALID = "DATA_INVALID"
    MORNING_ANCHOR_UNAVAILABLE = "MORNING_ANCHOR_UNAVAILABLE"
    EXPIRY_MISMATCH = "EXPIRY_MISMATCH"
    WINDOW_TRANSITION = "WINDOW_TRANSITION"
    PCR_UNAVAILABLE_ZERO_DENOMINATOR = "PCR_UNAVAILABLE_ZERO_DENOMINATOR"


class PcrBias(str, Enum):
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    BULLISH = "BULLISH"
    STRONGLY_BULLISH = "STRONGLY_BULLISH"
    UNAVAILABLE = "UNAVAILABLE"


def _text(name: str, value: object) -> str:
    if type(value) is not str or not value.strip() or len(value) > 128:
        raise ValueError(f"{name} must be bounded text")
    return value.strip()


def _aware(name: str, value: object) -> datetime:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _number(name: str, value: object, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{name} invalid")
    return result


@dataclass(frozen=True, slots=True)
class OptionOiCell:
    instrument_key: str
    option_side: str
    strike: float
    expiry: date
    current_oi: float
    provider_prev_oi: float | None
    source_timestamp: datetime

    def __post_init__(self) -> None:
        _text("instrument_key", self.instrument_key)
        if self.option_side not in {"CE", "PE"}:
            raise ValueError("option_side invalid")
        _number("strike", self.strike, positive=True)
        if type(self.expiry) is not date:
            raise ValueError("expiry invalid")
        _number("current_oi", self.current_oi)
        if self.current_oi < 0:
            raise ValueError("current_oi cannot be negative")
        if self.provider_prev_oi is not None:
            _number("provider_prev_oi", self.provider_prev_oi)
            if self.provider_prev_oi < 0:
                raise ValueError("provider_prev_oi cannot be negative")
        _aware("source_timestamp", self.source_timestamp)


@dataclass(frozen=True, slots=True)
class OiChangeEvidence:
    current: float
    baseline: float | None
    absolute_change: float | None
    percentage_change: float | None
    reason: str


@dataclass(frozen=True, slots=True)
class PcrWindowDefinition:
    expiry: date
    atm: float
    strike_interval: float
    window_steps: int
    strikes: tuple[float, ...]
    instrument_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.expiry) is not date:
            raise ValueError("expiry invalid")
        _number("atm", self.atm, positive=True)
        _number("strike_interval", self.strike_interval, positive=True)
        if type(self.window_steps) is not int or not 1 <= self.window_steps <= 5:
            raise ValueError("window_steps invalid")
        if len(self.strikes) != (2 * self.window_steps) + 1:
            raise ValueError("strike population invalid")
        if len(self.instrument_keys) != self.expected_contract_count:
            raise ValueError("instrument population invalid")
        if len(set(self.instrument_keys)) != len(self.instrument_keys):
            raise ValueError("duplicate instrument identity")

    @property
    def expected_contract_count(self) -> int:
        return ((2 * self.window_steps) + 1) * 2


@dataclass(frozen=True, slots=True)
class PcrAggregate:
    total_ce_oi: float
    total_pe_oi: float
    pcr: float | None
    classification: PcrBias
    previous_pcr: float | None
    absolute_change: float | None
    percentage_change: float | None
    slope_per_minute: float | None
    persistence_state: str
    consecutive_count: int


@dataclass(frozen=True, slots=True)
class PcrResearchPanel:
    name: str
    state: ResearchState
    spot: float
    atm: float
    expiry: date
    sessions_to_expiry: int
    strike_interval: float
    window_steps: int
    expected_contract_count: int
    observed_contract_count: int
    source_timestamp: datetime
    aggregate: PcrAggregate
    rows: tuple[dict[str, object], ...]
    anchor_timestamp: datetime | None = None
    anchor_status: str | None = None
    anchor_spot: float | None = None
    anchor_atm: float | None = None
    anchor_relevance: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchLatencyEvidence:
    source_ms: float
    normalization_ms: float
    calculation_ms: float
    persistence_ms: float
    end_to_end_ms: float
    dropped_obsolete_tasks: int = 0


@dataclass(frozen=True, slots=True)
class ResearchDataQuality:
    state: ResearchState
    source_age_seconds: float
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DualPcrResearchSnapshot:
    snapshot_id: str
    trading_date: date
    underlying: str
    provider: str
    source_timestamp: datetime
    evaluated_at: datetime
    current_panel: PcrResearchPanel
    morning_panel: PcrResearchPanel | None
    quality: ResearchDataQuality
    latency: ResearchLatencyEvidence
    agreement_state: str
    explanation: tuple[str, ...]
    authority: str = AUTHORITY
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _text("snapshot_id", self.snapshot_id)
        _text("underlying", self.underlying)
        _text("provider", self.provider)
        _aware("source_timestamp", self.source_timestamp)
        _aware("evaluated_at", self.evaluated_at)
        if self.authority != AUTHORITY:
            raise ValueError("research authority invalid")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("research schema version invalid")

    @classmethod
    def build_id(
        cls,
        *,
        underlying: str,
        provider: str,
        source_timestamp: datetime,
    ) -> str:
        payload = (
            f"{underlying}|{provider}|{source_timestamp.isoformat()}|"
            f"{SCHEMA_VERSION}"
        )
        return "MTR-" + sha256(payload.encode()).hexdigest()[:32]
