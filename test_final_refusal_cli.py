"""Final refusal CLI validation; no real account or production DB access."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

from test_hilega_application_preparation_v1 import env, process, command
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN

ROOT = Path.cwd().resolve()
PACKAGE = ROOT / "hilega-refusal-operations-tools-_w6qpenj"
EXPECTED = "b53ed7a5244c3335c9b18aec35cfe6af00070e7c232306e0018bb55fa45530ae"


@pytest.fixture
def package(tmp_path):
    manifest = PACKAGE / "manifest.json"
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == EXPECTED
    copied = tmp_path / "package"
    shutil.copytree(PACKAGE, copied)
    return copied


def run(package, action, *arguments):
    result = subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(package / "cli.py"),
         action, "--repo", str(ROOT), *map(str, arguments)],
        cwd=ROOT, capture_output=True, text=True, timeout=45,
    )
    return result


def arguments(e, tmp_path):
    # Synthetic test pin only; never read or copy the operator's private pin.
    assert PIN["scope"] == "UPSTOX:" + "b" * 64
    pin = tmp_path / "synthetic-pin.json"
    pin.write_text(json.dumps(dict(
        model="HILEGA_UPSTOX_ACCOUNT_PIN_V1",
        broker="UPSTOX", scope=PIN["scope"], key=PIN["key"],
        approved_at=datetime.now(timezone.utc).isoformat(),
    )))
    pin.chmod(0o600)
    return [
        "--application", e["store"].path,
        "--adapter", e["adapter_store"].path,
        "--pin-file", pin,
        "--backup-root", tmp_path / "backups",
    ]


def test_package_check(package):
    result = run(package, "package-check")
    report = json.loads(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["application_database_accessed"] is False


def test_empty_application_record_does_not_write(package, bound_env, tmp_path):
    e = bound_env
    command(e["s"], "pause")
    before = e["store"].path.read_bytes()
    result = run(package, "record", *arguments(e, tmp_path))
    report = json.loads(result.stdout)
    assert result.returncode == 0, report
    assert report["status"] == "NO_PREPARED_REQUEST_NO_WRITE"
    assert report["database_modified"] is False
    assert e["store"].path.read_bytes() == before
    assert not (tmp_path / "backups").exists()


def test_synthetic_refusal_record_and_inspect(package, bound_env, tmp_path):
    e = bound_env
    process(e)
    args = arguments(e, tmp_path)
    broker_before = e["adapter_store"].path.read_bytes()

    result = run(package, "record", *args)
    report = json.loads(result.stdout)
    assert result.returncode == 0, report
    assert report["persistence_outcome"] == "VERIFIED_COMMITTED_REFUSAL"
    assert report["exact_decision_signature_verified"] is True
    assert report["orders_sent"] is False
    assert report["production_execution_enabled"] is False

    before_inspection = e["store"].path.read_bytes()
    inspected = run(package, "inspect", *args)
    readback = json.loads(inspected.stdout)
    assert inspected.returncode == 0, readback
    assert readback["authenticated_record_count"] == 1
    assert readback["database_modified"] is False
    assert e["store"].path.read_bytes() == before_inspection
    assert e["adapter_store"].path.read_bytes() == broker_before

    with e["adapter_store"].tx() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


def test_modified_package_rejected(package):
    p = package / "existing_application_store.py"
    p.write_text(p.read_text() + "\n# synthetic mutation\n")
    result = run(package, "package-check")
    assert result.returncode == 1
    assert json.loads(result.stdout)["reason"] == "PACKAGE_OR_RUNTIME_HASH_MISMATCH"


def test_missing_runtime_rejected(package, tmp_path):
    result = run(package, "package-check", "--repo", tmp_path / "missing")
    assert result.returncode == 1
    assert json.loads(result.stdout)["reason"] == "REGULAR_PINNED_SOURCE_REQUIRED"


@pytest.mark.parametrize("action", ["submit", "release"])
def test_order_actions_unavailable(package, action):
    result = run(package, action)
    assert result.returncode == 2
    assert "invalid choice" in result.stderr