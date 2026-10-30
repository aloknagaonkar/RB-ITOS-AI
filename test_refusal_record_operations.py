"""Operational adapters tested on synthetic temporary application DBs."""
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

import refusal_record_operations as operations
from test_production_refusal_candidate import (
    prepared, verify_candidate, env, bound_env, rows,
)
from hilega_application_preparation_fixtures import PIN


def test_backup_is_valid_private_and_preserves_source(tmp_path):
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE evidence(value TEXT)")
        db.execute("INSERT INTO evidence VALUES('synthetic')")
    before = source.read_bytes()
    result = operations.backup_application(source, tmp_path / "backups")
    backup = Path(result["path"])
    assert result["quick_check_passed"] is True
    assert backup.stat().st_mode & 0o077 == 0
    assert backup.parent.stat().st_mode & 0o077 == 0
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT value FROM evidence").fetchone() == ("synthetic",)
    assert source.read_bytes() == before


def test_missing_source_does_not_create_database(tmp_path):
    source = tmp_path / "missing.sqlite"
    with pytest.raises(ValueError, match="^REGULAR_APPLICATION_DATABASE_REQUIRED$"):
        operations.backup_application(source, tmp_path / "backups")
    assert not source.exists()


def invoke(e, tmp_path):
    return operations.execute_record(
        e["store"], e["adapter_store"].path,
        pin_reader=lambda: dict(PIN), clock=lambda: e["clock"][0],
        backup_root=tmp_path / "backups",
    )


def test_success_reports_committed_result(prepared, tmp_path):
    e = prepared
    result = invoke(e, tmp_path)
    assert result["persistence_outcome"] == "RECORDER_RETURNED_AFTER_COMMIT"
    assert result["database_modified"] is True
    assert result["backup"]["quick_check_passed"] is True
    assert len(rows(e)) == 1
    assert result["automatic_write_retry"] is False
    assert result["orders_sent"] is False


def test_backup_failure_reports_no_write_attempt(prepared, tmp_path):
    e = prepared
    with patch.object(
        operations, "backup_application",
        side_effect=OSError("synthetic private detail"),
    ):
        result = invoke(e, tmp_path)
    assert result["persistence_outcome"] == "NOT_ATTEMPTED"
    assert result["database_modified"] is False
    assert result["reason"] == "RECORD_OPERATION_REVIEW_REQUIRED"
    assert "synthetic private detail" not in str(result)
    assert rows(e) == []


def test_lost_post_commit_response_is_unknown_no_retry(prepared, tmp_path):
    e = prepared
    original = operations.guarded_record
    calls = []

    def lost_response(*args, **kwargs):
        calls.append(1)
        original(*args, **kwargs)
        raise OSError("synthetic lost result after commit")

    with patch.object(operations, "guarded_record", lost_response):
        result = invoke(e, tmp_path)
    assert calls == [1]
    assert len(rows(e)) == 1
    assert result["persistence_outcome"] == "UNKNOWN_REVIEW_REQUIRED"
    assert result["database_modified"] is None
    assert result["automatic_write_retry"] is False
    assert result["orders_sent"] is False