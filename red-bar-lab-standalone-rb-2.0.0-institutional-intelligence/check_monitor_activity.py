import sqlite3
from red_bar_lab.config import RedBarSettings

settings = RedBarSettings.from_env()
con = sqlite3.connect(str(settings.database_path))
con.row_factory = sqlite3.Row

for table, query in [
    (
        "paper_monitor_status",
        """
        SELECT *
        FROM paper_monitor_status
        ORDER BY updated_at DESC
        LIMIT 5
        """
    ),
    (
        "paper_signal_diagnostics",
        """
        SELECT *
        FROM paper_signal_diagnostics
        ORDER BY timestamp DESC
        LIMIT 10
        """
    ),
]:
    print()
    print("=" * 80)
    print(table)

    try:
        rows = con.execute(query).fetchall()
        print("Rows:", len(rows))
        for row in rows:
            print(dict(row))
    except Exception as exc:
        print("ERROR:", exc)

con.close()
