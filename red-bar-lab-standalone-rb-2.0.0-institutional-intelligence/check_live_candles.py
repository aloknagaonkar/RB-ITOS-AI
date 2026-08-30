import pandas as pd
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

root = Path("artifacts/red_bar/data/live")
files = sorted(root.rglob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)

if not files:
    print("No live CSV files found.")
    raise SystemExit(1)

path = files[0]
print("Live file:", path.resolve())
print("Modified:", datetime.fromtimestamp(path.stat().st_mtime))

df = pd.read_csv(path)
print("Rows:", len(df))
print("Columns:", list(df.columns))

if "timestamp" in df.columns:
    ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    ist = ts.dt.tz_convert("Asia/Kolkata")
    current = df.loc[ist.dt.date == today]

    print("Today's rows:", len(current))
    if not current.empty:
        print(current.tail(10).to_string(index=False))
else:
    print("timestamp column missing")
