"""CLI integrity tests. No application DB or broker access."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path.cwd().resolve()
PACKAGE = ROOT / "hilega-closed-dispatch-tools-sy4gki37"
EXPECTED = "87291370fa2fc67e99a1bd8b9d9e07de17453a9ccb44e7ca019308bf1913bd38"


@pytest.fixture
def package(tmp_path):
    manifest = PACKAGE / "manifest.json"
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == EXPECTED
    target = tmp_path / "package"
    shutil.copytree(PACKAGE, target)
    return target


def run(package, repo=ROOT):
    result = subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(package / "cli.py"),
         "package-check", "--repo", str(repo)],
        cwd=ROOT, capture_output=True, text=True,
    )
    return result, json.loads(result.stdout)


def assert_blocked(result, report):
    assert result.returncode == 1
    assert report["status"] == "CLOSED_DISPATCH_CLI_STOPPED_FOR_REVIEW"
    for flag in (
        "database_modified", "broker_reads_performed", "entry_permission",
        "orders_sent", "production_execution_enabled",
        "reservation_release_permission", "production_ready",
    ):
        assert report[flag] is False
    assert result.stderr == ""


def test_package_check_succeeds_without_database_access(package):
    result, report = run(package)
    assert result.returncode == 0
    assert report["status"] == "CLOSED_DISPATCH_PACKAGE_CHECK_PASS"
    assert report["application_database_accessed"] is False
    assert report["broker_reads_performed"] is False


def test_modified_module_rejected(package):
    path = package / "closed_entry_dispatch.py"
    path.write_text(path.read_text() + "\n# synthetic mutation\n")
    result, report = run(package)
    assert_blocked(result, report)
    assert report["reason"] == "PACKAGE_OR_RUNTIME_HASH_MISMATCH"


def test_missing_runtime_rejected(package, tmp_path):
    result, report = run(package, repo=tmp_path / "missing-repo")
    assert_blocked(result, report)
    assert report["reason"] == "REGULAR_PINNED_FILE_REQUIRED"


def test_invalid_manifest_sanitized(package):
    (package / "manifest.json").write_text("SYNTHETIC_PRIVATE_TEXT")
    result, report = run(package)
    assert_blocked(result, report)
    assert "SYNTHETIC_PRIVATE_TEXT" not in result.stdout


def test_manifest_parent_traversal_rejected(package):
    path = package / "manifest.json"
    value = json.loads(path.read_text())
    value["package_sha256"] = {"../outside.py": "0" * 64}
    path.write_text(json.dumps(value))
    result, report = run(package)
    assert_blocked(result, report)
    assert report["reason"] == "MANIFEST_PATH_INVALID"