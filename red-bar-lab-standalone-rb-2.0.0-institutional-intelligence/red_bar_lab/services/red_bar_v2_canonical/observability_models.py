from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class CanonicalShadowPageStatus:
    availability: str
    authority: str
    canonical_authority: str
    feature_enabled: bool
    latest_event_timestamp: datetime | None
    persisted_at: datetime | None
    age_seconds: float | None
    freshness: str
    reason_code: str
    error_category: str | None
    database_display: str
    runtime_telemetry: str = "NOT DURABLY AVAILABLE"


@dataclass(frozen=True, slots=True)
class CanonicalSection1View:
    outcome: str
    reference_status: str
    trading_date: date | None
    reference_id: str | None
    reference_high: float | None
    reference_low: float | None
    reference_midpoint: float | None
    underlying_instrument: str
    futures_instrument: str | None
    futures_expiry: date | None
    context_status: str
    futures_volume_available: bool
    futures_vwap_available: bool
    latest_index_timestamp: datetime | None
    latest_futures_timestamp: datetime | None
    reason_code: str
    explanation: str


@dataclass(frozen=True, slots=True)
class CanonicalEvidenceView:
    name: str
    numeric_value: str
    required_interpretation: str
    actual_alignment: str


@dataclass(frozen=True, slots=True)
class CanonicalSection2View:
    admission_outcome: str
    previous_state: str
    current_state: str
    direction: str | None
    option_side: str | None
    entry_type: str | None
    evaluation_timeframe: str
    trend_strength: str | None
    admission_code: str
    admission_reason: str
    evidence: tuple[CanonicalEvidenceView, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class CanonicalBundleEventView:
    event_type: str
    event_timestamp: datetime
    source: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class CanonicalSection3View:
    bundle_available: bool
    bundle_id: str | None
    signal_id: str | None
    idempotency_key: str | None
    underlying_instrument: str | None
    trading_date: date | None
    direction: str | None
    option_side: str | None
    entry_type: str | None
    evaluation_timeframe: str | None
    lifecycle_status: str | None
    created_at: datetime | None
    event_history: tuple[CanonicalBundleEventView, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class CanonicalParityRow:
    field: str
    legacy: str
    canonical: str
    status: str


@dataclass(frozen=True, slots=True)
class CanonicalParityView:
    overall: str
    matches: bool | None
    mismatches: tuple[str, ...]
    rows: tuple[CanonicalParityRow, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class CanonicalPersistenceView:
    resolution_id: str
    source_replay_id: str
    schema_version: str
    bundle_schema_version: str | None
    persisted_at: datetime | None
    event_timestamp: datetime | None
    persistence_delay_seconds: float | None
    payload_integrity: str
    event_count: int
    persistence_outcome: str | None
    explanation: str


@dataclass(frozen=True, slots=True)
class CanonicalHistoryRow:
    event_time: str
    trading_date: str
    section_1_outcome: str
    admission_outcome: str
    direction: str
    option_side: str
    entry_type: str
    parity: str
    bundle_available: str
    resolution_id: str
    freshness: str


@dataclass(frozen=True, slots=True)
class CanonicalShadowObservationView:
    status: CanonicalShadowPageStatus
    section_1: CanonicalSection1View | None
    section_2: CanonicalSection2View | None
    section_3: CanonicalSection3View | None
    parity: CanonicalParityView | None
    persistence: CanonicalPersistenceView | None
    history: tuple[CanonicalHistoryRow, ...]
