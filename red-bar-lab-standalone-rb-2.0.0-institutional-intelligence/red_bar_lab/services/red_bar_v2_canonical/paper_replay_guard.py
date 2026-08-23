from __future__ import annotations

from datetime import datetime

from .paper_execution_ledger import StrictSQLiteCanonicalPaperExecutionRepository
from .paper_execution_models import PaperExecutionMode, PaperExecutionOutcome, PaperExecutionResult
from .paper_execution_service import CanonicalPaperExecutionService


class _SelectedContractSelector:
    """Reuse one already-validated selection without repeating market-data work."""

    def __init__(self, contract) -> None:
        self._contract = contract

    def select(self, **kwargs):
        return self._contract


class ReplayGuardedCanonicalPaperService(CanonicalPaperExecutionService):
    """Returns verified persisted paper evidence before acquiring another lease."""

    repository: StrictSQLiteCanonicalPaperExecutionRepository | None

    def execute(
        self,
        *,
        bundle_id: str,
        spot_price: float,
        requested_at: datetime,
        quantity_lots: int = 1,
    ) -> PaperExecutionResult:
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

                # Contract compatibility is a pre-reservation admission rule.
                # A wrong CE/PE contract is terminal input rejection and must not
                # create an active lease that then needs compensating cleanup.
                if self.selector is not None:
                    contract = self.selector.select(
                        option_side=canonical.bundle.option_side.value,
                        spot_price=float(spot_price),
                        selected_at=requested_at,
                    )
                    if contract is None:
                        return PaperExecutionResult(
                            PaperExecutionOutcome.CONTRACT_UNAVAILABLE,
                            "CONTRACT_UNAVAILABLE",
                        )
                    if contract.option_side is not canonical.bundle.option_side:
                        return PaperExecutionResult(
                            PaperExecutionOutcome.INVALID_REQUEST,
                            "CONTRACT_OPTION_SIDE_MISMATCH",
                        )

                    guarded = CanonicalPaperExecutionService(
                        database_path=self.database_path,
                        repository=self.repository,
                        reservation_service=self.reservation_service,
                        selector=_SelectedContractSelector(contract),
                        adapter=self.adapter,
                        enabled=self.enabled,
                        mode=self.mode.value,
                        owner_id=self.owner_id,
                    )
                    return guarded.execute(
                        bundle_id=bundle_id,
                        spot_price=spot_price,
                        requested_at=requested_at,
                        quantity_lots=quantity_lots,
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
