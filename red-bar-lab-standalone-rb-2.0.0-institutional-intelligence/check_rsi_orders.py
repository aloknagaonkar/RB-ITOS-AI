import sqlite3

db = r"C:\Users\Machine\Documents\GitHub\RB-ITOS-AI\red-bar-lab-standalone-rb-2.0.0-institutional-intelligence\artifacts\red_bar\database\red_bar_strategy.db"

signal_ids = (
    "RSI7-AD698253A7382CEE",
    "RSI7-B1AA0D00DCECF31B",
)

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

columns = [
    row["name"]
    for row in conn.execute(
        "PRAGMA table_info(paper_execution_orders)"
    )
]

print("Available columns:")
print(columns)

rows = conn.execute(
    """
    SELECT *
    FROM paper_execution_orders
    WHERE signal_id IN (?, ?)
    ORDER BY entry_timestamp DESC
    """,
    signal_ids,
).fetchall()

print(f"\nOrders found: {len(rows)}")

for row in rows:
    data = dict(row)
    print("\n" + "-" * 80)
    for field in (
        "order_id",
        "account_id",
        "signal_id",
        "tradingsymbol",
        "status",
        "execution_strategy_source",
        "entry_price",
        "current_price",
        "quantity",
        "entry_timestamp",
        "exit_timestamp",
        "exit_reason",
        "unrealized_pnl",
        "realized_pnl",
    ):
        print(f"{field}: {data.get(field)}")

conn.close()
