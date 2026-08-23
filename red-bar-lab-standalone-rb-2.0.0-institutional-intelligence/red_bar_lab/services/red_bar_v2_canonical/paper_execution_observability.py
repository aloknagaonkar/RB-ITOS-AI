from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from .paper_execution_ledger import StrictSQLiteCanonicalPaperExecutionRepository
from .paper_execution_repository import (
    PaperExecutionCorruptionError,
    PaperExecutionStorageError,
    VerifiedPaperExecution,
)
from .reservation_evidence_verification import (
    ReservationCorruptionError,
    verify_reservation_evidence,
)


@dataclass(frozen=True, slots=True)
class PaperExecutionObservation:
    status: str
    evidence: VerifiedPaperExecution | None


class SQLiteCanonicalPaperExecutionObservabilityRepository:
    """Read-only verified projection; never initializes or mutates schema."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def latest_for_bundle(self, *, bundle_id: str) -> PaperExecutionObservation:
        if not self.path.exists():
            return PaperExecutionObservation(
                "EXECUTION_DATABASE_UNAVAILABLE",
                None,
            )
        repository = StrictSQLiteCanonicalPaperExecutionRepository(
            self.path,
            initialize=False,
        )
        try:
            with repository._connect(read_only=True) as conn:
                table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='canonical_red_bar_v2_paper_commands'"
                ).fetchone()
                if table is None:
                    return PaperExecutionObservation(
                        "NO_CANONICAL_EXECUTION",
                        None,
                    )
                row = conn.execute(
                    "SELECT execution_id,reservation_id,bundle_id "
                    "FROM canonical_red_bar_v2_paper_commands "
                    "WHERE bundle_id=? "
                    "ORDER BY created_at DESC,command_id DESC LIMIT 1",
                    (bundle_id,),
                ).fetchone()
                if row is None:
                    return PaperExecutionObservation(
                        "NO_CANONICAL_EXECUTION",
                        None,
                    )
                evidence = repository.get_verified(
                    execution_id=str(row["execution_id"])
                )
                reservation_evidence = verify_reservation_evidence(
                    conn,
                    reservation_id=str(row["reservation_id"]),
                    expected_bundle_id=bundle_id,
                )

            reservation = reservation_evidence.reservation
            if (
                evidence.command.reservation_id != reservation.reservation_id
                or evidence.command.bundle_id != reservation.bundle_id
                or str(row["bundle_id"]) != reservation.bundle_id
            ):
                return PaperExecutionObservation(
                    "EXECUTION_DATA_CORRUPT",
                    None,
                )

            unresolved_finalization = (
                evidence.state.value in {"PAPER_FILLED", "PAPER_REJECTED"}
                and reservation.state.value == "RESERVED"
            )
            status = (
                "RECOVERY_REQUIRED"
                if unresolved_finalization
                or evidence.state.value
                in {"SUBMISSION_UNCERTAIN", "RECOVERY_REQUIRED"}
                else "EXECUTION_DATA_AVAILABLE"
            )
            return PaperExecutionObservation(status, evidence)
        except (PaperExecutionCorruptionError, ReservationCorruptionError):
            return PaperExecutionObservation("EXECUTION_DATA_CORRUPT", None)
        except (PaperExecutionStorageError, sqlite3.Error, OSError):
            return PaperExecutionObservation(
                "EXECUTION_DATABASE_UNAVAILABLE",
                None,
            )
