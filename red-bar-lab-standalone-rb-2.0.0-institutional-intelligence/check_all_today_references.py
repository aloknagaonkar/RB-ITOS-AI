import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from red_bar_lab.config import RedBarSettings

settings = RedBarSettings.from_env()
today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()

con = sqlite3.connect(str(settings.database_path))
con.row_factory = sqlite3.Row

rows = con.execute(
    """
    SELECT
        id,
        instrument_key,
        trading_date,
        level_type,
        source_timestamp,
        source_high,
        source_low,
        midpoint,
        level_value,
        data_quality
    FROM reference_levels
    WHERE trading_date = ?
    ORDER BY id DESC
    """,
    (today,),
).fetchall()

print("Database:", settings.database_path)
print("Trading date:", today)
print("All reference rows today:", len(rows))

for row in rows:
    print(dict(row))

con.close()
