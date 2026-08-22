import sqlite3

from red_bar_lab.services.red_bar_v2_canonical import SQLiteRedBarV2CanonicalRepository


def test_schema_creation_is_idempotent_and_preserves_unrelated_tables(tmp_path):
    path = tmp_path / "red_bar.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated_table(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO unrelated_table(value) VALUES('preserved')")
        conn.commit()

    SQLiteRedBarV2CanonicalRepository(path)
    SQLiteRedBarV2CanonicalRepository(path)

    with sqlite3.connect(path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert conn.execute("SELECT value FROM unrelated_table").fetchone() == ("preserved",)
        assert conn.execute("PRAGMA foreign_keys").fetchone() == (0,)

    assert {
        "canonical_red_bar_v2_resolutions",
        "canonical_red_bar_v2_bundles",
        "canonical_red_bar_v2_bundle_events",
    }.issubset(tables)
    assert {
        "idx_canonical_rbv2_resolution_session",
        "idx_canonical_rbv2_resolution_replay",
        "idx_canonical_rbv2_bundle_session",
        "idx_canonical_rbv2_bundle_event_history",
    }.issubset(indexes)


def test_repository_connection_enforces_foreign_keys(tmp_path):
    repository = SQLiteRedBarV2CanonicalRepository(tmp_path / "red_bar.db")
    with repository._connect() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
