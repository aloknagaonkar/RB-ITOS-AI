from pathlib import Path
import sqlite3
import json

ROOT = Path.cwd()

db_files = [
    path for path in ROOT.rglob("*.db")
    if ".venv" not in str(path) and "site-packages" not in str(path)
]

if not db_files:
    print("No SQLite .db files found under:", ROOT)
    raise SystemExit(1)

print("SQLite databases found:")
for index, path in enumerate(db_files, start=1):
    print(f"  {index}. {path}")

# Prefer the largest database because it is normally the active application DB.
db_path = max(db_files, key=lambda item: item.stat().st_size)
print("\nInspecting:", db_path)
print("Size:", db_path.stat().st_size, "bytes")

keywords = (
    "red_bar",
    "v2",
    "reference",
    "snapshot",
    "direction",
    "admission",
    "futures",
    "vwap",
    "rsi",
)

with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row

    tables = [
        row["name"]
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    ]

    print("\nAll tables:")
    for table in tables:
        print(" ", table)

    candidate_tables = [
        table
        for table in tables
        if any(keyword in table.lower() for keyword in keywords)
    ]

    print("\nCandidate Red Bar V2 tables:")
    if not candidate_tables:
        print("  No table name directly matched.")
    else:
        for table in candidate_tables:
            print(" ", table)

    for table in candidate_tables:
        print("\n" + "=" * 100)
        print("TABLE:", table)

        columns = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        column_names = [row["name"] for row in columns]
        print("COLUMNS:")
        print(" ", ", ".join(column_names))

        order_column = next(
            (
                name for name in (
                    "updated_at",
                    "observed_timestamp",
                    "evaluated_at",
                    "created_at",
                    "timestamp",
                    "trading_date",
                    "id",
                )
                if name in column_names
            ),
            None,
        )

        query = f'SELECT * FROM "{table}"'
        if order_column:
            query += f' ORDER BY "{order_column}" DESC'
        query += " LIMIT 5"

        try:
            rows = conn.execute(query).fetchall()
        except Exception as exc:
            print("READ ERROR:", exc)
            continue

        print("LATEST ROWS:", len(rows))
        for row in rows:
            data = dict(row)
            interesting = {
                key: value
                for key, value in data.items()
                if value not in (None, "")
                and any(keyword in key.lower() for keyword in keywords)
            }
            print(json.dumps(interesting or data, indent=2, default=str))

print("\nDiagnostic completed. Database was opened read-only for SELECT operations.")
