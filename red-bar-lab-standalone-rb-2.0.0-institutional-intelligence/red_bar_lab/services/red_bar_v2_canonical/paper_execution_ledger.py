from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json

from .paper_execution_identity import build_execution_event_id, payload_sha256
from .paper_execution_models import PaperExecutionEventType, PaperExecutionState
from .paper_execution_repository import (
    PaperExecutionCorruptionError,
    PaperExecutionStorageError,
    SQLiteCanonicalPaperExecutionRepository,
    VerifiedPaperExecution,
    _aware,
    command_from_payload,
)


@dataclass(frozen=True, slots=True)
class PendingReservationFinalization:
    execution_id: str
    reservation_id: str
    state: PaperExecutionState
    updated_at: datetime


_EVENT_TARGET = {
    PaperExecutionEventType.COMMAND_PREPARED: PaperExecutionState.PREPARED,
    PaperExecutionEventType.SUBMISSION_STARTED: PaperExecutionState.SUBMISSION_STARTED,
    PaperExecutionEventType.SUBMISSION_UNCERTAIN: PaperExecutionState.SUBMISSION_UNCERTAIN,
    PaperExecutionEventType.PAPER_ACCEPTED: PaperExecutionState.PAPER_ACCEPTED,
    PaperExecutionEventType.RECOVERY_REQUIRED: PaperExecutionState.RECOVERY_REQUIRED,
    PaperExecutionEventType.PAPER_FILLED: PaperExecutionState.PAPER_FILLED,
    PaperExecutionEventType.PAPER_REJECTED: PaperExecutionState.PAPER_REJECTED,
}

_ALLOWED_PREDECESSORS = {
    PaperExecutionEventType.COMMAND_PREPARED: {None},
    PaperExecutionEventType.SUBMISSION_STARTED: {PaperExecutionState.PREPARED},
    PaperExecutionEventType.SUBMISSION_UNCERTAIN: {PaperExecutionState.SUBMISSION_STARTED},
    PaperExecutionEventType.PAPER_ACCEPTED: {
        PaperExecutionState.SUBMISSION_STARTED,
        PaperExecutionState.SUBMISSION_UNCERTAIN,
        PaperExecutionState.RECOVERY_REQUIRED,
    },
    PaperExecutionEventType.RECOVERY_REQUIRED: {
        PaperExecutionState.PREPARED,
        PaperExecutionState.PAPER_ACCEPTED,
        PaperExecutionState.SUBMISSION_UNCERTAIN,
    },
    PaperExecutionEventType.PAPER_FILLED: {PaperExecutionState.PAPER_ACCEPTED},
    PaperExecutionEventType.PAPER_REJECTED: {
        PaperExecutionState.SUBMISSION_STARTED,
        PaperExecutionState.SUBMISSION_UNCERTAIN,
        PaperExecutionState.RECOVERY_REQUIRED,
    },
}


