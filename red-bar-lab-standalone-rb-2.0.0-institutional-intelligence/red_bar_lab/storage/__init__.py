from __future__ import annotations

"""Storage package hardening hooks.

P0-1 installs run-scoped signal replacement. P0-2 protects the final paper-order
persistence boundary so every execution path shares the same per-signal limits.
"""

from red_bar_lab.execution.signal_execution_limits import (
    evaluate_signal_execution_limits,
)
from red_bar_lab.services.run_scoped_signal_persistence import (
    replace_run_scoped_signal_rows,
)
from red_bar_lab.storage.database import RedBarDatabase, deterministic_signal_id


def _replace_signal_attempts_run_scoped(
    self: RedBarDatabase,
    run_id: str,
    instrument_key: str,
    trading_date: str,
    attempts,
) -> int:
    self.initialize()
    rows = []
    for item in attempts:
        direction = item.direction.value if item.direction else None
        cross_timestamp = (
            item.cross_timestamp.isoformat() if item.cross_timestamp else None
        )
        confirmation_timestamp = (
            item.confirmation_timestamp.isoformat()
            if item.confirmation_timestamp
            else None
        )
        rows.append(
            {
                "signal_id": deterministic_signal_id(
                    instrument_key,
                    trading_date,
                    item.level_type,
                    direction,
                    cross_timestamp,
                    confirmation_timestamp,
                ),
                "level_type": item.level_type,
                "level_value": item.level_value,
                "direction": direction,
                "state": item.state.value,
                "cross_timestamp": cross_timestamp,
                "confirmation_timestamp": confirmation_timestamp,
                "underlying_entry": item.underlying_entry,
                "cross_open": item.cross_open,
                "cross_high": item.cross_high,
                "cross_low": item.cross_low,
                "cross_close": item.cross_close,
                "confirmation_open": item.confirmation_open,
                "confirmation_high": item.confirmation_high,
                "confirmation_low": item.confirmation_low,
                "confirmation_close": item.confirmation_close,
                "confirmation_delay_minutes": item.confirmation_delay_minutes,
            }
        )
    result = replace_run_scoped_signal_rows(
        self.path,
        run_id=run_id,
        instrument_key=instrument_key,
        trading_date=trading_date,
        rows=rows,
    )
    return result.inserted_count


_original_insert_paper_execution_order = RedBarDatabase.insert_paper_execution_order


def _insert_paper_execution_order_with_signal_limits(
    self: RedBarDatabase,
    row: dict[str, object],
) -> None:
    self.initialize()
    decision = evaluate_signal_execution_limits(
        self.path,
        account_id=str(row.get("account_id") or "PAPER-STD"),
        signal_id=(str(row.get("signal_id")) if row.get("signal_id") else None),
        instrument_token=int(row.get("instrument_token") or 0),
        max_contracts_per_signal=int(row.get("max_contracts_per_signal") or 2),
        max_entries_per_signal=int(row.get("max_entries_per_signal") or 2),
        reentry_cooldown_seconds=int(row.get("reentry_cooldown_seconds") or 300),
        max_signal_age_seconds=int(row.get("max_signal_age_seconds") or 180),
        allow_stale_signal_override=bool(row.get("allow_stale_signal_override")),
    )
    if not decision.allowed:
        raise ValueError(
            "SIGNAL_EXECUTION_BLOCKED:"
            f"{decision.reason};entries={decision.existing_entries};"
            f"contracts={decision.existing_contracts};"
            f"age={decision.signal_age_seconds};"
            f"cooldown_age={decision.seconds_since_last_entry}"
        )
    _original_insert_paper_execution_order(self, row)


RedBarDatabase.replace_signal_attempts = _replace_signal_attempts_run_scoped
RedBarDatabase.insert_paper_execution_order = (
    _insert_paper_execution_order_with_signal_limits
)

__all__ = ["RedBarDatabase"]
