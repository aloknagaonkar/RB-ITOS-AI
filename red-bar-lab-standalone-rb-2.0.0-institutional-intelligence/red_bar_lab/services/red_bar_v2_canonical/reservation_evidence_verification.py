from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3

from red_bar_lab.domain.red_bar_v2 import Direction, EntryType, OptionSide

from .reservation_identity import reservation_sha256
from .reservation_models import (
    CanonicalBundleReservation,
    CanonicalReservationLifecycleEvent,
    ReservationEventType,
    ReservationState,
)


class ReservationCorruptionError(Exception):
    """Persisted reservation row or lifecycle evidence is inconsistent."""


@dataclass(frozen=True, slots=True)
class VerifiedReservationEvidence:
    reservation: CanonicalBundleReservation
    events: tuple[CanonicalReservationLifecycleEvent, ...]


def _aware_iso(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception as exc:
        raise ReservationCorruptionError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReservationCorruptionError(f"naive {field}")
    return parsed


def _same_instant(left: datetime, right: datetime) -> bool:
    return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)


def _decode_reservation(row: sqlite3.Row) -> CanonicalBundleReservation:
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
            reserved_at=_aware_iso(data["reserved_at"], "reserved_at"),
            lease_expires_at=_aware_iso(data["lease_expires_at"], "lease_expires_at"),
            released_at=(
                _aware_iso(data["released_at"], "released_at")
                if data.get("released_at")
                else None
            ),
            release_reason=data.get("release_reason"),
            schema_version=data["schema_version"],
        )
    except ReservationCorruptionError:
        raise
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
            reservation.released_at.isoformat() if reservation.released_at else None
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
            event_timestamp=_aware_iso(
                row["event_timestamp"], "reservation event_timestamp"
            ),
            owner_id=str(row["owner_id"]),
            reason_code=str(row["reason_code"]),
            metadata=metadata,
        )
    except ReservationCorruptionError:
        raise
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
    expected_state = {
        ReservationEventType.RESERVATION_ACQUIRED: ReservationState.RESERVED.value,
        ReservationEventType.RESERVATION_RELEASED: ReservationState.RELEASED.value,
        ReservationEventType.RESERVATION_EXPIRED: ReservationState.EXPIRED.value,
        ReservationEventType.RESERVATION_REJECTED: ReservationState.REJECTED.value,
    }.get(event.event_type)
    if expected_state is None or metadata.get("state") != expected_state:
        raise ReservationCorruptionError(
            "reservation event metadata mismatch: state"
        )
    return event


