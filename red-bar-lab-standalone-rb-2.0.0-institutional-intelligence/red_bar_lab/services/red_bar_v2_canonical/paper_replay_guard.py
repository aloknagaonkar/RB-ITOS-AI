from __future__ import annotations

from datetime import datetime

from .paper_execution_ledger import StrictSQLiteCanonicalPaperExecutionRepository
from .paper_execution_models import PaperExecutionMode, PaperExecutionOutcome, PaperExecutionResult
from .paper_execution_service import CanonicalPaperExecutionService


class ReplayGuardedCanonicalPaperService(CanonicalPaperExecutionService):
    """Returns verified persisted paper evidence before acquiring another lease."""

    repository: StrictSQLiteCanonicalPaperExecutionRepository | None

    def execute(self, *, bundle_id: str, spot_price: float, requested_at: datetime, quantity_lots: int = 1) -> PaperExecutionResult:
        if self.enabled and self.mode is PaperExecutionMode.PAPER_CANARY:
            try:
                canonical = self._read_canonical(bundle_id=bundle_id)
                if self.repository is not None:
                    previous = self.repository.find_by_idempotency_key(
                        idempotency_key=canonical.bundle.idempotency_key
                    )
                    if previous is not None:
                        return PaperExecutionResult(
                            PaperExecutionOutcome.IDEMPOTENT_REPLAY,
                            "IDEMPOTENT_REPLAY",
                            command=previous.command,
                            state=previous.state,
                            paper_order_id=previous.paper_order_id,
                        )
            except LookupError:
                return PaperExecutionResult(
                    PaperExecutionOutcome.BUNDLE_UNAVAILABLE,
                    "BUNDLE_NOT_FOUND",
                )
            except Exception as exc:
                if exc.__class__.__name__.endswith("CorruptionError"):
                    return PaperExecutionResult(
                        PaperExecutionOutcome.BUNDLE_CORRUPT,
                        "BUNDLE_CORRUPT",
                    )
        return super().execute(
            bundle_id=bundle_id,
            spot_price=spot_price,
            requested_at=requested_at,
            quantity_lots=quantity_lots,
        )
