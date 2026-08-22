from __future__ import annotations

"""Storage package hardening hooks.

The project historically defined ``RedBarDatabase.replace_signal_attempts`` in a
large compatibility module. P0-1 installs the run-scoped implementation at the
package boundary so every existing caller receives the corrected behavior while
the stable database API remains unchanged.
"""

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


RedBarDatabase.replace_signal_attempts = _replace_signal_attempts_run_scoped

__all__ = ["RedBarDatabase"]
