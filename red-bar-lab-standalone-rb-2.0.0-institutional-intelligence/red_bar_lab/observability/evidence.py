"""Per-step evidence tracking for long-running platform processes.

A small helper that wraps a unit of work (one step inside a process) in
a context manager that:

- Inserts a row in ``process_evidence`` when the step starts (status=RUNNING).
- Updates that row when the step ends, with status=OK and duration_ms.
- On exception, marks the row status=ERROR and re-raises.

The intended use is:

.. code-block:: python

    from red_bar_lab.observability.evidence import with_step_evidence

    with with_step_evidence(
        database,
        process_name="orchestrator",
        step_name="evaluate_day",
        run_id=run_id,
    ) as step_id:
        ... # do work

The live cadence UI reads from ``process_evidence`` to show a per-step
timeline with last-run timestamps and durations, so the user can answer
"is the orchestrator's ``evaluate_day`` step still running? did it
succeed? how long did it take last time?".
"""

from __future__ import annotations

import time as _time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_run_id(process_name: str) -> str:
    """Return a fresh run_id like ``orchestrator-2026-08-29T03:45:00-001``."""
    short_name = process_name.replace("_", "-")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    # Last 6 hex digits of perf_counter for uniqueness within the same second
    suffix = f"{int(_time.perf_counter() * 1_000_000) & 0xFFFFFF:06x}"
    return f"{short_name}-{now}-{suffix}"


@contextmanager
def with_step_evidence(
    database: Any,
    *,
    process_name: str,
    step_name: str,
    run_id: str | None = None,
    parent_step: str | None = None,
    artifacts: dict[str, object] | None = None,
) -> Iterator[int]:
    """Wrap a unit of work in evidence tracking.

    Yields the new step's row id so callers can read it back if they want.
    """
    rid = run_id or generate_run_id(process_name)
    started_at = _now_iso()
    step_id = database.write_step_evidence(
        process_name=process_name,
        run_id=rid,
        step_name=step_name,
        parent_step=parent_step,
        started_at=started_at,
        status="RUNNING",
        artifacts=artifacts,
    )
    started_perf = _time.perf_counter()
    try:
        yield step_id
    except Exception as exc:
        duration_ms = (_time.perf_counter() - started_perf) * 1000.0
        try:
            database.update_step_evidence(
                step_id=step_id,
                completed_at=_now_iso(),
                status="ERROR",
                duration_ms=duration_ms,
                error_message=f"{type(exc).__name__}: {exc}"[:500],
            )
        except Exception:  # noqa: BLE001
            # Best-effort: if writing the error row itself fails, don't mask
            # the original exception.
            pass
        raise
    else:
        duration_ms = (_time.perf_counter() - started_perf) * 1000.0
        try:
            database.update_step_evidence(
                step_id=step_id,
                completed_at=_now_iso(),
                status="OK",
                duration_ms=duration_ms,
            )
        except Exception:  # noqa: BLE001
            pass


def safe_step_evidence(
    database: Any,
    *,
    process_name: str,
    step_name: str,
    run_id: str | None = None,
    parent_step: str | None = None,
) -> "StepEvidenceGuard":
    """Return a guard object whose ``__enter__``/``__exit__`` is a thin
    wrapper around ``with_step_evidence`` that does not raise if the
    database write itself fails. Useful for places where you want to add
    evidence instrumentation without taking down the calling code if the
    database is unavailable.
    """

    class _Guard:
        def __enter__(self_inner) -> int:
            self_inner._cm = with_step_evidence(
                database,
                process_name=process_name,
                step_name=step_name,
                run_id=run_id,
                parent_step=parent_step,
            )
            try:
                return self_inner._cm.__enter__()
            except Exception:  # noqa: BLE001
                return -1

        def __exit__(self_inner, exc_type, exc, tb) -> bool:
            try:
                return self_inner._cm.__exit__(exc_type, exc, tb)
            except Exception:  # noqa: BLE001
                return False

    return _Guard()


class StepEvidenceGuard:  # pragma: no cover - alias for documentation
    """Deprecated alias for :func:`safe_step_evidence`. Use that instead."""


class ProcessEvidenceWriter:
    """Callable that writes one row to ``process_evidence``.

    Used by components that don't have direct access to the main
    RedBarDatabase (e.g. the canonical V2 shadow's persistence service)
    but still need to record step timing. The shadow_runtime constructs
    one of these and threads it through the persistence service via
    ``RedBarV2CanonicalPersistenceService(..., evidence_writer=...)``.

    The writer is best-effort: any exception is swallowed inside the
    writer. Callers don't need to wrap it in try/except.
    """

    def __init__(self, database: Any) -> None:
        self._database = database

    def __call__(
        self,
        *,
        process_name: str,
        run_id: str,
        step_name: str,
        parent_step: str | None,
        started_at: str,
        status: str,
        duration_ms: float | None = None,
        error_message: str | None = None,
        artifacts: dict[str, object] | None = None,
    ) -> int | None:
        """Write a single process_evidence row. Returns the new row id, or
        None if the database write failed or the database is unavailable."""
        if self._database is None:
            return None
        try:
            step_id = self._database.write_step_evidence(
                process_name=process_name,
                run_id=run_id,
                step_name=step_name,
                parent_step=parent_step,
                started_at=started_at,
                status=status,
                artifacts=artifacts,
            )
            self._database.update_step_evidence(
                step_id=step_id,
                completed_at=started_at,  # closed in the same instant
                status=status,
                duration_ms=float(duration_ms) if duration_ms is not None else 0.0,
                error_message=error_message,
            )
            return step_id
        except Exception:  # noqa: BLE001
            # Best-effort: never let evidence writing break the caller.
            return None
