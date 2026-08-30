import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from red_bar_lab.config import RedBarSettings

settings = RedBarSettings.from_env()
today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()

con = sqlite3.connect(str(settings.database_path))
rows = con.execute(
    """
    SELECT
        instrument_key,
        trading_date,
        level_type,
        source_timestamp,
        source_high,
        source_low,
        midpoint,
        data_quality
    FROM reference_levels
    WHERE instrument_key = ?
      AND trading_date = ?
      AND level_type = ?
    ORDER BY id DESC
    """,
    (
        "NSE_INDEX|Nifty 50",
        today,
        "NEXT_RED_CANDLE",
    ),
).fetchall()

print("IST trading date:", today)
print("Rows found:", len(rows))

for row in rows:
    print(row)

con.close()
