from __future__ import annotations

from datetime import datetime
import sqlite3

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
from .reservation_models import ReservationOutcome
from .reservation_service import RedBarV2CanonicalReservationService


class ControlledCanonicalPaperRecoveryService:
    """Reconciles by deterministic lookup only; it never resubmits."""

    _RELEASE_PROVEN = {
        ReservationOutcome.RELEASED,
        ReservationOutcome.EXPIRED,
    }

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

    def _candidate_ids(self, *, limit: int) -> tuple[str, ...]:
        bounded = max(1, min(int(limit), 500))
        ids = list(self.repository.list_non_terminal(limit=bounded))
        for pending in self.repository.list_pending_finalization(limit=bounded):
            if pending.execution_id not in ids:
                ids.append(pending.execution_id)
        return tuple(ids[:bounded])

    def _release(
        self,
        *,
        reservation_id: str,
        at: datetime,
        reason: str,
    ) -> bool:
        result = self.reservation_service.release(
            reservation_id=reservation_id,
            owner_id=self.owner_id,
            released_at=at,
            reason_code=reason,
        )
        return (
            result.outcome in self._RELEASE_PROVEN
            and result.reservation is not None
        )

    def _lookup_fail_closed(self, *, execution_id: str):
        try:
            return self.adapter.lookup(execution_id=execution_id), None
        except (TimeoutError, ConnectionError, sqlite3.Error, OSError):
            return None, "RECOVERY_LOOKUP_UNAVAILABLE"
        except Exception:
            return None, "RECOVERY_LOOKUP_FAILED"

    def _finalize_reservation(
        self,
        *,
        current,
        observed_at: datetime,
        accepted: bool,
        reason_code: str,
    ) -> PaperExecutionResult:
        release_reason = (
            "PAPER_EXECUTION_COMPLETED"
            if accepted
            else "PAPER_EXECUTION_REJECTED"
        )
        if not self._release(
            reservation_id=current.command.reservation_id,
            at=observed_at,
            reason=release_reason,
        ):
            return PaperExecutionResult(
                PaperExecutionOutcome.RECOVERY_REQUIRED,
                f"RESERVATION_FINALIZATION_REQUIRED:{release_reason}",
                command=current.command,
                state=current.state,
                paper_order_id=current.paper_order_id,
            )
        return PaperExecutionResult(
            (
                PaperExecutionOutcome.SUBMISSION_ACCEPTED
                if accepted
                else PaperExecutionOutcome.SUBMISSION_REJECTED
            ),
            reason_code,
            command=current.command,
            state=current.state,
            paper_order_id=current.paper_order_id,
        )

    def recover(
        self,
        *,
        observed_at: datetime,
        limit: int = 100,
    ) -> tuple[PaperExecutionResult, ...]:
        results: list[PaperExecutionResult] = []
        for execution_id in self._candidate_ids(limit=limit):
            try:
                current = self.repository.get_verified(execution_id=execution_id)

                if current.state is PaperExecutionState.PAPER_FILLED:
                    results.append(
                        self._finalize_reservation(
                            current=current,
                            observed_at=observed_at,
                            accepted=True,
                            reason_code="PAPER_EXECUTION_COMPLETED",
                        )
                    )
                    continue
                if current.state is PaperExecutionState.PAPER_REJECTED:
                    results.append(
                        self._finalize_reservation(
                            current=current,
                            observed_at=observed_at,
                            accepted=False,
                            reason_code=current.reason_code,
                        )
                    )
                    continue

                observed, lookup_failure = self._lookup_fail_closed(
                    execution_id=execution_id
                )
                if lookup_failure is not None:
                    results.append(
                        PaperExecutionResult(
                            PaperExecutionOutcome.RECOVERY_REQUIRED,
                            lookup_failure,
                            command=current.command,
                            state=current.state,
                            paper_order_id=current.paper_order_id,
                        )
                    )
                    continue
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
                            paper_order_id=observed.paper_order_id,
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
                    results.append(
                        self._finalize_reservation(
                            current=current,
                            observed_at=observed_at,
                            accepted=True,
                            reason_code=observed.reason_code,
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
                results.append(
                    self._finalize_reservation(
                        current=current,
                        observed_at=observed_at,
                        accepted=False,
                        reason_code=observed.reason_code,
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
