"""Existing-store adapter tests; temporary synthetic application DBs."""
import sqlite3

import pytest

from existing_application_store import ExistingApplicationStore
from test_production_refusal_candidate import (
    prepared, verify_candidate, env, bound_env, rows,
)
from hilega_application_preparation_fixtures import PIN
from refusal_record_operations import execute_record


def test_construction_initializes_nothing(prepared):
    e = prepared
    before = e["store"].path.read_bytes()
    store = ExistingApplicationStore(e["store"].path)
    assert store.path == e["store"].path.absolute()
    assert e["store"].path.read_bytes() == before


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(ValueError, match="^EXISTING_REGULAR_FILE_REQUIRED$"):
        ExistingApplicationStore(path)
    assert not path.exists()


def test_symlink_lock_is_rejected(tmp_path):
    path = tmp_path / "application.sqlite"
    with sqlite3.connect(path):
        pass
    path.chmod(0o600)
    other = tmp_path / "other.lock"
    other.write_text("")
    other.chmod(0o600)
    (tmp_path / "application.sqlite.control.lock").symlink_to(other)
    store = ExistingApplicationStore(path)
    with pytest.raises(ValueError, match="^EXISTING_REGULAR_FILE_REQUIRED$"):
        with store.lock():
            pytest.fail("Symlink lock accepted")


def test_operational_record_uses_existing_store(prepared, tmp_path):
    e = prepared
    store = ExistingApplicationStore(e["store"].path)
    result = execute_record(
        store, e["adapter_store"].path,
        pin_reader=lambda: dict(PIN), clock=lambda: e["clock"][0],
        backup_root=tmp_path / "backups",
    )
    assert result["persistence_outcome"] == "VERIFIED_COMMITTED_REFUSAL", result
    assert len(rows(e)) == 1
    assert result["production_execution_enabled"] is False


def test_transaction_exception_rolls_back(prepared):
    e = prepared
    store = ExistingApplicationStore(e["store"].path)

    class Interrupted(BaseException):
        pass

    with pytest.raises(Interrupted):
        with store.lock(), store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE synthetic_rollback_probe(id INTEGER)")
            db.execute("INSERT INTO synthetic_rollback_probe VALUES(1)")
            raise Interrupted()

    with store.db() as db:
        assert db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='synthetic_rollback_probe'"
        ).fetchone() is None