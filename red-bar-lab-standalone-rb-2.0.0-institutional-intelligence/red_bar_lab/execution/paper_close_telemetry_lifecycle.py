from __future__ import annotations

from typing import Any

from red_bar_lab.execution.option_telemetry_lifecycle import (
    record_exit_telemetry_fallback,
)


def install(paper_execution_engine_class: Any) -> None:
    """Record a non-blocking EXIT lifecycle snapshot after a paper order closes.

    The wrapper never changes close decisions, fill prices, exit reasons, or error
    handling. It only copies the latest persisted option telemetry after a
    successful close. Exact provider-time exit capture can replace this fallback
    later without changing the execution contract.
    """
    if getattr(paper_execution_engine_class, "_exit_telemetry_lifecycle_installed", False):
        return

    original_close = paper_execution_engine_class.close_position

    def close_position(self, *args, **kwargs):
        result = original_close(self, *args, **kwargs)
        try:
            row = dict(result or {})
            if str(row.get("status") or "").upper() != "CLOSED":
                return result
            order_id = str(row.get("order_id") or kwargs.get("order_id") or "")
            if not order_id:
                return result
            latest = self.database.read_latest_option_execution_telemetry(order_id)
            record_exit_telemetry_fallback(self.database, order_id, latest)
        except Exception:
            # Telemetry is observational and must never block a completed exit.
            pass
        return result

    paper_execution_engine_class.close_position = close_position
    paper_execution_engine_class._exit_telemetry_lifecycle_installed = True


__all__ = ["install"]
