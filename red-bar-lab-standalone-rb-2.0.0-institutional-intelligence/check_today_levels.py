import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from red_bar_lab.config import RedBarSettings

settings = RedBarSettings.from_env()
today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()

con = sqlite3.connect(str(settings.database_path))
con.row_factory = sqlite3.Row

print("Database:", settings.database_path)
print("Trading date:", today)

print()
print("reference_levels columns:")
columns = con.execute("PRAGMA table_info(reference_levels)").fetchall()
for column in columns:
    print(column["name"])

print()
rows = con.execute(
    """
    SELECT *
    FROM reference_levels
    WHERE trading_date = ?
    ORDER BY id DESC
    """,
    (today,),
).fetchall()

print("All reference rows today:", len(rows))
for row in rows:
    print(dict(row))

con.close()
