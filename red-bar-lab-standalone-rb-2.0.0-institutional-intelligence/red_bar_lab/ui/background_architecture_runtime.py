from __future__ import annotations

from functools import wraps

from red_bar_lab.execution.background_architecture_orchestrator import (
    ensure_background_architecture_orchestrator,
)


def build_background_architecture_bootstrap_wrapper(original):
    """Start the read-only daemon once shared runtime dependencies are available."""

    @wraps(original)
    def wrapper(
        settings,
        layout,
        database,
        token,
        underlying_name,
        instrument_key,
        interval,
        *args,
        **kwargs,
    ):
        ensure_background_architecture_orchestrator(
            settings=settings,
            layout=layout,
            database=database,
            instrument_key=str(instrument_key),
        )
        return original(
            settings,
            layout,
            database,
            token,
            underlying_name,
            instrument_key,
            interval,
            *args,
            **kwargs,
        )

    return wrapper


__all__ = ["build_background_architecture_bootstrap_wrapper"]
