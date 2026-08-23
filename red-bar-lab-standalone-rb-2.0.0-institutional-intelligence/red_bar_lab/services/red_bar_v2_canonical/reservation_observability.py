from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3

from .reservation_evidence_verification import (
    ReservationCorruptionError,
    verify_reservation_evidence,
)
from .reservation_models import CanonicalBundleReservation


@dataclass(frozen=True, slots=True)
class ReservationEventObservation:
    event_type: str
    event_timestamp: datetime
    owner_id: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class ReservationObservationResult:
    status: str
    reservation: CanonicalBundleReservation | None
    events: tuple[ReservationEventObservation, ...]


class SQLiteReservationObservabilityRepository:
    """Read-only reservation projection requiring complete verified lifecycle history."""

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

    def latest_for_bundle(self, *, bundle_id: str, event_limit: int = 25) -> ReservationObservationResult:
        bounded = min(max(int(event_limit), 1), 100)
        try:
            with self._connect() as conn:
                table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='canonical_red_bar_v2_bundle_reservations'"
                ).fetchone()
                if table is None:
                    return ReservationObservationResult("NO_RESERVATION", None, ())
                row = conn.execute(
                    "SELECT reservation_id FROM canonical_red_bar_v2_bundle_reservations WHERE bundle_id=? ORDER BY created_at DESC,reservation_id DESC LIMIT 1",
                    (bundle_id,),
                ).fetchone()
                if row is None:
                    return ReservationObservationResult("NO_RESERVATION", None, ())
                evidence = verify_reservation_evidence(
                    conn,
                    reservation_id=str(row["reservation_id"]),
                    expected_bundle_id=bundle_id,
                )
            projected = tuple(
                ReservationEventObservation(
                    event_type=event.event_type.value,
                    event_timestamp=event.event_timestamp,
                    owner_id=event.owner_id,
                    reason_code=event.reason_code,
                )
                for event in evidence.events[-bounded:]
            )
            return ReservationObservationResult(
                "RESERVATION_DATA_AVAILABLE",
                evidence.reservation,
                projected,
            )
        except ReservationCorruptionError:
            return ReservationObservationResult("RESERVATION_DATA_CORRUPT", None, ())
        except (FileNotFoundError, sqlite3.Error, OSError):
            return ReservationObservationResult("RESERVATION_DATABASE_UNAVAILABLE", None, ())


ReservationObservation = CanonicalBundleReservation
