from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import sqlite3
from typing import Protocol

from .persistence_models import (
    CanonicalBundleLifecycleEvent,
    CanonicalPersistenceCorruptionError,
    CanonicalPersistenceUnavailableError,
    PersistedRedBarV2Resolution,
)
from .persistence_serialization import (
    lifecycle_event_from_json,
    resolution_envelope_from_json,
)
from .persistence_identity import payload_sha256


@dataclass(frozen=True, slots=True)
class ObservabilityResolutionRecord:
    envelope: PersistedRedBarV2Resolution
    persisted_at: datetime


class RedBarV2CanonicalObservabilityRepository(Protocol):
    def latest_resolution(self, *, instrument_key: str, trading_date: date | None = None) -> ObservabilityResolutionRecord | None: ...
    def recent_resolutions(self, *, instrument_key: str, limit: int, trading_date: date | None = None) -> tuple[ObservabilityResolutionRecord, ...]: ...
    def bundle_events(self, *, bundle_id: str) -> tuple[CanonicalBundleLifecycleEvent, ...]: ...


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
    def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone() is not None

    @staticmethod
    def _decode_resolution(row: sqlite3.Row) -> ObservabilityResolutionRecord:
        payload = str(row["payload_json"])
        digest = str(row["payload_sha256"])
        if payload_sha256(payload) != digest:
            raise CanonicalPersistenceCorruptionError("resolution payload digest mismatch")
        try:
            envelope = resolution_envelope_from_json(payload)
            persisted_at = datetime.fromisoformat(str(row["persisted_at"]).replace("Z", "+00:00"))
        except Exception as exc:
            raise CanonicalPersistenceCorruptionError("resolution payload violates canonical schema") from exc
        projections = {
            "resolution_id": envelope.resolution_id,
            "instrument_key": envelope.instrument_key,
            "trading_date": envelope.trading_date.isoformat(),
            "source_replay_id": envelope.source_replay_id,
            "resolution_schema_version": envelope.schema_version,
            "bundle_id": envelope.section_3.bundle_id if envelope.section_3 else None,
        }
        for field, expected in projections.items():
            if row[field] != expected:
                raise CanonicalPersistenceCorruptionError(f"resolution projection mismatch: {field}")
        return ObservabilityResolutionRecord(envelope=envelope, persisted_at=persisted_at)

    def recent_resolutions(self, *, instrument_key: str, limit: int, trading_date: date | None = None) -> tuple[ObservabilityResolutionRecord, ...]:
        bounded = min(max(int(limit), 1), 100)
        try:
            with self._connect() as conn:
                if not self._table_exists(conn, "canonical_red_bar_v2_resolutions"):
                    return ()
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
            raise CanonicalPersistenceUnavailableError(str(exc)) from exc
        return tuple(self._decode_resolution(row) for row in rows)

    def latest_resolution(self, *, instrument_key: str, trading_date: date | None = None) -> ObservabilityResolutionRecord | None:
        rows = self.recent_resolutions(
            instrument_key=instrument_key,
            trading_date=trading_date,
            limit=1,
        )
        return rows[0] if rows else None

    def bundle_events(self, *, bundle_id: str) -> tuple[CanonicalBundleLifecycleEvent, ...]:
        try:
            with self._connect() as conn:
                if not self._table_exists(conn, "canonical_red_bar_v2_bundle_events"):
                    return ()
                rows = conn.execute(
                    """
                    SELECT metadata_json,metadata_sha256
                    FROM canonical_red_bar_v2_bundle_events
                    WHERE bundle_id=?
                    ORDER BY event_timestamp ASC,event_id ASC
                    """,
                    (bundle_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise CanonicalPersistenceUnavailableError(str(exc)) from exc
        events: list[CanonicalBundleLifecycleEvent] = []
        for row in rows:
            payload = str(row["metadata_json"])
            if payload_sha256(payload) != str(row["metadata_sha256"]):
                raise CanonicalPersistenceCorruptionError("lifecycle event digest mismatch")
            try:
                events.append(lifecycle_event_from_json(payload))
            except Exception as exc:
                raise CanonicalPersistenceCorruptionError("lifecycle event payload violates canonical schema") from exc
        return tuple(events)
