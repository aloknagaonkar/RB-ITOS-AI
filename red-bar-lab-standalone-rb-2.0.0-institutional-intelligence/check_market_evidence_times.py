import sqlite3
from pathlib import Path
from datetime import datetime, timezone

db = Path("artifacts/red_bar/database/red_bar_strategy.db")

with sqlite3.connect(db) as connection:
    connection.row_factory = sqlite3.Row

    option = connection.execute("""
        SELECT observed_at
        FROM option_participation_snapshots
        WHERE underlying_name = 'NIFTY 50'
        ORDER BY julianday(observed_at) DESC, observed_at DESC
        LIMIT 1
    """).fetchone()

    futures = connection.execute("""
        SELECT observed_at, latest_timestamp,
               positioning_state, strength
        FROM nifty_futures_diagnostic_snapshots
        WHERE underlying_name = 'NIFTY 50'
        ORDER BY julianday(observed_at) DESC, observed_at DESC
        LIMIT 1
    """).fetchone()

print("Current UTC:", datetime.now(timezone.utc).isoformat())
print("Option:", dict(option) if option else None)
print("Futures:", dict(futures) if futures else None)
