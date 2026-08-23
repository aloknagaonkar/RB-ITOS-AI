from __future__ import annotations

from datetime import datetime
import logging

from .reservation_models import CanonicalBundleReservation, CanonicalReservationResult, ReservationOutcome
from .reservation_repository import (
    ReservationConflictError,
    ReservationCorruptionError,
    ReservationStorageError,
    ReservationValidationError,
    SQLiteCanonicalReservationRepository,
)

_LOGGER = logging.getLogger(__name__)
OBSERVATIONAL_OWNER_ID = "CANONICAL_RESERVATION_VALIDATOR"
DEFAULT_LEASE_SECONDS = 30
DEFAULT_MAX_BUNDLE_AGE_SECONDS = 120


class RedBarV2CanonicalReservationService:
    def __init__(
        self,
        repository: SQLiteCanonicalReservationRepository | None,
        *,
        enabled: bool,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        maximum_bundle_age_seconds: int = DEFAULT_MAX_BUNDLE_AGE_SECONDS,
    ) -> None:
        self._repository = repository
        self._enabled = bool(enabled)
        self._lease_seconds = min(max(int(lease_seconds), 5), 300)
        self._maximum_bundle_age_seconds = min(max(int(maximum_bundle_age_seconds), 5), 3600)

    @staticmethod
    def _result(outcome: ReservationOutcome, reason: str) -> CanonicalReservationResult:
        return CanonicalReservationResult(outcome, reason, None)

    @staticmethod
    def _valid_text(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _aware(value: object) -> bool:
        return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None

    def reserve(self, *, bundle_id: str, owner_id: str, requested_at: datetime) -> CanonicalReservationResult:
        if not self._valid_text(bundle_id):
            return self._result(ReservationOutcome.INVALID_REQUEST, "INVALID_BUNDLE_ID")
        if not self._valid_text(owner_id):
            return self._result(ReservationOutcome.INVALID_REQUEST, "INVALID_OWNER_ID")
        if not self._aware(requested_at):
            return self._result(ReservationOutcome.INVALID_REQUEST, "NAIVE_REQUEST_TIMESTAMP")
        if not self._enabled or self._repository is None:
            return self._result(ReservationOutcome.RESERVATION_DISABLED, "FEATURE_DISABLED")
        try:
            return self._repository.reserve(
                bundle_id=bundle_id,
                owner_id=owner_id,
                requested_at=requested_at,
                lease_seconds=self._lease_seconds,
                feature_enabled=True,
                maximum_bundle_age_seconds=self._maximum_bundle_age_seconds,
            )
        except ReservationValidationError:
            return self._result(ReservationOutcome.INVALID_REQUEST, "INVALID_REQUEST")
        except ReservationCorruptionError:
            return self._result(ReservationOutcome.RESERVATION_CORRUPT, "RESERVATION_CORRUPT")
        except ReservationConflictError:
            return self._result(ReservationOutcome.RESERVATION_CONFLICT, "RESERVATION_CONFLICT")
        except ReservationStorageError:
            return self._result(ReservationOutcome.STORAGE_UNAVAILABLE, "STORAGE_UNAVAILABLE")
        except Exception as exc:
            _LOGGER.error(
                "canonical_reservation_unexpected_failure exception_class=%s",
                type(exc).__name__,
            )
            return self._result(ReservationOutcome.UNEXPECTED_FAILURE, "UNEXPECTED_RESERVATION_FAILURE")

    def release(
        self,
        *,
        reservation_id: str,
        owner_id: str,
        released_at: datetime,
        reason_code: str,
    ) -> CanonicalReservationResult:
        if not self._valid_text(reservation_id):
            return self._result(ReservationOutcome.INVALID_REQUEST, "INVALID_RESERVATION_ID")
        if not self._valid_text(owner_id):
            return self._result(ReservationOutcome.INVALID_REQUEST, "INVALID_OWNER_ID")
        if not self._aware(released_at):
            return self._result(ReservationOutcome.INVALID_REQUEST, "NAIVE_RELEASE_TIMESTAMP")
        if not self._valid_text(reason_code):
            return self._result(ReservationOutcome.INVALID_REQUEST, "INVALID_RELEASE_REASON")
        if not self._enabled or self._repository is None:
            return self._result(ReservationOutcome.RESERVATION_DISABLED, "FEATURE_DISABLED")
        try:
            return self._repository.release(
                reservation_id=reservation_id,
                owner_id=owner_id,
                released_at=released_at,
                reason_code=reason_code,
            )
        except ReservationValidationError:
            return self._result(ReservationOutcome.INVALID_REQUEST, "INVALID_REQUEST")
        except ReservationCorruptionError:
            return self._result(ReservationOutcome.RESERVATION_CORRUPT, "RESERVATION_CORRUPT")
        except ReservationConflictError:
            return self._result(ReservationOutcome.RESERVATION_CONFLICT, "RESERVATION_CONFLICT")
        except ReservationStorageError:
            return self._result(ReservationOutcome.STORAGE_UNAVAILABLE, "STORAGE_UNAVAILABLE")
        except Exception as exc:
            _LOGGER.error(
                "canonical_reservation_release_unexpected_failure exception_class=%s",
                type(exc).__name__,
            )
            return self._result(ReservationOutcome.UNEXPECTED_FAILURE, "UNEXPECTED_RESERVATION_FAILURE")

    def get_active(self, *, bundle_id: str, at: datetime) -> CanonicalBundleReservation | None:
        if not self._valid_text(bundle_id) or not self._aware(at):
            return None
        if not self._enabled or self._repository is None:
            return None
        try:
            return self._repository.get_active(bundle_id=bundle_id, at=at)
        except (ReservationValidationError, ReservationCorruptionError, ReservationConflictError, ReservationStorageError):
            return None
        except Exception as exc:
            _LOGGER.error(
                "canonical_reservation_active_lookup_failed exception_class=%s",
                type(exc).__name__,
            )
            return None
