from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3

from .canonical_evidence_verification import verify_canonical_bundle_evidence
from .paper_execution_adapter import CanonicalContractSelector, CanonicalPaperAdapter
from .paper_execution_identity import build_command_id, build_execution_id, payload_sha256
from .paper_execution_models import (
    CanonicalPaperExecutionCommand,
    PaperExecutionEventType,
    PaperExecutionMode,
    PaperExecutionOutcome,
    PaperExecutionResult,
    PaperExecutionState,
)
from .paper_execution_repository import (
    PaperExecutionConflictError,
    PaperExecutionCorruptionError,
    PaperExecutionStorageError,
    SQLiteCanonicalPaperExecutionRepository,
    command_payload,
)
from .reservation_evidence_verification import ReservationCorruptionError, verify_reservation_evidence
from .reservation_models import ReservationOutcome, ReservationState
from .reservation_service import RedBarV2CanonicalReservationService

CANONICAL_PAPER_WORKER_OWNER = "CANONICAL_RED_BAR_V2_PAPER_WORKER"


class CanonicalPaperExecutionService:
    def __init__(
        self,
        *,
        database_path: Path,
        repository: SQLiteCanonicalPaperExecutionRepository | None,
        reservation_service: RedBarV2CanonicalReservationService | None,
        selector: CanonicalContractSelector | None,
        adapter: CanonicalPaperAdapter | None,
        enabled: bool,
        mode: str,
        owner_id: str = CANONICAL_PAPER_WORKER_OWNER,
    ) -> None:
        self.database_path = Path(database_path)
        self.repository = repository
        self.reservation_service = reservation_service
        self.selector = selector
        self.adapter = adapter
        self.enabled = bool(enabled)
        try:
            self.mode: PaperExecutionMode | None = PaperExecutionMode(str(mode).upper())
        except ValueError:
            self.mode = None
        self.owner_id = owner_id

    @staticmethod
    def _result(outcome: PaperExecutionOutcome, reason: str, **kwargs) -> PaperExecutionResult:
        return PaperExecutionResult(outcome=outcome, reason_code=reason, **kwargs)

    def _release(self, *, reservation_id: str, released_at: datetime, reason: str) -> None:
        if self.reservation_service is not None:
            self.reservation_service.release(
                reservation_id=reservation_id,
                owner_id=self.owner_id,
                released_at=released_at,
                reason_code=reason,
            )

    def _read_canonical(self, *, bundle_id: str):
        with sqlite3.connect(
            f"file:{self.database_path.resolve().as_posix()}?mode=ro",
            uri=True,
        ) as conn:
            conn.row_factory = sqlite3.Row
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='canonical_red_bar_v2_bundles'"
            ).fetchone()
            if table is None:
                raise RuntimeError("MISSING_CANONICAL_BUNDLE_TABLE")
            row = conn.execute(
                "SELECT 1 FROM canonical_red_bar_v2_bundles WHERE bundle_id=?",
                (bundle_id,),
            ).fetchone()
            if row is None:
                raise LookupError("BUNDLE_NOT_FOUND")
            return verify_canonical_bundle_evidence(conn, bundle_id=bundle_id)

    def _guarded_prepare(
        self,
        *,
        bundle_id: str,
        reservation_id: str,
        contract,
        quantity: int,
        now: datetime,
    ):
        if self.repository is None:
            raise PaperExecutionStorageError("paper execution repository unavailable")
        conn = self.repository._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            canonical = verify_canonical_bundle_evidence(conn, bundle_id=bundle_id)
            reservation_evidence = verify_reservation_evidence(
                conn,
                reservation_id=reservation_id,
                expected_bundle_id=bundle_id,
            )
            reservation = reservation_evidence.reservation
            bundle = canonical.bundle
            if reservation.state is not ReservationState.RESERVED:
                raise ReservationCorruptionError("reservation is not active")
            if reservation.owner_id != self.owner_id:
                raise PermissionError("reservation owner mismatch")
            if now >= reservation.lease_expires_at:
                raise TimeoutError("reservation expired")
            if bundle.strategy_id != "RED_BAR_V2":
                raise ValueError("wrong strategy")
            if contract.option_side is not bundle.option_side:
                raise ValueError("contract option side mismatch")
            execution_id = build_execution_id(
                bundle_id=bundle.bundle_id,
                reservation_id=reservation.reservation_id,
                contract_instrument_key=contract.instrument_key,
                quantity=quantity,
                order_side="BUY",
                order_type="MARKET",
                limit_price=None,
            )
            command = CanonicalPaperExecutionCommand(
                command_id=build_command_id(execution_id=execution_id, created_at=now),
                execution_id=execution_id,
                reservation_id=reservation.reservation_id,
                bundle_id=bundle.bundle_id,
                signal_id=bundle.signal_id,
                idempotency_key=bundle.idempotency_key,
                strategy_id=bundle.strategy_id,
                strategy_version=bundle.strategy_version,
                instrument_key=bundle.instrument_key or "",
                trading_date=bundle.trading_date,
                direction=bundle.direction,
                option_side=bundle.option_side,
                entry_type=bundle.entry_type,
                signal_timestamp=bundle.evaluation_timestamp,
                reservation_owner=reservation.owner_id,
                reservation_expiry=reservation.lease_expires_at,
                contract=contract,
                quantity=quantity,
                order_side="BUY",
                order_type="MARKET",
                limit_price=None,
                created_at=now,
            )
            existing = conn.execute(
                "SELECT execution_id FROM canonical_red_bar_v2_paper_commands "
                "WHERE idempotency_key=?",
                (command.idempotency_key,),
            ).fetchone()
            if existing is not None:
                conn.execute("COMMIT")
                return self.repository.get_verified(
                    execution_id=str(existing["execution_id"])
                ), True
            payload = command_payload(command)
            conn.execute(
                "INSERT INTO canonical_red_bar_v2_paper_commands("
                "command_id,execution_id,reservation_id,bundle_id,signal_id,"
                "idempotency_key,state,paper_order_id,reason_code,created_at,"
                "updated_at,schema_version,payload_json,payload_sha256) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    command.command_id,
                    command.execution_id,
                    command.reservation_id,
                    command.bundle_id,
                    command.signal_id,
                    command.idempotency_key,
                    PaperExecutionState.PREPARED.value,
                    None,
                    "COMMAND_PREPARED",
                    now.isoformat(),
                    now.isoformat(),
                    command.schema_version,
                    payload,
                    payload_sha256(payload),
                ),
            )
            self.repository._insert_event(
                conn,
                command=command,
                event_type=PaperExecutionEventType.COMMAND_PREPARED,
                at=now,
                reason_code="COMMAND_PREPARED",
                paper_order_id=None,
            )
            conn.execute("COMMIT")
            return self.repository.get_verified(execution_id=command.execution_id), False
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def execute(
        self,
        *,
        bundle_id: str,
        spot_price: float,
        requested_at: datetime,
        quantity_lots: int = 1,
    ) -> PaperExecutionResult:
        if not self.enabled:
            return self._result(PaperExecutionOutcome.FEATURE_DISABLED, "FEATURE_DISABLED")
        if self.mode is not PaperExecutionMode.PAPER_CANARY:
            return self._result(PaperExecutionOutcome.OBSERVE_ONLY, "OBSERVE_ONLY")
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            return self._result(PaperExecutionOutcome.INVALID_REQUEST, "NAIVE_REQUEST_TIMESTAMP")
        if not bundle_id or spot_price <= 0 or quantity_lots <= 0:
            return self._result(PaperExecutionOutcome.INVALID_REQUEST, "INVALID_EXECUTION_REQUEST")
        if not all((self.repository, self.reservation_service, self.selector, self.adapter)):
            return self._result(PaperExecutionOutcome.STORAGE_UNAVAILABLE, "DEPENDENCY_UNAVAILABLE")

        try:
            canonical = self._read_canonical(bundle_id=bundle_id)
            contract = self.selector.select(
                option_side=canonical.bundle.option_side.value,
                spot_price=float(spot_price),
                selected_at=requested_at,
            )
        except LookupError:
            return self._result(PaperExecutionOutcome.BUNDLE_UNAVAILABLE, "BUNDLE_NOT_FOUND")
        except RuntimeError as exc:
            if str(exc) == "MISSING_CANONICAL_BUNDLE_TABLE":
                return self._result(PaperExecutionOutcome.BUNDLE_CORRUPT, str(exc))
            return self._result(PaperExecutionOutcome.STORAGE_UNAVAILABLE, "CANONICAL_READ_UNAVAILABLE")
        except Exception as exc:
            if exc.__class__.__name__.endswith("CorruptionError"):
                return self._result(PaperExecutionOutcome.BUNDLE_CORRUPT, "BUNDLE_CORRUPT")
            return self._result(PaperExecutionOutcome.STORAGE_UNAVAILABLE, "CANONICAL_READ_UNAVAILABLE")
        if contract is None:
            return self._result(PaperExecutionOutcome.CONTRACT_UNAVAILABLE, "CONTRACT_UNAVAILABLE")
        quantity = contract.lot_size * int(quantity_lots)

        reserved = self.reservation_service.reserve(
            bundle_id=bundle_id,
            owner_id=self.owner_id,
            requested_at=requested_at,
        )
        if reserved.outcome not in {
            ReservationOutcome.ACQUIRED,
            ReservationOutcome.IDEMPOTENT_REPLAY,
        } or reserved.reservation is None:
            mapping = {
                ReservationOutcome.BUNDLE_UNAVAILABLE: PaperExecutionOutcome.BUNDLE_UNAVAILABLE,
                ReservationOutcome.BUNDLE_CORRUPT: PaperExecutionOutcome.BUNDLE_CORRUPT,
                ReservationOutcome.BUNDLE_INELIGIBLE: PaperExecutionOutcome.BUNDLE_INELIGIBLE,
                ReservationOutcome.RESERVATION_CORRUPT: PaperExecutionOutcome.RESERVATION_CORRUPT,
                ReservationOutcome.EXPIRED: PaperExecutionOutcome.RESERVATION_EXPIRED,
                ReservationOutcome.ALREADY_RESERVED: PaperExecutionOutcome.RESERVATION_OWNER_MISMATCH,
                ReservationOutcome.STORAGE_UNAVAILABLE: PaperExecutionOutcome.STORAGE_UNAVAILABLE,
            }
            return self._result(
                mapping.get(reserved.outcome, PaperExecutionOutcome.RESERVATION_UNAVAILABLE),
                reserved.reason_code,
            )

        reservation_id = reserved.reservation.reservation_id
        try:
            prepared, replay = self._guarded_prepare(
                bundle_id=bundle_id,
                reservation_id=reservation_id,
                contract=contract,
                quantity=quantity,
                now=requested_at,
            )
        except PermissionError:
            return self._result(
                PaperExecutionOutcome.RESERVATION_OWNER_MISMATCH,
                "RESERVATION_OWNER_MISMATCH",
            )
        except TimeoutError:
            return self._result(
                PaperExecutionOutcome.RESERVATION_EXPIRED,
                "RESERVATION_EXPIRED",
            )
        except ReservationCorruptionError:
            return self._result(
                PaperExecutionOutcome.RESERVATION_CORRUPT,
                "RESERVATION_CORRUPT",
            )
        except PaperExecutionConflictError:
            return self._result(PaperExecutionOutcome.IDEMPOTENT_REPLAY, "IDEMPOTENT_REPLAY")
        except PaperExecutionStorageError:
            return self._result(PaperExecutionOutcome.STORAGE_UNAVAILABLE, "STORAGE_UNAVAILABLE")
        except Exception as exc:
            self._release(
                reservation_id=reservation_id,
                released_at=requested_at,
                reason="PAPER_CONSTRUCTION_REJECTED",
            )
            if exc.__class__.__name__.endswith("CorruptionError"):
                return self._result(PaperExecutionOutcome.BUNDLE_CORRUPT, "BUNDLE_CORRUPT")
            return self._result(PaperExecutionOutcome.INVALID_REQUEST, type(exc).__name__.upper())
        if replay:
            return self._result(
                PaperExecutionOutcome.IDEMPOTENT_REPLAY,
                "IDEMPOTENT_REPLAY",
                command=prepared.command,
                state=prepared.state,
                paper_order_id=prepared.paper_order_id,
            )

        started = self.repository.transition(
            execution_id=prepared.command.execution_id,
            expected_state=PaperExecutionState.PREPARED,
            new_state=PaperExecutionState.SUBMISSION_STARTED,
            event_type=PaperExecutionEventType.SUBMISSION_STARTED,
            at=requested_at,
            reason_code="SUBMISSION_STARTED",
        )
        adapter_result = self.adapter.submit(command=started.command)
        if adapter_result.uncertain:
            uncertain = self.repository.transition(
                execution_id=started.command.execution_id,
                expected_state=PaperExecutionState.SUBMISSION_STARTED,
                new_state=PaperExecutionState.SUBMISSION_UNCERTAIN,
                event_type=PaperExecutionEventType.SUBMISSION_UNCERTAIN,
                at=requested_at,
                reason_code=adapter_result.reason_code,
                paper_order_id=adapter_result.paper_order_id,
            )
            return self._result(
                PaperExecutionOutcome.SUBMISSION_UNCERTAIN,
                adapter_result.reason_code,
                command=uncertain.command,
                state=uncertain.state,
                paper_order_id=uncertain.paper_order_id,
            )
        if not adapter_result.accepted:
            rejected = self.repository.transition(
                execution_id=started.command.execution_id,
                expected_state=PaperExecutionState.SUBMISSION_STARTED,
                new_state=PaperExecutionState.PAPER_REJECTED,
                event_type=PaperExecutionEventType.PAPER_REJECTED,
                at=requested_at,
                reason_code=adapter_result.reason_code,
                paper_order_id=adapter_result.paper_order_id,
            )
            self._release(
                reservation_id=reservation_id,
                released_at=requested_at,
                reason="PAPER_EXECUTION_REJECTED",
            )
            return self._result(
                PaperExecutionOutcome.SUBMISSION_REJECTED,
                adapter_result.reason_code,
                command=rejected.command,
                state=rejected.state,
                paper_order_id=rejected.paper_order_id,
            )

        accepted = self.repository.transition(
            execution_id=started.command.execution_id,
            expected_state=PaperExecutionState.SUBMISSION_STARTED,
            new_state=PaperExecutionState.PAPER_ACCEPTED,
            event_type=PaperExecutionEventType.PAPER_ACCEPTED,
            at=requested_at,
            reason_code=adapter_result.reason_code,
            paper_order_id=adapter_result.paper_order_id,
        )
        filled = self.repository.transition(
            execution_id=accepted.command.execution_id,
            expected_state=PaperExecutionState.PAPER_ACCEPTED,
            new_state=PaperExecutionState.PAPER_FILLED,
            event_type=PaperExecutionEventType.PAPER_FILLED,
            at=requested_at,
            reason_code="PAPER_EXECUTION_COMPLETED",
            paper_order_id=adapter_result.paper_order_id,
        )
        self._release(
            reservation_id=reservation_id,
            released_at=requested_at,
            reason="PAPER_EXECUTION_COMPLETED",
        )
        return self._result(
            PaperExecutionOutcome.SUBMISSION_ACCEPTED,
            adapter_result.reason_code,
            command=filled.command,
            state=filled.state,
            paper_order_id=filled.paper_order_id,
        )


