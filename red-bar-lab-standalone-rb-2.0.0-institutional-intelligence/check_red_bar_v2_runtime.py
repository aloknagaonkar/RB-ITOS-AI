from pathlib import Path
import sqlite3
import json

db_path = Path(
    "artifacts/red_bar/database/red_bar_strategy.db"
)

tables_to_check = (
    "paper_monitor_status",
    "strategy_runs",
    "intelligence_pipeline_run_status",
    "signal_pipeline_status",
    "candidate_lifecycle",
    "execution_state_events",
    "paper_signal_diagnostics",
)

with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row

    existing = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    for table in tables_to_check:
        print("\n" + "=" * 100)
        print("TABLE:", table)

        if table not in existing:
            print("NOT PRESENT")
            continue

        columns = [
            row["name"]
            for row in conn.execute(
                f'PRAGMA table_info("{table}")'
            )
        ]
        print("COLUMNS:", ", ".join(columns))

        order_column = next(
            (
                name
                for name in (
                    "updated_at",
                    "timestamp",
                    "evaluated_at",
                    "created_at",
                    "heartbeat_at",
                    "last_scan_at",
                    "trading_date",
                    "id",
                )
                if name in columns
            ),
            None,
        )

        query = f'SELECT * FROM "{table}"'
        if order_column:
            query += f' ORDER BY "{order_column}" DESC'
        query += " LIMIT 10"

        for row in conn.execute(query):
            print(json.dumps(dict(row), indent=2, default=str))

    print("\n" + "=" * 100)
    print("ALL 20-AUG REFERENCE LEVELS")

    rows = conn.execute(
        """
        SELECT *
        FROM reference_levels
        WHERE trading_date = '2026-08-20'
          AND instrument_key = 'NSE_INDEX|Nifty 50'
        ORDER BY level_type
        """
    ).fetchall()

    for row in rows:
        print(json.dumps(dict(row), indent=2, default=str))

    print("\n" + "=" * 100)
    print("20-AUG SIGNAL COUNTS")

    for table, date_column in (
        ("signal_attempts", "trading_date"),
        ("market_context_snapshots", "trading_date"),
        ("volume_structure_snapshots", "trading_date"),
        ("option_context_snapshots", "trading_date"),
    ):
        count = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {table}
            WHERE {date_column} = '2026-08-20'
            """
        ).fetchone()[0]
        print(f"{table}: {count}")

