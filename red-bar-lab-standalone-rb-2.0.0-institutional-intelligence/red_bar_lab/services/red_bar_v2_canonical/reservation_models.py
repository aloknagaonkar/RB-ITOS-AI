from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python 3.10 compatibility
    from enum import Enum

    class StrEnum(str, Enum):
        """Compatibility implementation for Python 3.10."""

from red_bar_lab.domain.red_bar_v2 import Direction, EntryType, OptionSide


class ReservationState(StrEnum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class ReservationOutcome(StrEnum):
    ACQUIRED = "ACQUIRED"
    IDEMPOTENT_REPLAY = "IDEMPOTENT_REPLAY"
    ALREADY_RESERVED = "ALREADY_RESERVED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    TERMINAL_REJECTED = "TERMINAL_REJECTED"
    BUNDLE_UNAVAILABLE = "BUNDLE_UNAVAILABLE"
    BUNDLE_CORRUPT = "BUNDLE_CORRUPT"
    BUNDLE_INELIGIBLE = "BUNDLE_INELIGIBLE"
    RESERVATION_DISABLED = "RESERVATION_DISABLED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


class ReservationEventType(StrEnum):
    RESERVATION_ACQUIRED = "RESERVATION_ACQUIRED"
    RESERVATION_RELEASED = "RESERVATION_RELEASED"
    RESERVATION_EXPIRED = "RESERVATION_EXPIRED"
    RESERVATION_REJECTED = "RESERVATION_REJECTED"
    RESERVATION_CONFLICT = "RESERVATION_CONFLICT"


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


@dataclass(frozen=True, slots=True)
class CanonicalBundleReservation:
    reservation_id: str
    bundle_id: str
    signal_id: str
    idempotency_key: str
    strategy_id: str
    strategy_version: str
    instrument_key: str
    trading_date: date
    direction: Direction
    option_side: OptionSide
    entry_type: EntryType
    owner_id: str
    state: ReservationState
    reserved_at: datetime
    lease_expires_at: datetime
    released_at: datetime | None
    release_reason: str | None
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        for name in (
            "reservation_id",
            "bundle_id",
            "signal_id",
            "idempotency_key",
            "strategy_id",
            "strategy_version",
            "instrument_key",
            "owner_id",
            "schema_version",
        ):
            _text(name, getattr(self, name))
        if self.strategy_id != "RED_BAR_V2":
            raise ValueError("strategy_id must be RED_BAR_V2")
        if self.schema_version != "1.0":
            raise ValueError("unsupported reservation schema")
        _aware("reserved_at", self.reserved_at)
        _aware("lease_expires_at", self.lease_expires_at)
        if self.lease_expires_at <= self.reserved_at:
            raise ValueError("lease_expires_at must be later than reserved_at")
        if self.state is ReservationState.RESERVED:
            if self.released_at is not None or self.release_reason is not None:
                raise ValueError("active reservation cannot contain release fields")
        else:
            if self.released_at is None or not self.release_reason:
                raise ValueError("terminal reservation requires release timestamp and reason")
            _aware("released_at", self.released_at)
        from .reservation_identity import build_reservation_id

        expected_id = build_reservation_id(
            bundle_id=self.bundle_id,
            idempotency_key=self.idempotency_key,
            owner_id=self.owner_id,
            lease_epoch=self.reserved_at,
        )
        if self.reservation_id != expected_id:
            raise ValueError("reservation_id does not match canonical lease identity")


@dataclass(frozen=True, slots=True)
class ReservationEligibility:
    eligible: bool
    reason_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class CanonicalReservationResult:
    outcome: ReservationOutcome
    reason_code: str
    reservation: CanonicalBundleReservation | None


@dataclass(frozen=True, slots=True)
class ReservationEvent:
    event_id: str
    reservation_id: str
    bundle_id: str
    event_type: ReservationEventType
    event_timestamp: datetime
    owner_id: str
    reason_code: str

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "reservation_id",
            "bundle_id",
            "owner_id",
            "reason_code",
        ):
            _text(name, getattr(self, name))
        _aware("event_timestamp", self.event_timestamp)
