"""Process evidence maintenance.

Keeps ``process_evidence`` and ``process_run_correlation`` from
growing unbounded by deleting rows older than a configurable
retention window. Designed to be called from a long-running process
(e.g. the market_collector tick) which already has a database handle.

The cleanup is idempotent and self-throttling: it only runs if the
last cleanup was more than ``cleanup_interval_hours`` ago, so callers
can call it on every tick without worrying about repeated work.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

DEFAULT_RETENTION_DAYS = 7
DEFAULT_CLEANUP_INTERVAL_HOURS = 24


def maybe_cleanup_process_evidence(
    database: Any,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    cleanup_interval_hours: float = DEFAULT_CLEANUP_INTERVAL_HOURS,
) -> int:
    """Delete old ``process_evidence`` rows if it's been a while since
    the last cleanup. Returns the number of rows deleted, or 0 if no
    cleanup was needed. Best-effort: any error is swallowed and 0 is
    returned."""
    try:
        last_cleanup = database.read_last_cleanup_at()
        if last_cleanup is not None:
            parsed = _parse_iso(last_cleanup)
            if parsed is not None:
                age_hours = (
                    datetime.now(timezone.utc) - parsed
                ).total_seconds() / 3600.0
                if age_hours < cleanup_interval_hours:
                    return 0
        deleted = database.cleanup_process_evidence(
            retention_days=retention_days
        )
        database.write_last_cleanup_at(
            datetime.now(timezone.utc).isoformat()
        )
        return deleted
    except Exception:  # noqa: BLE001
        # Best-effort: cleanup failures must never interrupt the
        # calling process.
        return 0


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
