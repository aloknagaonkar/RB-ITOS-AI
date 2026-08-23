from __future__ import annotations

from .paper_execution_ledger import StrictSQLiteCanonicalPaperExecutionRepository
from .paper_execution_models import CanonicalPaperExecutionCommand
from .paper_execution_repository import (
    PaperExecutionConflictError,
    VerifiedPaperExecution,
)


class GuardedCanonicalPaperExecutionRepository(
    StrictSQLiteCanonicalPaperExecutionRepository
):
    """Public ledger boundary; command creation requires guarded orchestration."""

    def prepare(
        self,
        command: CanonicalPaperExecutionCommand,
    ) -> VerifiedPaperExecution:
        del command
        raise PaperExecutionConflictError(
            "direct paper command preparation is disabled; "
            "use guarded canonical paper orchestration"
        )
