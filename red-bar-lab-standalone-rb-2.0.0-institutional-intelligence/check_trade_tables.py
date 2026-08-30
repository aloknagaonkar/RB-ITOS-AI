import sqlite3

db = r"C:\Users\Machine\Documents\GitHub\RB-ITOS-AI\red-bar-lab-standalone-rb-2.0.0-institutional-intelligence\artifacts\red_bar\database\red_bar_strategy.db"

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

tables = [
    row["name"]
    for row in conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' ORDER BY name"
    )
]

print("Relevant tables:")
for table in tables:
    if any(
        word in table.lower()
        for word in ("paper", "order", "trade")
    ):
        print(" -", table)

conn.close()
