"""One-shot bootstrap that materializes every table the V2 code paths
expect against an existing SQLite database file. Idempotent: every
``CREATE TABLE`` is ``IF NOT EXISTS``.

Usage (on the VM):
    cd /home/aloknagaonkar46/RB-ITOS-AI/red-bar-lab-standalone-rb-2.0.0-institutional-intelligence
    export PYTHONPATH="$PWD"
    source /home/aloknagaonkar46/venv/bin/activate
    python scripts/bootstrap_cloud_db.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DB_PATH = Path(
    os.environ.get(
        "RB_DB_PATH",
        "/home/aloknagaonkar46/RB-ITOS-AI/red-bar-lab-standalone-rb-2.0.0-institutional-intelligence/artifacts/red_bar/database/red_bar_strategy.db",
    )
)


def main() -> int:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}", file=sys.stderr)
        return 1

    print(f"DB: {DB_PATH}")
    print(f"size: {DB_PATH.stat().st_size:,} bytes")

    # 1. RedBarDatabase: creates the legacy + process_evidence schema
    from red_bar_lab.storage.database import RedBarDatabase
    RedBarDatabase(str(DB_PATH))
    print("[1/4] RedBarDatabase() applied")

    # 2. RedBarV2Storage: creates red_bar_v2_* tables (direction_events etc.)
    from red_bar_lab.storage.red_bar_v2_storage import RedBarV2Storage
    RedBarV2Storage(DB_PATH).initialize()
    print("[2/4] RedBarV2Storage.initialize() applied")

    # 3. Canonical repositories: create canonical_red_bar_v2_* tables
    from red_bar_lab.services.red_bar_v2_canonical.sqlite_repository import (
        SQLiteRedBarV2CanonicalRepository,
    )
    from red_bar_lab.services.red_bar_v2_canonical.reservation_repository import (
        SQLiteCanonicalReservationRepository,
    )
    from red_bar_lab.services.red_bar_v2_canonical.paper_execution_repository import (
        SQLiteCanonicalPaperExecutionRepository,
    )
    SQLiteRedBarV2CanonicalRepository(DB_PATH)
    SQLiteCanonicalReservationRepository(DB_PATH)
    SQLiteCanonicalPaperExecutionRepository(DB_PATH)
    print("[3/4] canonical repositories initialized")

    # 4. Print the schema delta
    import sqlite3
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    print(f"[4/4] final table_count = {len(rows)}")
    for r in rows:
        print(f"  - {r[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
