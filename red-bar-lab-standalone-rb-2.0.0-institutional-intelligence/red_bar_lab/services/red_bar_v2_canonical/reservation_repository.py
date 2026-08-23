from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from red_bar_lab.domain.red_bar_v2 import Direction, EntryType, OptionSide

from .canonical_evidence_verification import verify_canonical_bundle_evidence
from .persistence_models import CanonicalPersistenceCorruptionError
from .reservation_identity import (
    build_reservation_event_id,
    build_reservation_id,
    canonical_reservation_json,
    reservation_sha256,
)
from .reservation_models import (
    CanonicalBundleReservation,
    CanonicalReservationLifecycleEvent,
    CanonicalReservationResult,
    ReservationEventType,
    ReservationOutcome,
    ReservationState,
)
from .reservation_policy import evaluate_reservation_eligibility

SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_red_bar_v2_bundle_reservations (
    reservation_id TEXT PRIMARY KEY,
    bundle_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    state TEXT NOT NULL,
    reserved_at TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT,
    schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rbv2_reservation_bundle_state
ON canonical_red_bar_v2_bundle_reservations(bundle_id,state,lease_expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_rbv2_active_bundle
ON canonical_red_bar_v2_bundle_reservations(bundle_id) WHERE state='RESERVED';
CREATE TABLE IF NOT EXISTS canonical_red_bar_v2_bundle_reservation_events (
    event_id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL,
    bundle_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_timestamp TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    metadata_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rbv2_reservation_events
ON canonical_red_bar_v2_bundle_reservation_events(bundle_id,event_timestamp);
"""


class ReservationError(Exception):
    """Base reservation-boundary error."""


class ReservationValidationError(ReservationError):
    """Public request is invalid."""


class ReservationConflictError(ReservationError):
    """Reservation state changed or evidence conflicts."""


class ReservationCorruptionError(ReservationError):
    """Persisted reservation evidence is corrupt."""


class ReservationStorageError(ReservationError):
    """Reservation storage is unavailable."""


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReservationValidationError(f"{field} must be timezone-aware")
    return value


def _same_instant(left: datetime, right: datetime) -> bool:
    return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)


class SQLiteCanonicalReservationRepository:
    """Atomic ownership lease with no execution, order, position, or capital authority."""

    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(
                self.path,
                timeout=max(self.busy_timeout_ms / 1000.0, 0.1),
                isolation_level=None,
            )
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            return conn
        except sqlite3.Error as exc:
            raise ReservationStorageError("reservation database unavailable") from exc

    @staticmethod
    def _payload(reservation: CanonicalBundleReservation) -> str:
        data = asdict(reservation)
        for key in ("trading_date", "reserved_at", "lease_expires_at", "released_at"):
            value = data[key]
            data[key] = value.isoformat() if value is not None else None
        for key in ("direction", "option_side", "entry_type", "state"):
            data[key] = data[key].value
        return canonical_reservation_json(data)

    @classmethod
    def _from_row(cls, row: sqlite3.Row) -> CanonicalBundleReservation:
        payload = str(row["payload_json"])
        if reservation_sha256(payload) != str(row["payload_sha256"]):
            raise ReservationCorruptionError("reservation payload digest mismatch")
        try:
            data = json.loads(payload)
            reservation = CanonicalBundleReservation(
                reservation_id=data["reservation_id"],
                bundle_id=data["bundle_id"],
                signal_id=data["signal_id"],
                idempotency_key=data["idempotency_key"],
                strategy_id=data["strategy_id"],
                strategy_version=data["strategy_version"],
                instrument_key=data["instrument_key"],
                trading_date=datetime.fromisoformat(data["trading_date"]).date(),
                direction=Direction(data["direction"]),
                option_side=OptionSide(data["option_side"]),
                entry_type=EntryType(data["entry_type"]),
                owner_id=data["owner_id"],
                state=ReservationState(data["state"]),
                reserved_at=datetime.fromisoformat(data["reserved_at"]),
                lease_expires_at=datetime.fromisoformat(data["lease_expires_at"]),
                released_at=(
                    datetime.fromisoformat(data["released_at"])
                    if data["released_at"]
                    else None
                ),
                release_reason=data["release_reason"],
                schema_version=data["schema_version"],
            )
        except Exception as exc:
            raise ReservationCorruptionError(
                "reservation payload violates canonical schema"
            ) from exc
        projections: dict[str, object] = {
            "reservation_id": reservation.reservation_id,
            "bundle_id": reservation.bundle_id,
            "owner_id": reservation.owner_id,
            "state": reservation.state.value,
            "reserved_at": reservation.reserved_at.isoformat(),
            "lease_expires_at": reservation.lease_expires_at.isoformat(),
            "released_at": (
                reservation.released_at.isoformat()
                if reservation.released_at
                else None
            ),
            "release_reason": reservation.release_reason,
            "schema_version": reservation.schema_version,
        }
        for field, expected in projections.items():
            if row[field] != expected:
                raise ReservationCorruptionError(
                    f"reservation projection mismatch: {field}"
                )
        return reservation

    @staticmethod
    def _event_metadata(
        reservation: CanonicalBundleReservation,
    ) -> dict[str, object]:
        return {
            "reservation_id": reservation.reservation_id,
            "bundle_id": reservation.bundle_id,
            "state": reservation.state.value,
        }

    @classmethod
    def _event_payload(cls, reservation: CanonicalBundleReservation) -> str:
        return canonical_reservation_json(cls._event_metadata(reservation))

    @classmethod
    def _decode_event(
        cls,
        row: sqlite3.Row,
    ) -> CanonicalReservationLifecycleEvent:
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
                event_timestamp=datetime.fromisoformat(
                    str(row["event_timestamp"])
                ),
                owner_id=str(row["owner_id"]),
                reason_code=str(row["reason_code"]),
                metadata=metadata,
            )
        except Exception as exc:
            raise ReservationCorruptionError(
                "reservation event violates canonical schema"
            ) from exc
        if metadata.get("reservation_id") != event.reservation_id:
            raise ReservationCorruptionError(
                "reservation event metadata mismatch: reservation_id"
            )
        if metadata.get("bundle_id") != event.bundle_id:
            raise ReservationCorruptionError(
                "reservation event metadata mismatch: bundle_id"
            )
        return event

    @classmethod
    def _insert_event(
        cls,
        conn: sqlite3.Connection,
        reservation: CanonicalBundleReservation,
        event_type: ReservationEventType,
        event_at: datetime,
        reason_code: str,
    ) -> None:
        event_id = build_reservation_event_id(
            reservation_id=reservation.reservation_id,
            event_type=event_type.value,
            event_timestamp=event_at,
            owner_id=reservation.owner_id,
            reason_code=reason_code,
        )
        payload = cls._event_payload(reservation)
        values = (
            event_id,
            reservation.reservation_id,
            reservation.bundle_id,
            event_type.value,
            event_at.isoformat(),
            reservation.owner_id,
            reason_code,
            payload,
            reservation_sha256(payload),
        )
        existing = conn.execute(
            "SELECT event_id,reservation_id,bundle_id,event_type,event_timestamp,"
            "owner_id,reason_code,metadata_json,metadata_sha256 "
            "FROM canonical_red_bar_v2_bundle_reservation_events "
            "WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if existing is not None:
            decoded = cls._decode_event(existing)
            expected = CanonicalReservationLifecycleEvent(
                event_id=event_id,
                reservation_id=reservation.reservation_id,
                bundle_id=reservation.bundle_id,
                event_type=event_type,
                event_timestamp=event_at,
                owner_id=reservation.owner_id,
                reason_code=reason_code,
                metadata=cls._event_metadata(reservation),
            )
            if decoded != expected:
                raise ReservationConflictError(
                    "reservation event identity conflict"
                )
            return
        conn.execute(
            "INSERT INTO canonical_red_bar_v2_bundle_reservation_events("
            "event_id,reservation_id,bundle_id,event_type,event_timestamp,"
            "owner_id,reason_code,metadata_json,metadata_sha256) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            values,
        )

    @classmethod
    def _update_terminal(
        cls,
        conn: sqlite3.Connection,
        current: CanonicalBundleReservation,
        terminal: CanonicalBundleReservation,
        updated_at: datetime,
    ) -> None:
        payload = cls._payload(terminal)
        cursor = conn.execute(
            "UPDATE canonical_red_bar_v2_bundle_reservations "
            "SET state=?,released_at=?,release_reason=?,payload_json=?,"
            "payload_sha256=?,updated_at=? "
            "WHERE reservation_id=? AND state=?",
            (
                terminal.state.value,
                terminal.released_at.isoformat()
                if terminal.released_at
                else None,
                terminal.release_reason,
                payload,
                reservation_sha256(payload),
                updated_at.isoformat(),
                current.reservation_id,
                current.state.value,
            ),
        )
        if cursor.rowcount != 1:
            raise ReservationConflictError(
                "reservation state update conflict"
            )

    def reserve(
        self,
        *,
        bundle_id: str,
        owner_id: str,
        requested_at: datetime,
        lease_seconds: int,
        feature_enabled: bool,
        maximum_bundle_age_seconds: float = 120.0,
    ) -> CanonicalReservationResult:
        if not feature_enabled:
            return CanonicalReservationResult(
                ReservationOutcome.RESERVATION_DISABLED,
                "FEATURE_DISABLED",
                None,
            )
        _aware(requested_at, "requested_at")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            bundle_row = conn.execute(
                "SELECT 1 FROM canonical_red_bar_v2_bundles WHERE bundle_id=?",
                (bundle_id,),
            ).fetchone()
            if bundle_row is None:
                conn.execute("ROLLBACK")
                return CanonicalReservationResult(
                    ReservationOutcome.BUNDLE_UNAVAILABLE,
                    "BUNDLE_NOT_FOUND",
                    None,
                )
            verified = verify_canonical_bundle_evidence(
                conn,
                bundle_id=bundle_id,
            )
            bundle = verified.bundle
            eligibility = evaluate_reservation_eligibility(
                bundle=bundle,
                evaluated_at=requested_at,
                feature_enabled=True,
                maximum_age_seconds=maximum_bundle_age_seconds,
                has_bundle_available_event=True,
            )
            if not eligibility.eligible:
                conn.execute("ROLLBACK")
                return CanonicalReservationResult(
                    ReservationOutcome.BUNDLE_INELIGIBLE,
                    eligibility.reason_code,
                    None,
                )
            active_row = conn.execute(
                "SELECT * FROM canonical_red_bar_v2_bundle_reservations "
                "WHERE bundle_id=? AND state='RESERVED'",
                (bundle_id,),
            ).fetchone()
            if active_row is not None:
                current = self._from_row(active_row)
                if requested_at >= current.lease_expires_at:
                    expired = CanonicalBundleReservation(
                        **{
                            **asdict(current),
                            "state": ReservationState.EXPIRED,
                            "released_at": current.lease_expires_at,
                            "release_reason": "LEASE_EXPIRED",
                        }
                    )
                    self._update_terminal(
                        conn,
                        current,
                        expired,
                        requested_at,
                    )
                    self._insert_event(
                        conn,
                        expired,
                        ReservationEventType.RESERVATION_EXPIRED,
                        current.lease_expires_at,
                        "LEASE_EXPIRED",
                    )
                elif current.owner_id == owner_id:
                    conn.execute("COMMIT")
                    return CanonicalReservationResult(
                        ReservationOutcome.IDEMPOTENT_REPLAY,
                        "ACTIVE_OWNER_REPLAY",
                        current,
                    )
                else:
                    conn.execute("COMMIT")
                    return CanonicalReservationResult(
                        ReservationOutcome.ALREADY_RESERVED,
                        "ACTIVE_LEASE_OWNED",
                        current,
                    )
            lease = min(max(int(lease_seconds), 5), 300)
            reservation = CanonicalBundleReservation(
                reservation_id=build_reservation_id(
                    bundle_id=bundle.bundle_id,
                    idempotency_key=bundle.idempotency_key,
                    owner_id=owner_id,
                    lease_epoch=requested_at,
                ),
                bundle_id=bundle.bundle_id,
                signal_id=bundle.signal_id,
                idempotency_key=bundle.idempotency_key,
                strategy_id=bundle.strategy_id,
                strategy_version=bundle.strategy_version,
                instrument_key=bundle.instrument_key or "",
                trading_date=bundle.trading_date,
                direction=bundle.direction,
                option_side=bundle.option_side,
                entry_type=bundle.entry_type,
                owner_id=owner_id,
                state=ReservationState.RESERVED,
                reserved_at=requested_at,
                lease_expires_at=requested_at + timedelta(seconds=lease),
                released_at=None,
                release_reason=None,
            )
            payload = self._payload(reservation)
            stored_at = requested_at.isoformat()
            conn.execute(
                "INSERT INTO canonical_red_bar_v2_bundle_reservations("
                "reservation_id,bundle_id,owner_id,state,reserved_at,"
                "lease_expires_at,released_at,release_reason,schema_version,"
                "payload_json,payload_sha256,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    reservation.reservation_id,
                    reservation.bundle_id,
                    reservation.owner_id,
                    reservation.state.value,
                    reservation.reserved_at.isoformat(),
                    reservation.lease_expires_at.isoformat(),
                    None,
                    None,
                    reservation.schema_version,
                    payload,
                    reservation_sha256(payload),
                    stored_at,
                    stored_at,
                ),
            )
            self._insert_event(
                conn,
                reservation,
                ReservationEventType.RESERVATION_ACQUIRED,
                requested_at,
                "ACQUIRED",
            )
            conn.execute("COMMIT")
            return CanonicalReservationResult(
                ReservationOutcome.ACQUIRED,
                "ACQUIRED",
                reservation,
            )
        except CanonicalPersistenceCorruptionError:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            return CanonicalReservationResult(
                ReservationOutcome.BUNDLE_CORRUPT,
                "BUNDLE_CORRUPT",
                None,
            )
        except ReservationCorruptionError:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            return CanonicalReservationResult(
                ReservationOutcome.RESERVATION_CORRUPT,
                "RESERVATION_CORRUPT",
                None,
            )
        except ReservationConflictError:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            return CanonicalReservationResult(
                ReservationOutcome.RESERVATION_CONFLICT,
                "RESERVATION_CONFLICT",
                None,
            )
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise ReservationStorageError(
                "reservation storage unavailable"
            ) from exc
        finally:
            conn.close()

    def release(
        self,
        *,
        reservation_id: str,
        owner_id: str,
        released_at: datetime,
        reason_code: str,
    ) -> CanonicalReservationResult:
        _aware(released_at, "released_at")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM canonical_red_bar_v2_bundle_reservations "
                "WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return CanonicalReservationResult(
                    ReservationOutcome.BUNDLE_UNAVAILABLE,
                    "RESERVATION_NOT_FOUND",
                    None,
                )
            current = self._from_row(row)
            if current.owner_id != owner_id:
                conn.execute("COMMIT")
                return CanonicalReservationResult(
                    ReservationOutcome.ALREADY_RESERVED,
                    "OWNER_MISMATCH",
                    current,
                )
            if current.state is ReservationState.EXPIRED:
                conn.execute("COMMIT")
                return CanonicalReservationResult(
                    ReservationOutcome.EXPIRED,
                    "LEASE_EXPIRED",
                    current,
                )
            if current.state is ReservationState.RELEASED:
                conn.execute("COMMIT")
                return CanonicalReservationResult(
                    ReservationOutcome.IDEMPOTENT_REPLAY,
                    "ALREADY_RELEASED",
                    current,
                )
            if current.state is not ReservationState.RESERVED:
                conn.execute("COMMIT")
                return CanonicalReservationResult(
                    ReservationOutcome.TERMINAL_REJECTED,
                    "RESERVATION_NOT_ACTIVE",
                    current,
                )
            if released_at < current.reserved_at:
                conn.execute("ROLLBACK")
                return CanonicalReservationResult(
                    ReservationOutcome.INVALID_REQUEST,
                    "RELEASE_BEFORE_RESERVATION",
                    current,
                )
            if released_at >= current.lease_expires_at:
                expired = CanonicalBundleReservation(
                    **{
                        **asdict(current),
                        "state": ReservationState.EXPIRED,
                        "released_at": current.lease_expires_at,
                        "release_reason": "LEASE_EXPIRED",
                    }
                )
                self._update_terminal(
                    conn,
                    current,
                    expired,
                    released_at,
                )
                self._insert_event(
                    conn,
                    expired,
                    ReservationEventType.RESERVATION_EXPIRED,
                    current.lease_expires_at,
                    "LEASE_EXPIRED",
                )
                conn.execute("COMMIT")
                return CanonicalReservationResult(
                    ReservationOutcome.EXPIRED,
                    "LEASE_EXPIRED",
                    expired,
                )
            released = CanonicalBundleReservation(
                **{
                    **asdict(current),
                    "state": ReservationState.RELEASED,
                    "released_at": released_at,
                    "release_reason": reason_code,
                }
            )
            self._update_terminal(
                conn,
                current,
                released,
                released_at,
            )
            self._insert_event(
                conn,
                released,
                ReservationEventType.RESERVATION_RELEASED,
                released_at,
                reason_code,
            )
            conn.execute("COMMIT")
            return CanonicalReservationResult(
                ReservationOutcome.RELEASED,
                reason_code,
                released,
            )
        except ReservationCorruptionError:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            return CanonicalReservationResult(
                ReservationOutcome.RESERVATION_CORRUPT,
                "RESERVATION_CORRUPT",
                None,
            )
        except ReservationConflictError:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            return CanonicalReservationResult(
                ReservationOutcome.RESERVATION_CONFLICT,
                "RESERVATION_CONFLICT",
                None,
            )
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise ReservationStorageError(
                "reservation storage unavailable"
            ) from exc
        finally:
            conn.close()

    def get_active(
        self,
        *,
        bundle_id: str,
        at: datetime,
    ) -> CanonicalBundleReservation | None:
        _aware(at, "at")
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM canonical_red_bar_v2_bundle_reservations "
                    "WHERE bundle_id=? AND state='RESERVED'",
                    (bundle_id,),
                ).fetchone()
            if row is None:
                return None
            reservation = self._from_row(row)
            return (
                reservation
                if at < reservation.lease_expires_at
                else None
            )
        except sqlite3.Error as exc:
            raise ReservationStorageError(
                "reservation storage unavailable"
            ) from exc
