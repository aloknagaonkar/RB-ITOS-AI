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
    """Replace one producer's rows without deleting another producer's signals.

    Deletion is scoped to ``(run_id, instrument_key, trading_date)``. Canonical
    ``signal_id`` remains globally unique: when a deterministic replay emits the
    same signal under a newer run ID, the existing row is reassigned and updated
    idempotently instead of creating a duplicate. Legacy signal-ID migration is
    intentionally excluded from this hot path.
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
    values: list[tuple[object, ...]] = []
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
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_signal_attempts_run_session
            ON signal_attempts(run_id, instrument_key, trading_date)
            """
        )
        deleted_count = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM signal_attempts
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
            ON CONFLICT(signal_id) DO UPDATE SET
                run_id=excluded.run_id,
                instrument_key=excluded.instrument_key,
                trading_date=excluded.trading_date,
                level_type=excluded.level_type,
                level_value=excluded.level_value,
                direction=excluded.direction,
                state=excluded.state,
                cross_timestamp=excluded.cross_timestamp,
                confirmation_timestamp=excluded.confirmation_timestamp,
                underlying_entry=excluded.underlying_entry,
                cross_open=excluded.cross_open,
                cross_high=excluded.cross_high,
                cross_low=excluded.cross_low,
                cross_close=excluded.cross_close,
                confirmation_open=excluded.confirmation_open,
                confirmation_high=excluded.confirmation_high,
                confirmation_low=excluded.confirmation_low,
                confirmation_close=excluded.confirmation_close,
                confirmation_delay_minutes=excluded.confirmation_delay_minutes,
                created_at=excluded.created_at
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


def count_orphaned_paper_orders(database_path: str | Path) -> int:
    """Return paper orders whose non-null signal ID has no signal row."""

    with sqlite3.connect(Path(database_path)) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if not {"paper_execution_orders", "signal_attempts"}.issubset(tables):
            return 0
        return int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM paper_execution_orders AS orders
                LEFT JOIN signal_attempts AS signals
                  ON signals.signal_id=orders.signal_id
                WHERE orders.signal_id IS NOT NULL
                  AND orders.signal_id<>''
                  AND signals.signal_id IS NULL
                """
            ).fetchone()[0]
        )


__all__ = [
    "RunScopedSignalPersistenceResult",
    "replace_run_scoped_signal_rows",
    "count_orphaned_paper_orders",
]
