from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class RunScopedSignalPersistenceResult:
    run_id: str
    instrument_key: str
    trading_date: str
    deleted_count: int
    inserted_count: int


def replace_run_scoped_signal_rows(
    database_path: str | Path,
    *,
    run_id: str,
    instrument_key: str,
    trading_date: str,
    rows: Iterable[Mapping[str, object]],
) -> RunScopedSignalPersistenceResult:
    """Replace signal rows owned by one producer without touching other runs.

    This is the P0-1 persistence primitive. It deliberately scopes deletion to
    ``(run_id, instrument_key, trading_date)`` so LIVE_MONITOR refreshes cannot
    erase RBV2-PAPER-RUNTIME or historical-replay rows for the same session.

    The caller supplies canonical signal IDs and normalized row values. Legacy
    signal-ID migration is intentionally excluded from this hot-path function.
    """

    owner = str(run_id or "").strip()
    instrument = str(instrument_key or "").strip()
    session = str(trading_date or "").strip()
    if not owner:
        raise ValueError("run_id is required")
    if not instrument:
        raise ValueError("instrument_key is required")
    if not session:
        raise ValueError("trading_date is required")

    payload = [dict(row) for row in rows]
    created_at = datetime.now().astimezone().isoformat()

    values = []
    for row in payload:
        signal_id = str(row.get("signal_id") or "").strip()
        if not signal_id:
            raise ValueError("signal_id is required for every signal row")
        values.append(
            (
                signal_id,
                owner,
                instrument,
                session,
                row.get("level_type"),
                row.get("level_value"),
                row.get("direction"),
                row.get("state"),
                row.get("cross_timestamp"),
                row.get("confirmation_timestamp"),
                row.get("underlying_entry"),
                row.get("cross_open"),
                row.get("cross_high"),
                row.get("cross_low"),
                row.get("cross_close"),
                row.get("confirmation_open"),
                row.get("confirmation_high"),
                row.get("confirmation_low"),
                row.get("confirmation_close"),
                row.get("confirmation_delay_minutes"),
                row.get("created_at") or created_at,
            )
        )

    with sqlite3.connect(Path(database_path)) as connection:
        deleted_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM signal_attempts
                WHERE run_id=? AND instrument_key=? AND trading_date=?
                """,
                (owner, instrument, session),
            ).fetchone()[0]
        )
        connection.execute(
            """
            DELETE FROM signal_attempts
            WHERE run_id=? AND instrument_key=? AND trading_date=?
            """,
            (owner, instrument, session),
        )
        connection.executemany(
            """
            INSERT INTO signal_attempts(
                signal_id,run_id,instrument_key,trading_date,level_type,
                level_value,direction,state,cross_timestamp,
                confirmation_timestamp,underlying_entry,cross_open,
                cross_high,cross_low,cross_close,confirmation_open,
                confirmation_high,confirmation_low,confirmation_close,
                confirmation_delay_minutes,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            values,
        )
        connection.commit()

    return RunScopedSignalPersistenceResult(
        run_id=owner,
        instrument_key=instrument,
        trading_date=session,
        deleted_count=deleted_count,
        inserted_count=len(values),
    )


__all__ = [
    "RunScopedSignalPersistenceResult",
    "replace_run_scoped_signal_rows",
]
