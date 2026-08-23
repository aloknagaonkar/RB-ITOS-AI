from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Protocol

from red_bar_lab.domain.red_bar_v2 import (
    RedBarV2SignalBundle,
    red_bar_v2_bundle_from_dict,
)

from .persistence_identity import payload_sha256
from .persistence_models import (
    CanonicalBundleEventType,
    CanonicalBundleLifecycleEvent,
    CanonicalPersistenceCorruptionError,
    CanonicalPersistenceUnavailableError,
    PersistedRedBarV2Resolution,
)
from .persistence_serialization import (
    lifecycle_event_from_json,
    resolution_envelope_from_json,
)


@dataclass(frozen=True, slots=True)
class ObservabilityResolutionRecord:
    envelope: PersistedRedBarV2Resolution
    persisted_at: datetime


@dataclass(frozen=True, slots=True)
class SelectedCanonicalBundleEvidence:
    bundle: RedBarV2SignalBundle
    events: tuple[CanonicalBundleLifecycleEvent, ...]


class RedBarV2CanonicalObservabilityRepository(Protocol):
    def latest_resolution(
        self,
        *,
        instrument_key: str,
        trading_date: date | None = None,
    ) -> ObservabilityResolutionRecord | None: ...

    def recent_resolutions(
        self,
        *,
        instrument_key: str,
        limit: int,
        trading_date: date | None = None,
    ) -> tuple[ObservabilityResolutionRecord, ...]: ...

    def selected_bundle_evidence(
        self,
        *,
        expected_bundle: RedBarV2SignalBundle,
    ) -> SelectedCanonicalBundleEvidence: ...


