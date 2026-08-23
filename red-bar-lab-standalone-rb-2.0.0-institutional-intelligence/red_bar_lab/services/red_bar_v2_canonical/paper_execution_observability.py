from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paper_execution_repository import (
    PaperExecutionCorruptionError,
    PaperExecutionStorageError,
    SQLiteCanonicalPaperExecutionRepository,
    VerifiedPaperExecution,
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
            return PaperExecutionObservation("EXECUTION_DATABASE_UNAVAILABLE", None)
        repository = SQLiteCanonicalPaperExecutionRepository(self.path, initialize=False)
        try:
            with repository._connect(read_only=True) as conn:
                table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='canonical_red_bar_v2_paper_commands'"
                ).fetchone()
                if table is None:
                    return PaperExecutionObservation("NO_CANONICAL_EXECUTION", None)
                row = conn.execute(
                    "SELECT execution_id FROM canonical_red_bar_v2_paper_commands "
                    "WHERE bundle_id=? ORDER BY created_at DESC,command_id DESC LIMIT 1",
                    (bundle_id,),
                ).fetchone()
            if row is None:
                return PaperExecutionObservation("NO_CANONICAL_EXECUTION", None)
            evidence = repository.get_verified(execution_id=str(row["execution_id"]))
            status = (
                "RECOVERY_REQUIRED"
                if evidence.state.value in {"SUBMISSION_UNCERTAIN", "RECOVERY_REQUIRED"}
                else "EXECUTION_DATA_AVAILABLE"
            )
            return PaperExecutionObservation(status, evidence)
        except PaperExecutionCorruptionError:
            return PaperExecutionObservation("EXECUTION_DATA_CORRUPT", None)
        except (PaperExecutionStorageError, OSError):
            return PaperExecutionObservation("EXECUTION_DATABASE_UNAVAILABLE", None)
