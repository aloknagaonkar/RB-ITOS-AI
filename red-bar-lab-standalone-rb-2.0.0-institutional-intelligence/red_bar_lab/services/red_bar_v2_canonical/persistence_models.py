from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Mapping

from red_bar_lab.domain.red_bar_v2 import (
    RedBarV2Decision,
    RedBarV2InputReadiness,
    RedBarV2SignalBundle,
)

from .models import RedBarV2ParityResult


class PersistenceOutcome(StrEnum):
    INSERTED = "INSERTED"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
    CONFLICT = "CONFLICT"
    FAILED = "FAILED"


class CanonicalBundleEventType(StrEnum):
    BUNDLE_AVAILABLE = "BUNDLE_AVAILABLE"
    PERSISTENCE_CONFLICT_OBSERVED = "PERSISTENCE_CONFLICT_OBSERVED"


@dataclass(frozen=True, slots=True)
class CanonicalPersistenceResult:
    resolution_id: str
    bundle_id: str | None
    outcome: PersistenceOutcome
    resolution_inserted: bool
    bundle_inserted: bool
    lifecycle_event_inserted: bool
    conflict_detected: bool
    persisted_at: datetime
    duration_ms: float
    payload_size_bytes: int
    transaction_retry_count: int = 0
    sqlite_error_category: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalBundleLifecycleEvent:
    event_id: str
    bundle_id: str
    event_type: CanonicalBundleEventType
    event_timestamp: datetime
    source: str
    reason_code: str
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PersistedRedBarV2Resolution:
    schema_version: str
    resolution_id: str
    instrument_key: str
    trading_date: date
    source_replay_id: str
    resolved_at: datetime
    section_1: RedBarV2InputReadiness
    section_2: RedBarV2Decision
    section_3: RedBarV2SignalBundle | None
    parity: RedBarV2ParityResult | None


class CanonicalPersistenceError(Exception):
    """Base canonical persistence failure."""


class CanonicalPersistenceConflictError(CanonicalPersistenceError):
    """Same canonical identity was observed with different immutable evidence."""


class CanonicalPersistenceCorruptionError(CanonicalPersistenceError):
    """Stored payload does not match its recorded digest or schema."""


class CanonicalPersistenceUnavailableError(CanonicalPersistenceError):
    """Storage cannot safely complete the transaction."""
