from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from .reservation_identity import reservation_sha256
from .reservation_models import (
    CanonicalBundleReservation,
    CanonicalReservationLifecycleEvent,
    ReservationEventType,
)
from .reservation_repository import ReservationCorruptionError, SQLiteCanonicalReservationRepository


@dataclass(frozen=True, slots=True)
class ReservationObservationResult:
    status: str
    reservation: CanonicalBundleReservation | None
    events: tuple[CanonicalReservationLifecycleEvent, ...]


class SQLiteReservationObservabilityRepository:
    """Read-only, integrity-verifying reservation projection."""

    def __init__(self, path: Path, *, busy_timeout_ms: int = 250) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = int(busy_timeout_ms)

    def _connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise FileNotFoundError("reservation database does not exist")
        conn = sqlite3.connect(
            f"file:{self.path.resolve().as_posix()}?mode=ro",
            uri=True,
            timeout=max(self.busy_timeout_ms / 1000.0, 0.1),
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return conn

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone() is not None

    @staticmethod
    def _decode_event(row: sqlite3.Row) -> CanonicalReservationLifecycleEvent:
        payload = str(row["metadata_json"])
        if reservation_sha256(payload) != str(row["metadata_sha256"]):
            raise ReservationCorruptionError("reservation event digest mismatch")
        try:
            metadata = json.loads(payload)
            event = CanonicalReservationLifecycleEvent(
                event_id=str(row["event_id"]),
                reservation_id=str(row["reservation_id"]),
                bundle_id=str(row["bundle_id"]),
                event_type=ReservationEventType(str(row["event_type"])),
                event_timestamp=datetime.fromisoformat(str(row["event_timestamp"])),
                owner_id=str(row["owner_id"]),
                reason_code=str(row["reason_code"]),
                metadata=metadata,
            )
        except Exception as exc:
            raise ReservationCorruptionError("reservation event violates canonical schema") from exc
        if metadata.get("reservation_id") != event.reservation_id:
            raise ReservationCorruptionError("reservation event metadata mismatch: reservation_id")
        if metadata.get("bundle_id") != event.bundle_id:
            raise ReservationCorruptionError("reservation event metadata mismatch: bundle_id")
        return event

    def latest_for_bundle(
        self,
        *,
        bundle_id: str,
        event_limit: int = 25,
    ) -> ReservationObservationResult:
        bounded = min(max(int(event_limit), 1), 100)
        try:
            with self._connect() as conn:
                if not self._table_exists(conn, "canonical_red_bar_v2_bundle_reservations"):
                    return ReservationObservationResult("NO_RESERVATION", None, ())
                row = conn.execute(
                    "SELECT * FROM canonical_red_bar_v2_bundle_reservations WHERE bundle_id=? ORDER BY created_at DESC,reservation_id DESC LIMIT 1",
                    (bundle_id,),
                ).fetchone()
                if row is None:
                    return ReservationObservationResult("NO_RESERVATION", None, ())
                reservation = SQLiteCanonicalReservationRepository._from_row(row)
                if reservation.bundle_id != bundle_id:
                    raise ReservationCorruptionError("reservation bundle mismatch")
                if not self._table_exists(conn, "canonical_red_bar_v2_bundle_reservation_events"):
                    raise ReservationCorruptionError("reservation event table missing")
                rows = conn.execute(
                    "SELECT event_id,reservation_id,bundle_id,event_type,event_timestamp,owner_id,reason_code,metadata_json,metadata_sha256 FROM canonical_red_bar_v2_bundle_reservation_events WHERE reservation_id=? AND bundle_id=? ORDER BY event_timestamp DESC,event_id DESC LIMIT ?",
                    (reservation.reservation_id, reservation.bundle_id, bounded),
                ).fetchall()
            events = tuple(self._decode_event(item) for item in rows)
            for event in events:
                if event.reservation_id != reservation.reservation_id:
                    raise ReservationCorruptionError("reservation event projection mismatch: reservation_id")
                if event.bundle_id != reservation.bundle_id:
                    raise ReservationCorruptionError("reservation event projection mismatch: bundle_id")
            return ReservationObservationResult("RESERVATION_DATA_AVAILABLE", reservation, events)
        except ReservationCorruptionError:
            return ReservationObservationResult("RESERVATION_DATA_CORRUPT", None, ())
        except (FileNotFoundError, sqlite3.Error, OSError):
            return ReservationObservationResult("RESERVATION_DATABASE_UNAVAILABLE", None, ())


ReservationObservation = CanonicalBundleReservation
ReservationEventObservation = CanonicalReservationLifecycleEvent