class SQLiteRedBarV2CanonicalObservabilityRepository:
    """Read-only projection over canonical persistence without schema creation."""

    def __init__(self, path: Path, *, busy_timeout_ms: int = 250) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = int(busy_timeout_ms)

    def _connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise CanonicalPersistenceUnavailableError("canonical database does not exist")
        try:
            conn = sqlite3.connect(
                f"file:{self.path.resolve().as_posix()}?mode=ro",
                uri=True,
                timeout=max(self.busy_timeout_ms / 1000.0, 0.1),
            )
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            return conn
        except sqlite3.Error as exc:
            raise CanonicalPersistenceUnavailableError(str(exc)) from exc

    @staticmethod
    def _aware_iso(value: object, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception as exc:
            raise CanonicalPersistenceCorruptionError(f"invalid {field}") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise CanonicalPersistenceCorruptionError(f"naive {field}")
        return parsed

    @staticmethod
    def _same_instant(left: datetime, right: datetime) -> bool:
        if (
            left.tzinfo is None
            or left.utcoffset() is None
            or right.tzinfo is None
            or right.utcoffset() is None
        ):
            return False
        return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)

    @staticmethod
    def _missing_table(exc: sqlite3.Error, table: str) -> bool:
        return f"no such table: {table}" in str(exc).lower()

    @classmethod
    def _decode_bundle(cls, row: sqlite3.Row) -> RedBarV2SignalBundle:
        payload = str(row["payload_json"])
        if payload_sha256(payload) != str(row["payload_sha256"]):
            raise CanonicalPersistenceCorruptionError("bundle payload digest mismatch")
        try:
            bundle = red_bar_v2_bundle_from_dict(json.loads(payload))
        except Exception as exc:
            raise CanonicalPersistenceCorruptionError(
                "bundle payload violates canonical schema"
            ) from exc
        projections: dict[str, object] = {
            "bundle_id": bundle.bundle_id,
            "signal_id": bundle.signal_id,
            "idempotency_key": bundle.idempotency_key,
            "strategy_id": bundle.strategy_id,
            "strategy_version": bundle.strategy_version,
            "instrument_key": bundle.instrument_key,
            "trading_date": bundle.trading_date.isoformat(),
            "entry_type": bundle.entry_type.value,
            "direction": bundle.direction.value,
            "option_side": bundle.option_side.value,
            "bundle_schema_version": bundle.schema_version,
        }
        for field, expected in projections.items():
            if row[field] != expected:
                raise CanonicalPersistenceCorruptionError(
                    f"bundle projection mismatch: {field}"
                )
        stored_eval = cls._aware_iso(
            row["evaluation_timestamp"],
            "bundle evaluation_timestamp",
        )
        if not cls._same_instant(stored_eval, bundle.evaluation_timestamp):
            raise CanonicalPersistenceCorruptionError(
                "bundle projection mismatch: evaluation_timestamp"
            )
        return bundle

    @classmethod
    def _decode_resolution(cls, row: sqlite3.Row) -> ObservabilityResolutionRecord:
        payload = str(row["payload_json"])
        if payload_sha256(payload) != str(row["payload_sha256"]):
            raise CanonicalPersistenceCorruptionError(
                "resolution payload digest mismatch"
            )
        try:
            envelope = resolution_envelope_from_json(payload)
        except Exception as exc:
            raise CanonicalPersistenceCorruptionError(
                "resolution payload violates canonical schema"
            ) from exc
        persisted_at = cls._aware_iso(row["persisted_at"], "persisted_at")
        projections: dict[str, object] = {
            "resolution_id": envelope.resolution_id,
            "instrument_key": envelope.instrument_key,
            "trading_date": envelope.trading_date.isoformat(),
            "source_replay_id": envelope.source_replay_id,
            "resolution_schema_version": envelope.schema_version,
            "bundle_id": envelope.section_3.bundle_id if envelope.section_3 else None,
        }
        for field, expected in projections.items():
            if row[field] != expected:
                raise CanonicalPersistenceCorruptionError(
                    f"resolution projection mismatch: {field}"
                )
        return ObservabilityResolutionRecord(
            envelope=envelope,
            persisted_at=persisted_at,
        )

    @classmethod
    def _decode_event(
        cls,
        row: sqlite3.Row,
        *,
        requested_bundle_id: str,
    ) -> CanonicalBundleLifecycleEvent:
        payload = str(row["metadata_json"])
        if payload_sha256(payload) != str(row["metadata_sha256"]):
            raise CanonicalPersistenceCorruptionError(
                "lifecycle event digest mismatch"
            )
        try:
            event = lifecycle_event_from_json(payload)
        except Exception as exc:
            raise CanonicalPersistenceCorruptionError(
                "lifecycle event payload violates canonical schema"
            ) from exc
        if event.bundle_id != requested_bundle_id:
            raise CanonicalPersistenceCorruptionError(
                "lifecycle event projection mismatch: requested_bundle_id"
            )
        projections: dict[str, object] = {
            "event_id": event.event_id,
            "bundle_id": event.bundle_id,
            "event_type": event.event_type.value,
            "source": event.source,
            "reason_code": event.reason_code,
        }
        for field, expected in projections.items():
            if row[field] != expected:
                raise CanonicalPersistenceCorruptionError(
                    f"lifecycle event projection mismatch: {field}"
                )
        stored_timestamp = cls._aware_iso(
            row["event_timestamp"],
            "lifecycle event_timestamp",
        )
        if not cls._same_instant(stored_timestamp, event.event_timestamp):
            raise CanonicalPersistenceCorruptionError(
                "lifecycle event projection mismatch: event_timestamp"
            )
        return event

    def recent_resolutions(
        self,
        *,
        instrument_key: str,
        limit: int,
        trading_date: date | None = None,
    ) -> tuple[ObservabilityResolutionRecord, ...]:
        bounded = min(max(int(limit), 1), 100)
        try:
            with self._connect() as conn:
                if trading_date is None:
                    rows = conn.execute(
                        """
                        SELECT * FROM canonical_red_bar_v2_resolutions
                        WHERE instrument_key=?
                        ORDER BY evaluation_timestamp DESC,resolution_id DESC
                        LIMIT ?
                        """,
                        (instrument_key, bounded),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM canonical_red_bar_v2_resolutions
                        WHERE instrument_key=? AND trading_date=?
                        ORDER BY evaluation_timestamp DESC,resolution_id DESC
                        LIMIT ?
                        """,
                        (instrument_key, trading_date.isoformat(), bounded),
                    ).fetchall()
        except sqlite3.Error as exc:
            if self._missing_table(exc, "canonical_red_bar_v2_resolutions"):
                return ()
            raise CanonicalPersistenceUnavailableError(str(exc)) from exc
        return tuple(self._decode_resolution(row) for row in rows)

    def latest_resolution(
        self,
        *,
        instrument_key: str,
        trading_date: date | None = None,
    ) -> ObservabilityResolutionRecord | None:
        rows = self.recent_resolutions(
            instrument_key=instrument_key,
            trading_date=trading_date,
            limit=1,
        )
        return rows[0] if rows else None

    def selected_bundle_evidence(
        self,
        *,
        expected_bundle: RedBarV2SignalBundle,
    ) -> SelectedCanonicalBundleEvidence:
        try:
            with self._connect() as conn:
                try:
                    bundle_row = conn.execute(
                        """
                        SELECT bundle_id,signal_id,idempotency_key,strategy_id,
                               strategy_version,instrument_key,trading_date,
                               evaluation_timestamp,entry_type,direction,option_side,
                               bundle_schema_version,payload_json,payload_sha256
                        FROM canonical_red_bar_v2_bundles
                        WHERE bundle_id=?
                        """,
                        (expected_bundle.bundle_id,),
                    ).fetchone()
                except sqlite3.Error as exc:
                    if self._missing_table(exc, "canonical_red_bar_v2_bundles"):
                        raise CanonicalPersistenceCorruptionError(
                            "resolution references missing bundle table"
                        ) from exc
                    raise
                if bundle_row is None:
                    raise CanonicalPersistenceCorruptionError(
                        "resolution references missing bundle"
                    )
                stored_bundle = self._decode_bundle(bundle_row)
                if stored_bundle != expected_bundle:
                    raise CanonicalPersistenceCorruptionError(
                        "resolution embedded bundle does not match stored bundle"
                    )

                try:
                    event_rows = conn.execute(
                        """
                        SELECT event_id,bundle_id,event_type,event_timestamp,source,
                               reason_code,metadata_json,metadata_sha256
                        FROM canonical_red_bar_v2_bundle_events
                        WHERE bundle_id=?
                        ORDER BY event_timestamp ASC,event_id ASC
                        """,
                        (expected_bundle.bundle_id,),
                    ).fetchall()
                except sqlite3.Error as exc:
                    if self._missing_table(
                        exc,
                        "canonical_red_bar_v2_bundle_events",
                    ):
                        raise CanonicalPersistenceCorruptionError(
                            "bundle references missing lifecycle event table"
                        ) from exc
                    raise
        except CanonicalPersistenceCorruptionError:
            raise
        except sqlite3.Error as exc:
            raise CanonicalPersistenceUnavailableError(str(exc)) from exc

        if not event_rows:
            raise CanonicalPersistenceCorruptionError(
                "bundle has no lifecycle event history"
            )
        events = tuple(
            self._decode_event(
                row,
                requested_bundle_id=expected_bundle.bundle_id,
            )
            for row in event_rows
        )
        if not any(
            event.event_type is CanonicalBundleEventType.BUNDLE_AVAILABLE
            and event.bundle_id == expected_bundle.bundle_id
            for event in events
        ):
            raise CanonicalPersistenceCorruptionError(
                "bundle has no BUNDLE_AVAILABLE lifecycle event"
            )
        return SelectedCanonicalBundleEvidence(
            bundle=stored_bundle,
            events=events,
        )
