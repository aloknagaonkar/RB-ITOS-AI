"""Preflight CLI tests; temporary package copies, no application DB access."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path.cwd().resolve()
PACKAGE = ROOT / "hilega-refusal-persistence-stage-k2aygu9h"
EXPECTED = "4e12f7894aa7cc7818e6c8ba11388119553867a63296a5bf426ef82b114f65f2"


@pytest.fixture
def package(tmp_path):
    manifest = PACKAGE / "manifest.json"
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == EXPECTED
    copied = tmp_path / "package"
    shutil.copytree(PACKAGE, copied)
    return copied


def run(package, action="package-check", repo=ROOT):
    return subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(package / "cli.py"),
         action, "--repo", str(repo)],
        cwd=ROOT, capture_output=True, text=True,
    )


def test_package_check_without_database_access(package):
    result = run(package)
    report = json.loads(result.stdout)
    assert result.returncode == 0
    assert report["status"] == "REFUSAL_PACKAGE_CHECK_PASS"
    assert report["application_database_accessed"] is False
    assert report["database_modified"] is False


def test_candidate_tampering_rejected(package):
    path = package / "production_closed_decisions.py"
    path.write_text(path.read_text() + "\n# synthetic mutation\n")
    result = run(package)
    report = json.loads(result.stdout)
    assert result.returncode == 1
    assert report["reason"] == "PACKAGE_OR_RUNTIME_HASH_MISMATCH"
    assert report["database_modified"] is False


def test_missing_runtime_rejected(package, tmp_path):
    result = run(package, repo=tmp_path / "missing")
    report = json.loads(result.stdout)
    assert result.returncode == 1
    assert report["reason"] == "REGULAR_PINNED_SOURCE_REQUIRED"


def test_invalid_manifest_message_sanitized(package):
    (package / "manifest.json").write_text("SYNTHETIC_PRIVATE_TEXT")
    result = run(package)
    report = json.loads(result.stdout)
    assert result.returncode == 1
    assert report["reason"] == "SOURCE_OR_PACKAGE_REVIEW_REQUIRED"
    assert "SYNTHETIC_PRIVATE_TEXT" not in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize("action", ["record", "submit", "release"])
def test_write_actions_unavailable(package, action):
    result = run(package, action=action)
    assert result.returncode == 2
    assert "invalid choice" in result.stderr