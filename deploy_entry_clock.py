from contextlib import closing
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

ROOT = Path.cwd().resolve()
STAGE = ROOT / "hilega-entry-clock-stage-a6h90flu"
PYTHON = ROOT / ".venv/bin/python"
CONTROL = ROOT / "scripts/hilega_supervised_control.py"

SOURCE = "backend/market_lab/hilega_preparation_runtime_v1/source.py"
MANIFEST = "hilega-ownership-producer-tools-v1/manifest.json"
TARGETS = [
    (SOURCE, STAGE / "source.py",
     "c792ebb12ab5d17a20d624843c8f6a2af7b8405fd69439d68c283a2ee1bb1a5b",
     "8163ca0db32a5fc95358368d2f474a6f0e083c853cb97008b7574f1241310f71"),
    (MANIFEST, STAGE / MANIFEST,
     "09ac943ec667024266520a6382cffa75d02d6f7939222e95a0894cd305ef4857",
     "4fe45c48b1520e60dc2a0c59a3adcc7ed5f136fab4601abcd6129389f38e8598"),
]
DATABASES = [
    ROOT / "data/research/hilega-production-workspace/sim.sqlite",
    ROOT / "data/research/hilega-broker-adapter-closed/adapter.sqlite",
]
TABLES = (
    "preparation_entry_ownership_state",
    "preparation_entry_ownership_reviews",
    "preparation_entry_ownership_audit",
    "preparation_account_captures",
)


def need(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def sha(path):
    need(path.is_file() and not path.is_symlink(),
         "REGULAR_FILE_REQUIRED")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def ownership_snapshot():
    with closing(sqlite3.connect(
        DATABASES[0].resolve().as_uri() + "?mode=ro", uri=True
    )) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        rows = {}
        for table in TABLES:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            rows[table] = (
                db.execute("SELECT * FROM " + table + " ORDER BY rowid").fetchall()
                if exists else None
            )
        db.rollback()
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "counts": {k: None if v is None else len(v) for k, v in rows.items()},
    }


def install(candidate, target):
    mode = target.stat().st_mode & 0o777
    fd, temporary = tempfile.mkstemp(prefix=".clock-install-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(candidate.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


proof = json.loads((STAGE / "producer-pair-validation.json").read_text())
need(proof["status"] == "STAGED_CLOCK_PRODUCER_PACKAGE_CHECK_PASS",
     "STAGED_PACKAGE_VALIDATION_REQUIRED")

for relative, candidate, before, after in TARGETS:
    need(sha(ROOT / relative) == before, "INSTALLED_TARGET_CHANGED")
    need(sha(candidate) == after, "STAGED_TARGET_CHANGED")
    if relative == SOURCE:
        compile(candidate.read_bytes(), str(candidate), "exec")
need(proof["candidate_source_sha256"] == TARGETS[0][3]
     and proof["candidate_manifest_sha256"] == TARGETS[1][3],
     "VALIDATION_PROOF_TARGET_MISMATCH")

run(str(PYTHON), "check-preparation-paused.py")
before_records = ownership_snapshot()

backup_root = ROOT / "backups"
backup_root.mkdir(exist_ok=True)
backup = Path(tempfile.mkdtemp(prefix="hilega-entry-clock-", dir=backup_root))
report = {
    "backup": str(backup),
    "started_at": datetime.now(timezone.utc).isoformat(),
    "ownership_before": before_records,
    "production_execution_enabled": False,
    "database_migration_performed": False,
}


def phase(value):
    report["phase"] = value
    (backup / "deployment.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"phase": value, "backup": str(backup)}), flush=True)


for relative, candidate, before, after in TARGETS:
    destination = backup / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / relative, destination)

phase("PREPARED")
try:
    run(str(PYTHON), str(CONTROL), "stop")
    phase("PREPARATION_SERVICES_STOPPED")
    need(ownership_snapshot() == before_records,
         "OWNERSHIP_RECORDS_CHANGED_BEFORE_INSTALL")

    for index, database in enumerate(DATABASES):
        sha(database)
        with closing(sqlite3.connect(
            database.resolve().as_uri() + "?mode=ro", uri=True
        )) as source, closing(sqlite3.connect(
            backup / ("database-" + str(index) + ".sqlite")
        )) as destination:
            source.backup(destination)

    phase("DATABASES_BACKED_UP")
    for relative, candidate, before, after in TARGETS:
        need(sha(ROOT / relative) == before, "TARGET_CHANGED_BEFORE_INSTALL")
        need(sha(candidate) == after, "CANDIDATE_CHANGED_BEFORE_INSTALL")
        install(candidate, ROOT / relative)
        need(sha(ROOT / relative) == after, "INSTALLED_HASH_MISMATCH")

    producer = ROOT / "hilega-ownership-producer-tools-v1/producer.py"
    spec = importlib.util.spec_from_file_location("clock_deploy_producer", producer)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.package_check(ROOT)
    need(ownership_snapshot() == before_records,
         "OWNERSHIP_RECORDS_CHANGED_DURING_INSTALL")
    phase("FILES_INSTALLED_PACKAGE_VERIFIED")

    run(str(PYTHON), str(CONTROL), "start")
    run(str(PYTHON), "check-preparation-paused.py")
    need(ownership_snapshot() == before_records,
         "OWNERSHIP_RECORDS_CHANGED_AFTER_START")
    report["ownership_records_preserved"] = True
    phase("DEPLOYED_POSTCHECK_COMPLETED")
    print("Review the printed health status; heartbeat freshness may need a later check.")
except BaseException:
    phase("STOPPED_FOR_REVIEW")
    print("Do not rerun installer. Preserve this backup and deployment report.")
    raise