def _validate_chain(
    reservation: CanonicalBundleReservation,
    events: tuple[CanonicalReservationLifecycleEvent, ...],
) -> None:
    if not events:
        raise ReservationCorruptionError(
            "reservation has no lifecycle event history"
        )
    previous_timestamp: datetime | None = None
    for event in events:
        if event.reservation_id != reservation.reservation_id:
            raise ReservationCorruptionError(
                "reservation event reservation mismatch"
            )
        if event.bundle_id != reservation.bundle_id:
            raise ReservationCorruptionError("reservation event bundle mismatch")
        if event.owner_id != reservation.owner_id:
            raise ReservationCorruptionError("reservation event owner mismatch")
        if event.event_timestamp < reservation.reserved_at:
            raise ReservationCorruptionError(
                "reservation event precedes reservation"
            )
        if (
            previous_timestamp is not None
            and event.event_timestamp < previous_timestamp
        ):
            raise ReservationCorruptionError(
                "reservation event chronology mismatch"
            )
        previous_timestamp = event.event_timestamp

    acquired = [
        event
        for event in events
        if event.event_type is ReservationEventType.RESERVATION_ACQUIRED
    ]
    if (
        len(acquired) != 1
        or events[0].event_type is not ReservationEventType.RESERVATION_ACQUIRED
    ):
        raise ReservationCorruptionError(
            "reservation requires exactly one first acquired event"
        )
    if not _same_instant(acquired[0].event_timestamp, reservation.reserved_at):
        raise ReservationCorruptionError("acquired event timestamp mismatch")

    terminal_types = {
        ReservationEventType.RESERVATION_RELEASED,
        ReservationEventType.RESERVATION_EXPIRED,
        ReservationEventType.RESERVATION_REJECTED,
    }
    terminal = [event for event in events if event.event_type in terminal_types]
    if len(terminal) > 1:
        raise ReservationCorruptionError(
            "reservation has multiple terminal lifecycle events"
        )
    if terminal and events[-1] != terminal[0]:
        raise ReservationCorruptionError(
            "reservation has events after terminal transition"
        )

    if reservation.state is ReservationState.RESERVED:
        if terminal:
            raise ReservationCorruptionError(
                "reserved state conflicts with terminal lifecycle event"
            )
        return
    if reservation.state is ReservationState.REJECTED:
        raise ReservationCorruptionError(
            "rejected reservation workflow is unsupported"
        )
    if (
        len(terminal) != 1
        or reservation.released_at is None
        or reservation.release_reason is None
    ):
        raise ReservationCorruptionError(
            "terminal reservation lifecycle event missing"
        )

    event = terminal[0]
    if reservation.state is ReservationState.RELEASED:
        if event.event_type is not ReservationEventType.RESERVATION_RELEASED:
            raise ReservationCorruptionError(
                "released state lifecycle mismatch"
            )
        if not _same_instant(event.event_timestamp, reservation.released_at):
            raise ReservationCorruptionError(
                "released event timestamp mismatch"
            )
        if event.reason_code != reservation.release_reason:
            raise ReservationCorruptionError("released event reason mismatch")
        if event.event_timestamp >= reservation.lease_expires_at:
            raise ReservationCorruptionError(
                "released event occurred after lease expiry"
            )
    elif reservation.state is ReservationState.EXPIRED:
        if event.event_type is not ReservationEventType.RESERVATION_EXPIRED:
            raise ReservationCorruptionError(
                "expired state lifecycle mismatch"
            )
        if not _same_instant(
            event.event_timestamp, reservation.lease_expires_at
        ):
            raise ReservationCorruptionError(
                "expired event timestamp mismatch"
            )
        if (
            event.reason_code != "LEASE_EXPIRED"
            or reservation.release_reason != "LEASE_EXPIRED"
        ):
            raise ReservationCorruptionError("expired event reason mismatch")
        if not _same_instant(
            reservation.released_at, reservation.lease_expires_at
        ):
            raise ReservationCorruptionError(
                "expired terminal timestamp mismatch"
            )


def verify_reservation_evidence(
    conn: sqlite3.Connection,
    *,
    reservation_id: str,
    expected_bundle_id: str | None = None,
) -> VerifiedReservationEvidence:
    row = conn.execute(
        "SELECT reservation_id,bundle_id,owner_id,state,reserved_at,"
        "lease_expires_at,released_at,release_reason,schema_version,"
        "payload_json,payload_sha256 "
        "FROM canonical_red_bar_v2_bundle_reservations "
        "WHERE reservation_id=?",
        (reservation_id,),
    ).fetchone()
    if row is None:
        raise ReservationCorruptionError("reservation row missing")
    reservation = _decode_reservation(row)
    if (
        expected_bundle_id is not None
        and reservation.bundle_id != expected_bundle_id
    ):
        raise ReservationCorruptionError("reservation bundle mismatch")
    rows = conn.execute(
        "SELECT event_id,reservation_id,bundle_id,event_type,event_timestamp,"
        "owner_id,reason_code,metadata_json,metadata_sha256 "
        "FROM canonical_red_bar_v2_bundle_reservation_events "
        "WHERE reservation_id=? "
        "ORDER BY event_timestamp ASC, "
        "CASE event_type "
        "WHEN 'RESERVATION_ACQUIRED' THEN 10 "
        "WHEN 'RESERVATION_RELEASED' THEN 20 "
        "WHEN 'RESERVATION_EXPIRED' THEN 20 "
        "WHEN 'RESERVATION_REJECTED' THEN 20 "
        "ELSE 999 END ASC, event_id ASC",
        (reservation_id,),
    ).fetchall()
    events = tuple(_decode_event(item) for item in rows)
    _validate_chain(reservation, events)
    return VerifiedReservationEvidence(
        reservation=reservation,
        events=events,
    )
