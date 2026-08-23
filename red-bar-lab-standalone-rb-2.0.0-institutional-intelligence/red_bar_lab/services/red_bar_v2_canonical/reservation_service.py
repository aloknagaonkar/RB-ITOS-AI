from __future__ import annotations

from datetime import datetime

from .reservation_models import (
    CanonicalBundleReservation,
    CanonicalReservationResult,
    ReservationOutcome,
)
from .reservation_repository import (
    ReservationStorageError,
    SQLiteCanonicalReservationRepository,
)

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
        self._maximum_bundle_age_seconds = min(
            max(int(maximum_bundle_age_seconds), 5),
            3600,
        )

    @staticmethod
    def _disabled() -> CanonicalReservationResult:
        return CanonicalReservationResult(
            ReservationOutcome.RESERVATION_DISABLED,
            "FEATURE_DISABLED",
            None,
        )

    @staticmethod
    def _storage_unavailable() -> CanonicalReservationResult:
        return CanonicalReservationResult(
            ReservationOutcome.STORAGE_UNAVAILABLE,
            "STORAGE_UNAVAILABLE",
            None,
        )

    def reserve(
        self,
        *,
        bundle_id: str,
        owner_id: str,
        requested_at: datetime,
    ) -> CanonicalReservationResult:
        if not self._enabled or self._repository is None:
            return self._disabled()
        try:
            return self._repository.reserve(
                bundle_id=bundle_id,
                owner_id=owner_id,
                requested_at=requested_at,
                lease_seconds=self._lease_seconds,
                feature_enabled=True,
                maximum_bundle_age_seconds=self._maximum_bundle_age_seconds,
            )
        except ReservationStorageError:
            return self._storage_unavailable()

    def release(
        self,
        *,
        reservation_id: str,
        owner_id: str,
        released_at: datetime,
        reason_code: str,
    ) -> CanonicalReservationResult:
        if not self._enabled or self._repository is None:
            return self._disabled()
        try:
            return self._repository.release(
                reservation_id=reservation_id,
                owner_id=owner_id,
                released_at=released_at,
                reason_code=reason_code,
            )
        except ReservationStorageError:
            return self._storage_unavailable()

    def get_active(
        self,
        *,
        bundle_id: str,
        at: datetime,
    ) -> CanonicalBundleReservation | None:
        if not self._enabled or self._repository is None:
            return None
        try:
            return self._repository.get_active(bundle_id=bundle_id, at=at)
        except ReservationStorageError:
            return None
