from pathlib import Path
import sqlite3
import json

db_path = Path("artifacts/red_bar/database/red_bar_strategy.db")

uri = f"file:{db_path.resolve().as_posix()}?mode=ro"

with sqlite3.connect(uri, uri=True) as conn:
    conn.row_factory = sqlite3.Row

    signal = conn.execute(
        """
        SELECT *
        FROM paper_signal_diagnostics
        WHERE signal_id LIKE 'RBV2-%'
        ORDER BY timestamp DESC, id DESC
        LIMIT 1
        """
    ).fetchone()

    if not signal:
        print("No current Red Bar V2 signal diagnostic found.")
        raise SystemExit(0)

    signal = dict(signal)
    signal_id = signal.get("signal_id")

    print("\nLATEST SIGNAL")
    print(json.dumps(signal, indent=2, default=str))

    checks = [
        (
            "PIPELINE STATUS",
            """
            SELECT *
            FROM signal_pipeline_status
            WHERE signal_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
        ),
        (
            "PERFORMANCE SELECTION",
            """
            SELECT *
            FROM trade_selection_evaluations
            WHERE signal_id = ?
            ORDER BY evaluated_at DESC
            LIMIT 10
            """,
        ),
        (
            "COMMITTEE EVALUATION",
            """
            SELECT *
            FROM institutional_execution_evaluations
            WHERE signal_id = ?
            ORDER BY evaluated_at DESC
            LIMIT 10
            """,
        ),
        (
            "CANDIDATE LIFECYCLE",
            """
            SELECT *
            FROM candidate_lifecycle
            WHERE signal_id = ?
            ORDER BY updated_at DESC
            LIMIT 20
            """,
        ),
        (
            "EXECUTION EVENTS",
            """
            SELECT *
            FROM execution_state_events
            WHERE signal_id = ?
            ORDER BY timestamp DESC
            LIMIT 20
            """,
        ),
    ]

    for title, query in checks:
        print("\n" + "=" * 100)
        print(title)
        rows = conn.execute(query, (signal_id,)).fetchall()
        if not rows:
            print("NO ROWS")
            continue
        for row in rows:
            print(json.dumps(dict(row), indent=2, default=str))

    print("\n" + "=" * 100)
    print("LATEST MONITOR STATUS")

    row = conn.execute(
        """
        SELECT *
        FROM paper_monitor_status
        ORDER BY updated_at DESC
        LIMIT 1
        """
    ).fetchone()

    print(json.dumps(dict(row), indent=2, default=str) if row else "NO ROW")
