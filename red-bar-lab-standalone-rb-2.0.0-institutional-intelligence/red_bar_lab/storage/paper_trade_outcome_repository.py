"""Repository for paper_trade_outcomes domain."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from red_bar_lab.storage.database import RedBarDatabase


class PaperTradeOutcomeRepository:
    """Domain-specific repository for paper trade outcome operations."""

    def __init__(self, database: RedBarDatabase) -> None:
        self._db = database

    def replace_paper_trade_outcomes(
        self,
        instrument_key: str,
        trading_date: str,
        outcomes,
    ) -> int:
        self._db.initialize()
        now = datetime.now(timezone.utc).isoformat()

        with self._db._connect() as conn:
            existing = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(paper_trade_outcomes)"
                )
            }
            required = {
                "risk_points": "REAL",
                "exit_model": "TEXT",
                "model_parameter": "TEXT",
                "r_multiple": "REAL",
                "session_mfe_points": "REAL",
                "session_mae_points": "REAL",
                "session_extreme_price": "REAL",
                "session_extreme_timestamp": "TEXT",
                "move_after_target_points": "REAL",
                "minutes_from_target_to_extreme": "INTEGER",
                "giveback_from_extreme_points": "REAL",
            }
            for name, sql_type in required.items():
                if name not in existing:
                    conn.execute(
                        f"ALTER TABLE paper_trade_outcomes "
                        f"ADD COLUMN {name} {sql_type}"
                    )

            conn.execute(
                """
                DELETE FROM paper_trade_outcomes
                WHERE instrument_key=? AND trading_date=?
                """,
                (instrument_key, trading_date),
            )

            for item in outcomes:
                conn.execute(
                    """
                    INSERT INTO paper_trade_outcomes(
                        trade_id,
                        signal_id,
                        instrument_key,
                        trading_date,
                        level_type,
                        direction,
                        entry_timestamp,
                        entry_price,
                        stop_price,
                        risk_points,
                        exit_model,
                        model_parameter,
                        target_points,
                        target_price,
                        exit_timestamp,
                        exit_price,
                        exit_reason,
                        status,
                        points,
                        r_multiple,
                        mfe,
                        mae,
                        holding_minutes,
                        session_mfe_points,
                        session_mae_points,
                        session_extreme_price,
                        session_extreme_timestamp,
                        move_after_target_points,
                        minutes_from_target_to_extreme,
                        giveback_from_extreme_points,
                        created_at,
                        updated_at
                    ) VALUES(
                        ?,?,?,?,?,?,?,?,?,?,
                        ?,?,?,?,?,?,?,?,?,?,
                        ?,?,?,?,?,?,?,?,?,?,
                        ?,?
                    )
                    """,
                    (
                        item.trade_id,
                        item.signal_id,
                        item.instrument_key,
                        item.trading_date,
                        item.level_type,
                        item.direction,
                        item.entry_timestamp.isoformat(),
                        item.entry_price,
                        item.stop_price,
                        item.risk_points,
                        item.exit_model.value,
                        item.model_parameter,
                        item.target_points,
                        item.target_price,
                        item.exit_timestamp.isoformat()
                        if item.exit_timestamp
                        else None,
                        item.exit_price,
                        item.exit_reason.value,
                        item.status.value,
                        item.points,
                        item.r_multiple,
                        item.mfe,
                        item.mae,
                        item.holding_minutes,
                        item.session_mfe_points,
                        item.session_mae_points,
                        item.session_extreme_price,
                        item.session_extreme_timestamp.isoformat()
                        if item.session_extreme_timestamp
                        else None,
                        item.move_after_target_points,
                        item.minutes_from_target_to_extreme,
                        item.giveback_from_extreme_points,
                        now,
                        now,
                    ),
                )
            conn.commit()

        return len(outcomes)

    def read_paper_trade_outcomes(
        self,
        instrument_key: str,
        trading_date: str,
    ) -> list[dict[str, object]]:
        self._db.initialize()

        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM paper_trade_outcomes
                WHERE instrument_key=? AND trading_date=?
                ORDER BY
                    entry_timestamp,
                    level_type,
                    exit_model,
                    model_parameter
                """,
                (instrument_key, trading_date),
            ).fetchall()

        return [dict(row) for row in rows]

    def paper_trade_summary(
        self,
        instrument_key: str,
        trading_date: str,
    ) -> dict[str, object]:
        rows = self.read_paper_trade_outcomes(
            instrument_key,
            trading_date,
        )
        evaluable = [
            row
            for row in rows
            if row["exit_reason"] != "NOT_EVALUABLE"
            and row["points"] is not None
        ]
        winners = [
            row for row in evaluable if float(row["points"]) > 0
        ]
        losers = [
            row for row in evaluable if float(row["points"]) < 0
        ]

        gross_profit = sum(
            float(row["points"]) for row in winners
        )
        gross_loss = abs(
            sum(float(row["points"]) for row in losers)
        )
        net_points = sum(
            float(row["points"]) for row in evaluable
        )

        return {
            "trades": len(rows),
            "evaluable": len(evaluable),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": (
                len(winners) / len(evaluable) * 100.0
                if evaluable
                else 0.0
            ),
            "net_points": net_points,
            "average_points": (
                net_points / len(evaluable)
                if evaluable
                else 0.0
            ),
            "profit_factor": (
                gross_profit / gross_loss
                if gross_loss > 0
                else None
            ),
        }

    def paper_trade_range_rows(
        self,
        instrument_key: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, object]]:
        self._db.initialize()

        with self._db._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM paper_trade_outcomes
                WHERE instrument_key=?
                  AND trading_date>=?
                  AND trading_date<=?
                ORDER BY
                    trading_date,
                    entry_timestamp,
                    level_type,
                    exit_model,
                    model_parameter
                """,
                (
                    instrument_key,
                    start_date,
                    end_date,
                ),
            ).fetchall()

        return [dict(row) for row in rows]

    def paper_trade_range_summary(
        self,
        instrument_key: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, object]:
        rows = self.paper_trade_range_rows(
            instrument_key,
            start_date,
            end_date,
        )
        evaluable = [
            row
            for row in rows
            if row["exit_reason"] != "NOT_EVALUABLE"
            and row["points"] is not None
        ]
        winners = [
            row for row in evaluable if float(row["points"]) > 0
        ]
        losers = [
            row for row in evaluable if float(row["points"]) < 0
        ]

        gross_profit = sum(
            float(row["points"]) for row in winners
        )
        gross_loss = abs(
            sum(float(row["points"]) for row in losers)
        )
        net_points = sum(
            float(row["points"]) for row in evaluable
        )

        return {
            "rows": len(rows),
            "evaluable": len(evaluable),
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": (
                len(winners) / len(evaluable) * 100.0
                if evaluable
                else 0.0
            ),
            "net_points": net_points,
            "average_points": (
                net_points / len(evaluable)
                if evaluable
                else 0.0
            ),
            "profit_factor": (
                gross_profit / gross_loss
                if gross_loss > 0
                else None
            ),
        }

    def read_paper_trade_outcomes_range(
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
                FROM paper_trade_outcomes
                WHERE instrument_key=?
                  AND trading_date>=?
                  AND trading_date<=?
                ORDER BY trading_date, entry_timestamp, trade_id
                """,
                (instrument_key, date_from, date_to),
            ).fetchall()
        return [dict(row) for row in rows]
