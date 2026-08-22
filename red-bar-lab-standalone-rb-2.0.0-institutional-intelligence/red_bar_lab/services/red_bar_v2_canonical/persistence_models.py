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

    def __post_init__(self) -> None:
        for name in ("event_id", "bundle_id", "source", "reason_code"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.event_timestamp.tzinfo is None or self.event_timestamp.utcoffset() is None:
            raise ValueError("event_timestamp must be timezone-aware")
        from .persistence_identity import build_canonical_bundle_event_id

        expected = build_canonical_bundle_event_id(
            bundle_id=self.bundle_id,
            event_type=self.event_type.value,
            event_timestamp=self.event_timestamp,
            source=self.source,
            reason_code=self.reason_code,
        )
        if self.event_id != expected:
            raise ValueError("event_id does not match canonical lifecycle fields")


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

    def __post_init__(self) -> None:
        for name in ("schema_version", "resolution_id", "instrument_key", "source_replay_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.schema_version != "1.0":
            raise ValueError(f"unsupported resolution schema: {self.schema_version}")
        if self.resolved_at.tzinfo is None or self.resolved_at.utcoffset() is None:
            raise ValueError("resolved_at must be timezone-aware")
        if self.section_1.trading_date != self.trading_date:
            raise ValueError("readiness trading date must match envelope")
        if self.section_2.reference is not None and self.section_2.reference.trading_date != self.trading_date:
            raise ValueError("decision reference trading date must match envelope")
        if self.section_3 is not None:
            if self.section_3.instrument_key != self.instrument_key:
                raise ValueError("bundle underlying instrument must match envelope")
            if self.section_3.trading_date != self.trading_date:
                raise ValueError("bundle trading date must match envelope")
            if self.section_3.decision != self.section_2:
                raise ValueError("bundle decision must match envelope decision")
        if self.parity is not None:
            if self.parity.canonical_direction is not self.section_2.direction:
                raise ValueError("parity direction must match envelope decision")
            if self.parity.canonical_option_side is not self.section_2.option_side:
                raise ValueError("parity option side must match envelope decision")
            if self.parity.canonical_entry_type is not self.section_2.entry_type:
                raise ValueError("parity entry type must match envelope decision")
            if self.parity.canonical_admission_code != self.section_2.admission_code:
                raise ValueError("parity admission code must match envelope decision")

        from .persistence_identity import build_canonical_resolution_id

        expected = build_canonical_resolution_id(
            strategy_id=self.section_2.strategy_id,
            strategy_version=self.section_2.strategy_version,
            instrument_key=self.instrument_key,
            trading_date=self.trading_date,
            source_replay_id=self.source_replay_id,
            evaluation_timestamp=self.section_2.evaluation_timestamp,
            entry_type=self.section_2.entry_type,
            direction=self.section_2.direction,
            admission_outcome=self.section_2.admission_outcome,
        )
        if self.resolution_id != expected:
            raise ValueError("resolution_id does not match canonical envelope fields")


class CanonicalPersistenceError(Exception):
    """Base canonical persistence failure."""


class CanonicalPersistenceConflictError(CanonicalPersistenceError):
    """Same canonical identity was observed with different immutable evidence."""


class CanonicalPersistenceCorruptionError(CanonicalPersistenceError):
    """Stored payload does not match its recorded digest or schema."""


class CanonicalPersistenceUnavailableError(CanonicalPersistenceError):
    """Storage cannot safely complete the transaction."""
