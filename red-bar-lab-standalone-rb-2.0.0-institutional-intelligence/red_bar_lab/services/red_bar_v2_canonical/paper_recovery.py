from __future__ import annotations

from datetime import datetime

from .paper_execution_adapter import CanonicalPaperAdapter
from .paper_execution_ledger import StrictSQLiteCanonicalPaperExecutionRepository
from .paper_execution_models import (
    PaperExecutionEventType,
    PaperExecutionOutcome,
    PaperExecutionResult,
    PaperExecutionState,
)
from .paper_execution_repository import (
    PaperExecutionConflictError,
    PaperExecutionCorruptionError,
    PaperExecutionStorageError,
)
from .paper_execution_service import CANONICAL_PAPER_WORKER_OWNER
from .reservation_service import RedBarV2CanonicalReservationService


class ControlledCanonicalPaperRecoveryService:
    """Reconciles persisted intents by lookup only; it never blindly resubmits."""

    def __init__(
        self,
        *,
        repository: StrictSQLiteCanonicalPaperExecutionRepository,
        adapter: CanonicalPaperAdapter,
        reservation_service: RedBarV2CanonicalReservationService,
        owner_id: str = CANONICAL_PAPER_WORKER_OWNER,
    ) -> None:
        self.repository = repository
        self.adapter = adapter
        self.reservation_service = reservation_service
        self.owner_id = owner_id

    def _release(
        self,
        *,
        reservation_id: str,
        at: datetime,
        reason: str,
    ) -> None:
        self.reservation_service.release(
            reservation_id=reservation_id,
            owner_id=self.owner_id,
            released_at=at,
            reason_code=reason,
        )

    def recover(
        self,
        *,
        observed_at: datetime,
        limit: int = 100,
    ) -> tuple[PaperExecutionResult, ...]:
        results: list[PaperExecutionResult] = []
        for execution_id in self.repository.list_non_terminal(limit=limit):
            try:
                current = self.repository.get_verified(execution_id=execution_id)
                observed = self.adapter.lookup(execution_id=execution_id)
                if observed is None:
                    results.append(
                        PaperExecutionResult(
                            PaperExecutionOutcome.RECOVERY_REQUIRED,
                            "NO_PROVEN_PAPER_RESULT",
                            command=current.command,
                            state=current.state,
                        )
                    )
                    continue
                if observed.uncertain:
                    results.append(
                        PaperExecutionResult(
                            PaperExecutionOutcome.SUBMISSION_UNCERTAIN,
                            observed.reason_code,
                            command=current.command,
                            state=current.state,
                        )
                    )
                    continue

                if current.state is PaperExecutionState.PREPARED:
                    current = self.repository.transition(
                        execution_id=execution_id,
                        expected_state=PaperExecutionState.PREPARED,
                        new_state=PaperExecutionState.SUBMISSION_STARTED,
                        event_type=PaperExecutionEventType.SUBMISSION_STARTED,
                        at=observed_at,
                        reason_code="RECOVERY_EXISTING_RESULT_FOUND",
                    )

                if observed.accepted:
                    if current.state in {
                        PaperExecutionState.SUBMISSION_STARTED,
                        PaperExecutionState.SUBMISSION_UNCERTAIN,
                        PaperExecutionState.RECOVERY_REQUIRED,
                    }:
                        current = self.repository.transition(
                            execution_id=execution_id,
                            expected_state=current.state,
                            new_state=PaperExecutionState.PAPER_ACCEPTED,
                            event_type=PaperExecutionEventType.PAPER_ACCEPTED,
                            at=observed_at,
                            reason_code=observed.reason_code,
                            paper_order_id=observed.paper_order_id,
                        )
                    if current.state is PaperExecutionState.PAPER_ACCEPTED:
                        current = self.repository.transition(
                            execution_id=execution_id,
                            expected_state=PaperExecutionState.PAPER_ACCEPTED,
                            new_state=PaperExecutionState.PAPER_FILLED,
                            event_type=PaperExecutionEventType.PAPER_FILLED,
                            at=observed_at,
                            reason_code="PAPER_EXECUTION_COMPLETED",
                            paper_order_id=observed.paper_order_id,
                        )
                    self._release(
                        reservation_id=current.command.reservation_id,
                        at=observed_at,
                        reason="PAPER_EXECUTION_COMPLETED",
                    )
                    results.append(
                        PaperExecutionResult(
                            PaperExecutionOutcome.SUBMISSION_ACCEPTED,
                            observed.reason_code,
                            command=current.command,
                            state=current.state,
                            paper_order_id=current.paper_order_id,
                        )
                    )
                    continue

                if current.state in {
                    PaperExecutionState.SUBMISSION_STARTED,
                    PaperExecutionState.SUBMISSION_UNCERTAIN,
                    PaperExecutionState.RECOVERY_REQUIRED,
                }:
                    current = self.repository.transition(
                        execution_id=execution_id,
                        expected_state=current.state,
                        new_state=PaperExecutionState.PAPER_REJECTED,
                        event_type=PaperExecutionEventType.PAPER_REJECTED,
                        at=observed_at,
                        reason_code=observed.reason_code,
                        paper_order_id=observed.paper_order_id,
                    )
                self._release(
                    reservation_id=current.command.reservation_id,
                    at=observed_at,
                    reason="PAPER_EXECUTION_REJECTED",
                )
                results.append(
                    PaperExecutionResult(
                        PaperExecutionOutcome.SUBMISSION_REJECTED,
                        observed.reason_code,
                        command=current.command,
                        state=current.state,
                        paper_order_id=current.paper_order_id,
                    )
                )
            except (
                PaperExecutionCorruptionError,
                PaperExecutionConflictError,
                PaperExecutionStorageError,
            ):
                results.append(
                    PaperExecutionResult(
                        PaperExecutionOutcome.RECOVERY_REQUIRED,
                        "RECOVERY_VERIFICATION_FAILED",
                    )
                )
        return tuple(results)
