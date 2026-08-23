from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3


@dataclass(frozen=True, slots=True)
class ReservationObservation:
    reservation_id: str
    bundle_id: str
    owner_id: str
    state: str
    reserved_at: datetime
    lease_expires_at: datetime
    released_at: datetime | None
    release_reason: str | None


@dataclass(frozen=True, slots=True)
class ReservationEventObservation:
    event_type: str
    event_timestamp: datetime
    owner_id: str
    reason_code: str


class SQLiteReservationObservabilityRepository:
    """Read-only reservation projection. It never creates a database or schema."""

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

    def latest_for_bundle(
        self,
        *,
        bundle_id: str,
        event_limit: int = 25,
    ) -> tuple[ReservationObservation | None, tuple[ReservationEventObservation, ...]]:
        bounded = min(max(int(event_limit), 1), 100)
        with self._connect() as conn:
            if not self._table_exists(conn, "canonical_red_bar_v2_bundle_reservations"):
                return None, ()
            row = conn.execute(
                """
                SELECT reservation_id,bundle_id,owner_id,state,reserved_at,
                       lease_expires_at,released_at,release_reason
                FROM canonical_red_bar_v2_bundle_reservations
                WHERE bundle_id=?
                ORDER BY created_at DESC,reservation_id DESC
                LIMIT 1
                """,
                (bundle_id,),
            ).fetchone()
            if row is None:
                return None, ()
            reservation = ReservationObservation(
                reservation_id=str(row["reservation_id"]),
                bundle_id=str(row["bundle_id"]),
                owner_id=str(row["owner_id"]),
                state=str(row["state"]),
                reserved_at=datetime.fromisoformat(str(row["reserved_at"])),
                lease_expires_at=datetime.fromisoformat(str(row["lease_expires_at"])),
                released_at=(
                    datetime.fromisoformat(str(row["released_at"]))
                    if row["released_at"] is not None
                    else None
                ),
                release_reason=(
                    str(row["release_reason"])
                    if row["release_reason"] is not None
                    else None
                ),
            )
            if not self._table_exists(conn, "canonical_red_bar_v2_bundle_reservation_events"):
                return reservation, ()
            rows = conn.execute(
                """
                SELECT event_type,event_timestamp,owner_id,reason_code
                FROM canonical_red_bar_v2_bundle_reservation_events
                WHERE bundle_id=?
                ORDER BY event_timestamp DESC,event_id DESC
                LIMIT ?
                """,
                (bundle_id, bounded),
            ).fetchall()
        events = tuple(
            ReservationEventObservation(
                event_type=str(item["event_type"]),
                event_timestamp=datetime.fromisoformat(str(item["event_timestamp"])),
                owner_id=str(item["owner_id"]),
                reason_code=str(item["reason_code"]),
            )
            for item in rows
        )
        return reservation, events
