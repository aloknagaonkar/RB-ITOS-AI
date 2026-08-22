from __future__ import annotations

import sqlite3
from pathlib import Path

from red_bar_lab.services.option_participation_store import (
    read_latest_option_participation,
)


def test_missing_option_participation_database_is_not_created(tmp_path: Path):
    database_path = tmp_path / "missing.sqlite"

    assert read_latest_option_participation(database_path) == []
    assert not database_path.exists()


def test_option_participation_read_does_not_create_schema(tmp_path: Path):
    database_path = tmp_path / "existing.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
        before = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()

    assert read_latest_option_participation(database_path) == []

    with sqlite3.connect(database_path) as connection:
        after = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()

    assert after == before
    assert all(name != "option_participation_snapshots" for _, name, _ in after)