class StrictSQLiteCanonicalPaperExecutionRepository(
    SQLiteCanonicalPaperExecutionRepository
):
    """Verified ledger with deterministic ordering and transition validation."""

    def get_verified(self, *, execution_id: str) -> VerifiedPaperExecution:
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM canonical_red_bar_v2_paper_commands WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise LookupError("canonical paper execution not found")
            payload = str(row["payload_json"])
            if payload_sha256(payload) != str(row["payload_sha256"]):
                raise PaperExecutionCorruptionError("command digest mismatch")
            command = command_from_payload(payload)
            projections = {
                "command_id": command.command_id,
                "execution_id": command.execution_id,
                "reservation_id": command.reservation_id,
                "bundle_id": command.bundle_id,
                "signal_id": command.signal_id,
                "idempotency_key": command.idempotency_key,
                "schema_version": command.schema_version,
            }
            for field, expected in projections.items():
                if row[field] != expected:
                    raise PaperExecutionCorruptionError(
                        f"command projection mismatch: {field}"
                    )
            persisted_state = PaperExecutionState(str(row["state"]))
            event_rows = conn.execute(
                """
                SELECT * FROM canonical_red_bar_v2_paper_execution_events
                WHERE execution_id=?
                ORDER BY event_timestamp ASC,
                  CASE event_type
                    WHEN 'COMMAND_PREPARED' THEN 10
                    WHEN 'SUBMISSION_STARTED' THEN 20
                    WHEN 'SUBMISSION_UNCERTAIN' THEN 30
                    WHEN 'PAPER_ACCEPTED' THEN 40
                    WHEN 'RECOVERY_REQUIRED' THEN 50
                    WHEN 'PAPER_FILLED' THEN 60
                    WHEN 'PAPER_REJECTED' THEN 60
                    ELSE 999
                  END ASC,
                  event_id ASC
                """,
                (execution_id,),
            ).fetchall()
        if not event_rows:
            raise PaperExecutionCorruptionError(
                "paper execution has no lifecycle history"
            )

        events = []
        derived_state: PaperExecutionState | None = None
        previous_timestamp = None
        for item in event_rows:
            metadata_json = str(item["metadata_json"])
            if payload_sha256(metadata_json) != str(item["metadata_sha256"]):
                raise PaperExecutionCorruptionError(
                    "paper execution event digest mismatch"
                )
            try:
                metadata = json.loads(metadata_json)
            except Exception as exc:
                raise PaperExecutionCorruptionError(
                    "paper execution event metadata schema mismatch"
                ) from exc
            timestamp = _aware(item["event_timestamp"], "event_timestamp")
            if previous_timestamp is not None and timestamp < previous_timestamp:
                raise PaperExecutionCorruptionError(
                    "paper execution event chronology mismatch"
                )
            previous_timestamp = timestamp
            try:
                event_type = PaperExecutionEventType(str(item["event_type"]))
            except ValueError as exc:
                raise PaperExecutionCorruptionError(
                    "unknown paper execution event type"
                ) from exc
            target_state = _EVENT_TARGET[event_type]
            if (
                metadata.get("execution_id") != command.execution_id
                or metadata.get("command_id") != command.command_id
                or metadata.get("state") != target_state.value
            ):
                raise PaperExecutionCorruptionError(
                    "paper execution event metadata mismatch"
                )
            expected_id = build_execution_event_id(
                execution_id=command.execution_id,
                event_type=event_type.value,
                event_timestamp=timestamp,
                reason_code=str(item["reason_code"]),
            )
            if (
                item["event_id"] != expected_id
                or item["command_id"] != command.command_id
                or item["execution_id"] != command.execution_id
            ):
                raise PaperExecutionCorruptionError(
                    "paper execution event identity mismatch"
                )
            if derived_state not in _ALLOWED_PREDECESSORS[event_type]:
                raise PaperExecutionCorruptionError(
                    "paper execution lifecycle transition mismatch"
                )
            derived_state = target_state
            events.append(
                (
                    event_type,
                    timestamp,
                    str(item["reason_code"]),
                    item["paper_order_id"],
                )
            )

        if derived_state is not persisted_state:
            raise PaperExecutionCorruptionError(
                "paper execution state/history mismatch"
            )
        if persisted_state in {
            PaperExecutionState.PAPER_FILLED,
            PaperExecutionState.PAPER_REJECTED,
        } and events[-1][0] not in {
            PaperExecutionEventType.PAPER_FILLED,
            PaperExecutionEventType.PAPER_REJECTED,
        }:
            raise PaperExecutionCorruptionError(
                "paper execution terminal event mismatch"
            )
        return VerifiedPaperExecution(
            command=command,
            state=persisted_state,
            reason_code=str(row["reason_code"]),
            paper_order_id=row["paper_order_id"],
            events=tuple(events),
        )

    def find_by_idempotency_key(
        self,
        *,
        idempotency_key: str,
    ) -> VerifiedPaperExecution | None:
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT execution_id FROM canonical_red_bar_v2_paper_commands "
                "WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
        return (
            self.get_verified(execution_id=str(row["execution_id"]))
            if row is not None
            else None
        )

    def list_pending_finalization(
        self,
        *,
        limit: int = 100,
    ) -> tuple[PendingReservationFinalization, ...]:
        bounded = max(1, min(int(limit), 500))
        try:
            with self._connect(read_only=True) as conn:
                rows = conn.execute(
                    """
                    SELECT c.execution_id,c.reservation_id,c.state,c.updated_at
                    FROM canonical_red_bar_v2_paper_commands c
                    JOIN canonical_red_bar_v2_bundle_reservations r
                      ON r.reservation_id=c.reservation_id
                    WHERE c.state IN ('PAPER_FILLED','PAPER_REJECTED')
                      AND r.state='RESERVED'
                    ORDER BY c.updated_at ASC,c.execution_id ASC
                    LIMIT ?
                    """,
                    (bounded,),
                ).fetchall()
        except PaperExecutionStorageError:
            raise
        return tuple(
            PendingReservationFinalization(
                execution_id=str(row["execution_id"]),
                reservation_id=str(row["reservation_id"]),
                state=PaperExecutionState(str(row["state"])),
                updated_at=_aware(row["updated_at"], "updated_at"),
            )
            for row in rows
        )

    def count_trading_date_executions(self, *, trading_date: date) -> int:
        if type(trading_date) is not date:
            raise ValueError("trading_date must be date")
        try:
            with self._connect(read_only=True) as conn:
                rows = conn.execute(
                    "SELECT payload_json,payload_sha256 FROM "
                    "canonical_red_bar_v2_paper_commands"
                ).fetchall()
        except PaperExecutionStorageError:
            raise
        count = 0
        for row in rows:
            payload = str(row["payload_json"])
            if payload_sha256(payload) != str(row["payload_sha256"]):
                raise PaperExecutionCorruptionError("command digest mismatch")
            command = command_from_payload(payload)
            if command.trading_date == trading_date:
                count += 1
        return count
