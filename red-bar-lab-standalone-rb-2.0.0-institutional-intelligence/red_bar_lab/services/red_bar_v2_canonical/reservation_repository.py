from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3

from red_bar_lab.domain.red_bar_v2 import RedBarV2SignalBundle, red_bar_v2_bundle_from_dict

from .persistence_identity import payload_sha256
from .persistence_models import CanonicalPersistenceCorruptionError
from .persistence_serialization import lifecycle_event_from_json
from .reservation_identity import (
    build_reservation_event_id,
    build_reservation_id,
    canonical_reservation_json,
    reservation_sha256,
)
from .reservation_models import (
    CanonicalBundleReservation,
    CanonicalReservationResult,
    ReservationEventType,
    ReservationOutcome,
    ReservationState,
)
from .reservation_policy import evaluate_reservation_eligibility

SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_red_bar_v2_bundle_reservations (
 reservation_id TEXT PRIMARY KEY,bundle_id TEXT NOT NULL,owner_id TEXT NOT NULL,state TEXT NOT NULL,
 reserved_at TEXT NOT NULL,lease_expires_at TEXT NOT NULL,released_at TEXT,release_reason TEXT,
 schema_version TEXT NOT NULL,payload_json TEXT NOT NULL,payload_sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rbv2_reservation_bundle_state
ON canonical_red_bar_v2_bundle_reservations(bundle_id,state,lease_expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_rbv2_active_bundle
ON canonical_red_bar_v2_bundle_reservations(bundle_id) WHERE state='RESERVED';
CREATE TABLE IF NOT EXISTS canonical_red_bar_v2_bundle_reservation_events (
 event_id TEXT PRIMARY KEY,reservation_id TEXT NOT NULL,bundle_id TEXT NOT NULL,event_type TEXT NOT NULL,
 event_timestamp TEXT NOT NULL,owner_id TEXT NOT NULL,reason_code TEXT NOT NULL,
 metadata_json TEXT NOT NULL,metadata_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rbv2_reservation_events
ON canonical_red_bar_v2_bundle_reservation_events(bundle_id,event_timestamp);
"""


class ReservationStorageError(Exception):
    pass


class SQLiteCanonicalReservationRepository:
    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=max(self.busy_timeout_ms / 1000, 0.1), isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return conn

    @staticmethod
    def _verify_bundle(conn: sqlite3.Connection, bundle_id: str) -> tuple[RedBarV2SignalBundle, bool]:
        row = conn.execute("SELECT payload_json,payload_sha256 FROM canonical_red_bar_v2_bundles WHERE bundle_id=?", (bundle_id,)).fetchone()
        if row is None:
            raise LookupError("BUNDLE_NOT_FOUND")
        payload = str(row["payload_json"])
        if payload_sha256(payload) != str(row["payload_sha256"]):
            raise CanonicalPersistenceCorruptionError("bundle payload digest mismatch")
        try:
            bundle = red_bar_v2_bundle_from_dict(json.loads(payload))
        except Exception as exc:
            raise CanonicalPersistenceCorruptionError("bundle payload violates canonical schema") from exc
        events = conn.execute(
            "SELECT metadata_json,metadata_sha256 FROM canonical_red_bar_v2_bundle_events WHERE bundle_id=?",
            (bundle_id,),
        ).fetchall()
        available = False
        for event_row in events:
            event_json = str(event_row["metadata_json"])
            if payload_sha256(event_json) != str(event_row["metadata_sha256"]):
                raise CanonicalPersistenceCorruptionError("lifecycle event digest mismatch")
            event = lifecycle_event_from_json(event_json)
            available = available or event.event_type.value == "BUNDLE_AVAILABLE"
        return bundle, available

    @staticmethod
    def _payload(reservation: CanonicalBundleReservation) -> str:
        data = asdict(reservation)
        for key in ("trading_date", "reserved_at", "lease_expires_at", "released_at"):
            value = data[key]
            data[key] = value.isoformat() if value is not None else None
        for key in ("direction", "option_side", "entry_type", "state"):
            data[key] = data[key].value
        return canonical_reservation_json(data)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> CanonicalBundleReservation:
        from red_bar_lab.domain.red_bar_v2 import Direction, EntryType, OptionSide
        payload = str(row["payload_json"])
        if reservation_sha256(payload) != str(row["payload_sha256"]):
            raise CanonicalPersistenceCorruptionError("reservation payload digest mismatch")
        data = json.loads(payload)
        return CanonicalBundleReservation(
            reservation_id=data["reservation_id"],bundle_id=data["bundle_id"],signal_id=data["signal_id"],
            idempotency_key=data["idempotency_key"],strategy_id=data["strategy_id"],strategy_version=data["strategy_version"],
            instrument_key=data["instrument_key"],trading_date=datetime.fromisoformat(data["trading_date"]).date(),
            direction=Direction(data["direction"]),option_side=OptionSide(data["option_side"]),entry_type=EntryType(data["entry_type"]),
            owner_id=data["owner_id"],state=ReservationState(data["state"]),reserved_at=datetime.fromisoformat(data["reserved_at"]),
            lease_expires_at=datetime.fromisoformat(data["lease_expires_at"]),
            released_at=datetime.fromisoformat(data["released_at"]) if data["released_at"] else None,
            release_reason=data["release_reason"],schema_version=data["schema_version"],
        )

    def reserve(self, *, bundle_id: str, owner_id: str, requested_at: datetime, lease_seconds: int, feature_enabled: bool) -> CanonicalReservationResult:
        if not feature_enabled:
            return CanonicalReservationResult(ReservationOutcome.RESERVATION_DISABLED, "FEATURE_DISABLED", None)
        try:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                bundle, has_available = self._verify_bundle(conn, bundle_id)
                eligibility = evaluate_reservation_eligibility(bundle=bundle,evaluated_at=requested_at,feature_enabled=True,has_bundle_available_event=has_available)
                if not eligibility.eligible:
                    conn.execute("ROLLBACK")
                    return CanonicalReservationResult(ReservationOutcome.BUNDLE_INELIGIBLE, eligibility.reason_code, None)
                active = conn.execute(
                    "SELECT * FROM canonical_red_bar_v2_bundle_reservations WHERE bundle_id=? AND state='RESERVED'",
                    (bundle_id,),
                ).fetchone()
                if active is not None:
                    current = self._from_row(active)
                    if current.lease_expires_at <= requested_at:
                        expired = CanonicalBundleReservation(**{**asdict(current),"state":ReservationState.EXPIRED,"released_at":requested_at,"release_reason":"LEASE_EXPIRED"})
                        self._update(conn, expired, requested_at)
                        self._event(conn, expired, ReservationEventType.RESERVATION_EXPIRED, requested_at, "LEASE_EXPIRED")
                    elif current.owner_id == owner_id:
                        conn.execute("COMMIT")
                        return CanonicalReservationResult(ReservationOutcome.IDEMPOTENT_REPLAY, "ACTIVE_OWNER_REPLAY", current)
                    else:
                        conn.execute("COMMIT")
                        return CanonicalReservationResult(ReservationOutcome.ALREADY_RESERVED, "ACTIVE_LEASE_OWNED", current)
                lease = min(max(int(lease_seconds), 5), 300)
                reservation = CanonicalBundleReservation(
                    reservation_id=build_reservation_id(bundle_id=bundle.bundle_id,idempotency_key=bundle.idempotency_key,owner_id=owner_id,lease_epoch=requested_at),
                    bundle_id=bundle.bundle_id,signal_id=bundle.signal_id,idempotency_key=bundle.idempotency_key,
                    strategy_id=bundle.strategy_id,strategy_version=bundle.strategy_version,instrument_key=bundle.instrument_key or "",
                    trading_date=bundle.trading_date,direction=bundle.direction,option_side=bundle.option_side,entry_type=bundle.entry_type,
                    owner_id=owner_id,state=ReservationState.RESERVED,reserved_at=requested_at,
                    lease_expires_at=requested_at + timedelta(seconds=lease),released_at=None,release_reason=None,
                )
                payload = self._payload(reservation)
                now = requested_at.isoformat()
                conn.execute(
                    "INSERT INTO canonical_red_bar_v2_bundle_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (reservation.reservation_id,bundle_id,owner_id,reservation.state.value,reservation.reserved_at.isoformat(),reservation.lease_expires_at.isoformat(),None,None,reservation.schema_version,payload,reservation_sha256(payload),now,now),
                )
                self._event(conn,reservation,ReservationEventType.RESERVATION_ACQUIRED,requested_at,"ACQUIRED")
                conn.execute("COMMIT")
                return CanonicalReservationResult(ReservationOutcome.ACQUIRED, "ACQUIRED", reservation)
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
        except LookupError:
            return CanonicalReservationResult(ReservationOutcome.BUNDLE_UNAVAILABLE, "BUNDLE_NOT_FOUND", None)
        except CanonicalPersistenceCorruptionError:
            return CanonicalReservationResult(ReservationOutcome.BUNDLE_CORRUPT, "BUNDLE_CORRUPT", None)
        except sqlite3.Error as exc:
            raise ReservationStorageError(str(exc)) from exc

    def _update(self, conn: sqlite3.Connection, reservation: CanonicalBundleReservation, at: datetime) -> None:
        payload = self._payload(reservation)
        conn.execute("UPDATE canonical_red_bar_v2_bundle_reservations SET state=?,released_at=?,release_reason=?,payload_json=?,payload_sha256=?,updated_at=? WHERE reservation_id=?",
                     (reservation.state.value,reservation.released_at.isoformat() if reservation.released_at else None,reservation.release_reason,payload,reservation_sha256(payload),at.isoformat(),reservation.reservation_id))

    def _event(self, conn: sqlite3.Connection, reservation: CanonicalBundleReservation, event_type: ReservationEventType, at: datetime, reason: str) -> None:
        event_id = build_reservation_event_id(reservation_id=reservation.reservation_id,event_type=event_type.value,event_timestamp=at,owner_id=reservation.owner_id,reason_code=reason)
        metadata = canonical_reservation_json({"reservation_id":reservation.reservation_id,"bundle_id":reservation.bundle_id,"state":reservation.state.value})
        conn.execute("INSERT OR IGNORE INTO canonical_red_bar_v2_bundle_reservation_events VALUES(?,?,?,?,?,?,?,?,?)",
                     (event_id,reservation.reservation_id,reservation.bundle_id,event_type.value,at.isoformat(),reservation.owner_id,reason,metadata,reservation_sha256(metadata)))

    def release(self, *, reservation_id: str, owner_id: str, released_at: datetime, reason_code: str) -> CanonicalReservationResult:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM canonical_red_bar_v2_bundle_reservations WHERE reservation_id=?",(reservation_id,)).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return CanonicalReservationResult(ReservationOutcome.BUNDLE_UNAVAILABLE,"RESERVATION_NOT_FOUND",None)
            current = self._from_row(row)
            if current.owner_id != owner_id:
                conn.execute("COMMIT")
                return CanonicalReservationResult(ReservationOutcome.ALREADY_RESERVED,"OWNER_MISMATCH",current)
            if current.state is ReservationState.RELEASED:
                conn.execute("COMMIT")
                return CanonicalReservationResult(ReservationOutcome.IDEMPOTENT_REPLAY,"ALREADY_RELEASED",current)
            released = CanonicalBundleReservation(**{**asdict(current),"state":ReservationState.RELEASED,"released_at":released_at,"release_reason":reason_code})
            self._update(conn,released,released_at)
            self._event(conn,released,ReservationEventType.RESERVATION_RELEASED,released_at,reason_code)
            conn.execute("COMMIT")
            return CanonicalReservationResult(ReservationOutcome.RELEASED,reason_code,released)
        except Exception:
            if conn.in_transaction: conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def get_active(self, *, bundle_id: str, at: datetime) -> CanonicalBundleReservation | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM canonical_red_bar_v2_bundle_reservations WHERE bundle_id=? AND state='RESERVED'",(bundle_id,)).fetchone()
        if row is None: return None
        reservation = self._from_row(row)
        return reservation if reservation.lease_expires_at > at else None
