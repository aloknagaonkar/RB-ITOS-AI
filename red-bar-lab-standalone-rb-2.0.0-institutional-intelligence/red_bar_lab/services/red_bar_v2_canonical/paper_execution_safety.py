from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .paper_execution_adapter import CanonicalPaperAdapter, PaperAdapterResult
from .reservation_models import CanonicalReservationResult, ReservationOutcome
from .reservation_service import RedBarV2CanonicalReservationService


@dataclass(frozen=True, slots=True)
class ReservationFinalizationRequired(Exception):
    reservation_id: str
    reason_code: str
    result: CanonicalReservationResult | None


class UncertainPaperAdapterBoundary:
    """Converts adapter operational failures into durable uncertainty inputs."""

    def __init__(self, adapter: CanonicalPaperAdapter) -> None:
        self._adapter = adapter

    def lookup(self, *, execution_id: str) -> PaperAdapterResult | None:
        return self._adapter.lookup(execution_id=execution_id)

    def submit(self, *, command) -> PaperAdapterResult:
        try:
            return self._adapter.submit(command=command)
        except Exception:
            return PaperAdapterResult(
                accepted=False,
                uncertain=True,
                reason_code="PAPER_ADAPTER_EXCEPTION_UNCERTAIN",
                paper_order_id=None,
            )


class VerifiedReservationFinalizationService:
    """Delegates to Change 6 and requires a typed terminal proof."""

    _PROVEN = {
        ReservationOutcome.RELEASED,
        ReservationOutcome.EXPIRED,
    }

    def __init__(self, service: RedBarV2CanonicalReservationService) -> None:
        self._service = service

    def reserve(self, **kwargs):
        return self._service.reserve(**kwargs)

    def release(
        self,
        *,
        reservation_id: str,
        owner_id: str,
        released_at: datetime,
        reason_code: str,
    ) -> CanonicalReservationResult:
        result = self._service.release(
            reservation_id=reservation_id,
            owner_id=owner_id,
            released_at=released_at,
            reason_code=reason_code,
        )
        if result.outcome in self._PROVEN and result.reservation is not None:
            return result
        raise ReservationFinalizationRequired(
            reservation_id=reservation_id,
            reason_code=reason_code,
            result=result,
        )
