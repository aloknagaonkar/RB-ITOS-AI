"""Repository for signal_attempts domain."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Iterable

from red_bar_lab.strategy.identity import canonical_signal_id
from red_bar_lab.strategy.models import Direction, SignalAttempt, SignalState

if TYPE_CHECKING:
    from red_bar_lab.storage.database import RedBarDatabase


class SignalRepository:
    """Domain-specific repository for signal_attempts operations."""

    def __init__(self, database: RedBarDatabase) -> None:
        self._db = database

    @property
    def path(self):  # type: ignore[override]
        return self._db.path

    def replace_signal_attempts(
        self,
        run_id: str,
        instrument_key: str,
        trading_date: str,
        attempts: Iterable[SignalAttempt],
    ) -> int:
        """Replace the complete historical replay result for one date.

        Historical replay is deterministic. Re-running it for the same
        instrument/date must replace prior rows instead of appending duplicates.
        """
        self._db.initialize()
        rows = list(attempts)
        from datetime import datetime

        now = datetime.now().astimezone().isoformat()
        values = []
        for item in rows:
            direction = item.direction.value if item.direction else None
            cross_timestamp = (
                item.cross_timestamp.isoformat() if item.cross_timestamp else None
            )
            confirmation_timestamp = (
                item.confirmation_timestamp.isoformat()
                if item.confirmation_timestamp
                else None
            )
            signal_id = canonical_signal_id(
                instrument_key,
                trading_date,
                item.level_type,
                direction,
                cross_timestamp,
                confirmation_timestamp,
            )
            values.append(
                (
                    signal_id,
                    run_id,
                    instrument_key,
                    trading_date,
                    item.level_type,
                    item.level_value,
                    direction,
                    item.state.value,
                    cross_timestamp,
                    confirmation_timestamp,
                    item.underlying_entry,
                    item.cross_open,
                    item.cross_high,
                    item.cross_low,
                    item.cross_close,
                    item.confirmation_open,
                    item.confirmation_high,
                    item.confirmation_low,
                    item.confirmation_close,
                    item.confirmation_delay_minutes,
                    now,
                )
            )

        with self._db._connect() as conn:
            conn.execute(
                "DELETE FROM signal_attempts WHERE instrument_key=? AND trading_date=?",
                (instrument_key, trading_date),
            )
            conn.executemany(
                """INSERT INTO signal_attempts(
                    signal_id,run_id,instrument_key,trading_date,level_type,
                    level_value,direction,state,cross_timestamp,
                    confirmation_timestamp,underlying_entry,cross_open,
                    cross_high,cross_low,cross_close,confirmation_open,
                    confirmation_high,confirmation_low,confirmation_close,
                    confirmation_delay_minutes,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                values,
            )

            conn.execute(
                """
                UPDATE paper_trade_outcomes
                SET signal_id = (
                    SELECT s.signal_id
                    FROM signal_attempts s
                    WHERE s.instrument_key = paper_trade_outcomes.instrument_key
                      AND s.trading_date = paper_trade_outcomes.trading_date
                      AND s.level_type = paper_trade_outcomes.level_type
                      AND s.direction = paper_trade_outcomes.direction
                      AND s.confirmation_timestamp =
                          paper_trade_outcomes.entry_timestamp
                    LIMIT 1
                )
                WHERE instrument_key=?
                  AND trading_date=?
                  AND EXISTS (
                    SELECT 1
                    FROM signal_attempts s
                    WHERE s.instrument_key = paper_trade_outcomes.instrument_key
                      AND s.trading_date = paper_trade_outcomes.trading_date
                      AND s.level_type = paper_trade_outcomes.level_type
                      AND s.direction = paper_trade_outcomes.direction
                      AND s.confirmation_timestamp =
                          paper_trade_outcomes.entry_timestamp
                )
                """,
                (instrument_key, trading_date),
            )
            conn.commit()
        return len(rows)

    def read_signal_attempts(
        self, instrument_key: str, trading_date: str, run_id: str | None = None
    ) -> list[dict[str, object]]:
        self._db.initialize()
        query = """SELECT signal_id,level_type,level_value,direction,state,
                          cross_timestamp,confirmation_timestamp,underlying_entry,
                          cross_open,cross_high,cross_low,cross_close,
                          confirmation_open,confirmation_high,confirmation_low,
                          confirmation_close,confirmation_delay_minutes
                   FROM signal_attempts
                   WHERE instrument_key=? AND trading_date=?"""
        params: tuple[object, ...] = (instrument_key, trading_date)
        if run_id is not None:
            query += " AND run_id=?"
            params += (run_id,)
        query += " ORDER BY cross_timestamp, level_type"
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def read_signal_attempt_by_id(
        self,
        signal_id: str,
    ) -> dict[str, object] | None:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT signal_id,run_id,instrument_key,trading_date,
                       level_type,level_value,direction,state,
                       cross_timestamp,confirmation_timestamp,
                       underlying_entry,confirmation_delay_minutes,
                       created_at
                FROM signal_attempts
                WHERE signal_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (signal_id,),
            ).fetchone()
        return dict(row) if row else None

    def read_signal_attempts_by_ids(
        self,
        signal_ids: Iterable[str],
    ) -> dict[str, dict[str, object]]:
        """Batch-load signal metadata keyed by signal_id."""
        self._db.initialize()
        ids = tuple(dict.fromkeys(str(item) for item in signal_ids if str(item)))
        if not ids:
            return {}
        result: dict[str, dict[str, object]] = {}
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                placeholders = ",".join("?" for _ in chunk)
                query = f"""
                    SELECT signal_id,run_id,instrument_key,trading_date,
                           level_type,level_value,direction,state,
                           cross_timestamp,confirmation_timestamp,
                           underlying_entry,confirmation_delay_minutes,
                           created_at
                    FROM signal_attempts
                    WHERE signal_id IN ({placeholders})
                    ORDER BY id DESC
                """
                rows = conn.execute(query, chunk).fetchall()
                for row in rows:
                    key = str(row["signal_id"] or "")
                    if key and key not in result:
                        result[key] = dict(row)
        return result

    def signal_summary(
        self, instrument_key: str, trading_date: str, run_id: str | None = None
    ) -> dict[str, int]:
        rows = self.read_signal_attempts(instrument_key, trading_date, run_id)
        return {
            "attempts": len(rows),
            "active": sum(row["state"] == SignalState.ACTIVE.value for row in rows),
            "failed": sum(
                row["state"]
                in {
                    SignalState.CONFIRMATION_FAILED.value,
                    SignalState.TIMEOUT.value,
                }
                for row in rows
            ),
            "awaiting": sum(
                row["state"] == SignalState.AWAITING_CONFIRMATION.value
                for row in rows
            ),
            "bullish": sum(
                row["direction"] == Direction.BULLISH.value for row in rows
            ),
            "bearish": sum(
                row["direction"] == Direction.BEARISH.value for row in rows
            ),
        }

    def read_signal_attempts_range(
        self,
        instrument_key: str,
        date_from: str,
        date_to: str,
    ) -> list[dict[str, object]]:
        self._db.initialize()
        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM signal_attempts
                WHERE instrument_key=?
                  AND trading_date>=?
                  AND trading_date<=?
                ORDER BY trading_date, confirmation_timestamp, signal_id
                """,
                (instrument_key, date_from, date_to),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_signal_state(
        self,
        signal_id: str,
        state: str,
    ) -> None:
        """Persist a lifecycle state change for one signal."""
        self._db.initialize()
        with self._db._connect() as conn:
            conn.execute(
                """
                UPDATE signal_attempts
                SET state=?
                WHERE signal_id=?
                """,
                (state, signal_id),
            )
            conn.commit()
