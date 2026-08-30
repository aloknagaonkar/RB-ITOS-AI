"""Process evidence writer for Red Bar V2 strategy sub-checks.

Extracted to its own module to avoid circular imports between
``red_bar_v2_current_session`` and ``red_bar_v2_futures_historical_replay``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def record_strategy_subcheck(
    database: Any,
    *,
    run_id: str | None,
    step_name: str,
    artifacts: dict[str, Any] | None = None,
    status: str = "OK",
    error_message: str | None = None,
) -> None:
    """Best-effort: write one ``process_evidence`` row describing a
    single Red Bar V2 strategy sub-check (gate, candidate, score,
    decision, mid-session, re-entry, etc.).

    The writer only writes if the caller supplied a non-empty
    ``run_id`` (i.e. the page is in Live Mode) AND the database has
    the right interface. Failures are swallowed because strategy
    evaluation must never be interrupted by evidence-writing errors.
    """
    if not run_id:
        return
    write_fn = getattr(database, "write_step_evidence", None)
    update_fn = getattr(database, "update_step_evidence", None)
    if not callable(write_fn) or not callable(update_fn):
        return
    try:
        started_at = datetime.now(timezone.utc).isoformat()
        step_id = write_fn(
            process_name="red_bar_v2_strategy",
            run_id=run_id,
            step_name=step_name,
            parent_step="strategy_evaluate",
            started_at=started_at,
            status=status,
            artifacts=artifacts or {},
        )
        update_fn(
            step_id=step_id,
            completed_at=started_at,
            status=status,
            duration_ms=0.0,
            error_message=error_message,
        )
    except Exception:
        pass
