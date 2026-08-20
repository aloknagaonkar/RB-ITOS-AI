from __future__ import annotations

from typing import Any

from red_bar_lab.execution.option_telemetry_lifecycle import (
    record_exit_telemetry_exact,
    record_exit_telemetry_fallback,
)


class _QuoteCaptureProxy:
    """Delegate market-data calls while retaining the exact quote used to exit."""

    def __init__(self, provider: Any) -> None:
        self._provider = provider
        self.last_quotes: dict[str, object] = {}

    def __getattr__(self, name: str):
        return getattr(self._provider, name)

    def quote(self, keys):
        result = self._provider.quote(keys)
        if isinstance(result, dict):
            self.last_quotes = dict(result)
        return result


def install(paper_execution_engine_class: Any) -> None:
    """Record a non-blocking exact or fallback EXIT lifecycle snapshot.

    The provider object is wrapped only for the duration of ``close_position``.
    The wrapper observes the same quote response already used for the paper fill,
    so exact exit capture adds no provider request and never changes fill logic.
    """
    if getattr(paper_execution_engine_class, "_exit_telemetry_lifecycle_installed", False):
        return

    original_close = paper_execution_engine_class.close_position

    def close_position(self, *args, **kwargs):
        call_kwargs = dict(kwargs)
        provider = call_kwargs.get("zerodha")
        proxy = _QuoteCaptureProxy(provider) if provider is not None else None
        if proxy is not None:
            call_kwargs["zerodha"] = proxy

        result = original_close(self, *args, **call_kwargs)
        try:
            row = dict(result or {})
            if str(row.get("status") or "").upper() != "CLOSED":
                return result
            order_id = str(row.get("order_id") or kwargs.get("order_id") or "")
            if not order_id:
                return result
            latest = self.database.read_latest_option_execution_telemetry(order_id)
            quote = None
            if proxy is not None:
                key = f"{row.get('exchange')}:{row.get('tradingsymbol')}"
                quote = proxy.last_quotes.get(key)
                if quote is None and len(proxy.last_quotes) == 1:
                    quote = next(iter(proxy.last_quotes.values()))
            if quote:
                record_exit_telemetry_exact(
                    self.database,
                    order_id,
                    quote,
                    latest,
                    observed_timestamp=str(row.get("exit_timestamp") or "") or None,
                )
            else:
                record_exit_telemetry_fallback(self.database, order_id, latest)
        except Exception:
            # Telemetry is observational and must never block a completed exit.
            pass
        return result

    paper_execution_engine_class.close_position = close_position
    paper_execution_engine_class._exit_telemetry_lifecycle_installed = True


__all__ = ["install"]
