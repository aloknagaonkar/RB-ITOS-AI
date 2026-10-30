"""Guard candidate tests; synthetic pins and temporary databases only."""
from pathlib import Path
from unittest.mock import Mock
import sqlite3

import pytest

import guarded_refusal_record as guard
from test_production_refusal_candidate import (
    prepared, verify_candidate, env, bound_env, rows,
)
from test_hilega_application_preparation_v1 import command
from hilega_application_preparation_fixtures import PIN


def backup_copy(e, path):
    with sqlite3.connect(e["store"].path) as source:
        with sqlite3.connect(path) as target:
            source.backup(target)
    return path


def test_prepared_request_backed_up_before_record(prepared, tmp_path):
    e = prepared
    path = tmp_path / "before-record.sqlite"
    backup = Mock(side_effect=lambda: backup_copy(e, path))
    result = guard.guarded_record(
        e["store"], e["adapter_store"].path,
        pin_reader=lambda: dict(PIN), clock=lambda: e["clock"][0],
        backup=backup,
    )
    backup.assert_called_once()
    assert path.is_file()
    assert len(rows(e)) == 1
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE name='preparation_closed_dispatch_decisions'"
        ).fetchone() is None
    assert result["production_execution_enabled"] is False


def test_empty_application_does_not_backup_or_write(bound_env):
    e = bound_env
    command(e["s"], "pause")
    before = e["store"].path.read_bytes()
    backup = Mock(side_effect=AssertionError("No backup expected"))
    result = guard.guarded_record(
        e["store"], e["adapter_store"].path,
        pin_reader=lambda: dict(PIN), clock=lambda: e["clock"][0],
        backup=backup,
    )
    assert result["status"] == "NO_PREPARED_REQUEST_NO_WRITE"
    backup.assert_not_called()
    assert e["store"].path.read_bytes() == before


def test_backup_failure_prevents_record(prepared):
    e = prepared
    backup = Mock(side_effect=OSError("SYNTHETIC_BACKUP_FAILURE"))
    with pytest.raises(OSError, match="SYNTHETIC_BACKUP_FAILURE"):
        guard.guarded_record(
            e["store"], e["adapter_store"].path,
            pin_reader=lambda: dict(PIN), clock=lambda: e["clock"][0],
            backup=backup,
        )
    assert rows(e) == []


def test_pin_change_before_commit_rolls_back(prepared):
    e = prepared
    current = [dict(PIN)]

    def checkpoint(stage):
        if stage == "BEFORE_COMMIT":
            current[0] = dict(PIN, scope="UPSTOX:" + "a" * 64)

    with pytest.raises(
        ValueError, match="^ACCOUNT_PIN_CHANGED_DURING_TRANSACTION$"
    ):
        guard.guarded_record(
            e["store"], e["adapter_store"].path,
            pin_reader=lambda: current[0],
            clock=lambda: e["clock"][0],
            backup=lambda: "SYNTHETIC_BACKUP_COMPLETED",
            checkpoint=checkpoint,
        )
    assert rows(e) == []