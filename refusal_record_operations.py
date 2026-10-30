"""Backup and result handling; no broker transport."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

from guarded_refusal_record import guarded_record


def regular(path):
    path = Path(path).absolute()
    if (not path.is_file() or path.is_symlink()
            or any(p.is_symlink() for p in path.parents)):
        raise ValueError("REGULAR_APPLICATION_DATABASE_REQUIRED")
    return path


def backup_application(application, backup_root):
    application = regular(application)
    parent = Path(backup_root).absolute()
    parent.mkdir(parents=True, exist_ok=True)
    if (parent.is_symlink()
            or any(p.is_symlink() for p in parent.parents)
            or parent.stat().st_uid != os.getuid()):
        raise ValueError("OWNED_BACKUP_DIRECTORY_REQUIRED")
    folder = Path(tempfile.mkdtemp(prefix="hilega-refusal-record-", dir=parent))
    destination = folder / "application-before-record.sqlite"
    try:
        with closing(sqlite3.connect(
            application.as_uri() + "?mode=ro", uri=True, timeout=10
        )) as source, closing(sqlite3.connect(destination)) as target:
            os.chmod(destination, 0o600)
            source.execute("PRAGMA query_only=ON")
            source.execute("BEGIN")
            source.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            source.backup(target)
            source.rollback()
            if target.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("BACKUP_INTEGRITY_CHECK_FAILED")
        return dict(
            path=str(destination),
            sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
            quick_check_passed=True,
        )
    except BaseException:
        # Only this newly created backup folder is removed.
        shutil.rmtree(folder)
        raise


def execute_record(store, adapter, *, pin_reader, clock, backup_root):
    backed_up = []

    def backup():
        result = backup_application(store.path, backup_root)
        backed_up.append(result)
        return result

    base = dict(
        assessed_at=datetime.now(timezone.utc).isoformat(),
        broker_reads_performed=False,
        orders_sent=False,
        entry_permission=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
        production_ready=False,
        automatic_write_retry=False,
    )
    try:
        result = guarded_record(
            store, adapter, pin_reader=pin_reader, clock=clock, backup=backup)
        base.update(result)
        base["persistence_outcome"] = (
            "NOT_ATTEMPTED" if result["status"] == "NO_PREPARED_REQUEST_NO_WRITE"
            else "RECORDER_RETURNED_AFTER_COMMIT"
        )
    except Exception as exc:
        reason = str(exc)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,179}", reason):
            reason = "RECORD_OPERATION_REVIEW_REQUIRED"
        base.update(
            status="REFUSAL_RECORD_STOPPED_FOR_REVIEW",
            reason=reason,
            # Without a successful return, do not assume a write rolled back.
            database_modified=None if backed_up else False,
            persistence_outcome=(
                "UNKNOWN_REVIEW_REQUIRED" if backed_up else "NOT_ATTEMPTED"),
        )
    if backed_up:
        base["backup"] = backed_up[0]
    return base