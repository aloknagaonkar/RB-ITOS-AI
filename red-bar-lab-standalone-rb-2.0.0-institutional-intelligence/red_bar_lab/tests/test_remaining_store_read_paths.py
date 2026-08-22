import sqlite3
from pathlib import Path

from red_bar_lab.services.global_readiness_store import (
    read_global_readiness_snapshots,
)
from red_bar_lab.services.nifty_futures_snapshot_store import (
    read_nifty_futures_snapshots,
)


def _schema_objects(path: Path):
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()


def test_global_readiness_read_does_not_create_schema(tmp_path: Path):
    path = tmp_path / "readiness.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    before = _schema_objects(path)

    assert read_global_readiness_snapshots(path) == []

    assert _schema_objects(path) == before


def test_futures_read_does_not_create_or_alter_schema(tmp_path: Path):
    path = tmp_path / "futures.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    before = _schema_objects(path)

    assert read_nifty_futures_snapshots(path) == []

    assert _schema_objects(path) == before


def test_missing_database_reads_do_not_create_files(tmp_path: Path):
    readiness = tmp_path / "missing-readiness.sqlite"
    futures = tmp_path / "missing-futures.sqlite"

    assert read_global_readiness_snapshots(readiness) == []
    assert read_nifty_futures_snapshots(futures) == []
    assert readiness.exists() is False
    assert futures.exists() is False
