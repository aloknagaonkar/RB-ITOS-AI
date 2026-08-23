from __future__ import annotations

from datetime import datetime

from .reservation_models import CanonicalBundleReservation, CanonicalReservationResult
from .reservation_repository import SQLiteCanonicalReservationRepository

OBSERVATIONAL_OWNER_ID = "CANONICAL_RESERVATION_VALIDATOR"
DEFAULT_LEASE_SECONDS = 30


class RedBarV2CanonicalReservationService:
    def __init__(
        self,
        repository: SQLiteCanonicalReservationRepository | None,
        *,
        enabled: bool,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> None:
        self._repository = repository
        self._enabled = bool(enabled)
        self._lease_seconds = min(max(int(lease_seconds), 5), 300)

    def reserve(
        self,
        *,
        bundle_id: str,
        owner_id: str,
        requested_at: datetime,
    ) -> CanonicalReservationResult:
        if self._repository is None:
            from .reservation_models import ReservationOutcome
            return CanonicalReservationResult(ReservationOutcome.RESERVATION_DISABLED, "FEATURE_DISABLED", None)
        return self._repository.reserve(
            bundle_id=bundle_id,
            owner_id=owner_id,
            requested_at=requested_at,
            lease_seconds=self._lease_seconds,
            feature_enabled=self._enabled,
        )

    def release(
        self,
        *,
        reservation_id: str,
        owner_id: str,
        released_at: datetime,
        reason_code: str,
    ) -> CanonicalReservationResult:
        if self._repository is None:
            from .reservation_models import ReservationOutcome
            return CanonicalReservationResult(ReservationOutcome.RESERVATION_DISABLED, "FEATURE_DISABLED", None)
        return self._repository.release(
            reservation_id=reservation_id,
            owner_id=owner_id,
            released_at=released_at,
            reason_code=reason_code,
        )

    def get_active(self, *, bundle_id: str, at: datetime) -> CanonicalBundleReservation | None:
        if self._repository is None:
            return None
        return self._repository.get_active(bundle_id=bundle_id, at=at)