class CanonicalPaperExecutionRecoveryService:
    def __init__(
        self,
        *,
        repository: SQLiteCanonicalPaperExecutionRepository,
        adapter: CanonicalPaperAdapter,
    ) -> None:
        self.repository = repository
        self.adapter = adapter

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
                existing = self.adapter.lookup(execution_id=execution_id)
                if existing is None:
                    results.append(
                        PaperExecutionResult(
                            PaperExecutionOutcome.RECOVERY_REQUIRED,
                            "NO_PROVEN_PAPER_RESULT",
                            command=current.command,
                            state=current.state,
                        )
                    )
                    continue
                if existing.uncertain:
                    results.append(
                        PaperExecutionResult(
                            PaperExecutionOutcome.SUBMISSION_UNCERTAIN,
                            existing.reason_code,
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
                        reason_code="RECOVERY_SUBMISSION_OBSERVED",
                    )
                if current.state in {
                    PaperExecutionState.SUBMISSION_STARTED,
                    PaperExecutionState.SUBMISSION_UNCERTAIN,
                    PaperExecutionState.RECOVERY_REQUIRED,
                }:
                    target = (
                        PaperExecutionState.PAPER_ACCEPTED
                        if existing.accepted
                        else PaperExecutionState.PAPER_REJECTED
                    )
                    event = (
                        PaperExecutionEventType.PAPER_ACCEPTED
                        if existing.accepted
                        else PaperExecutionEventType.PAPER_REJECTED
                    )
                    reconciled = self.repository.transition(
                        execution_id=execution_id,
                        expected_state=current.state,
                        new_state=target,
                        event_type=event,
                        at=observed_at,
                        reason_code=existing.reason_code,
                        paper_order_id=existing.paper_order_id,
                    )
                    results.append(
                        PaperExecutionResult(
                            PaperExecutionOutcome.SUBMISSION_ACCEPTED
                            if existing.accepted
                            else PaperExecutionOutcome.SUBMISSION_REJECTED,
                            existing.reason_code,
                            command=reconciled.command,
                            state=reconciled.state,
                            paper_order_id=reconciled.paper_order_id,
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
