
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

PACKAGE = Path('/home/aloknagaonkar46/RB-ITOS-AI/hilega-operational-lifecycle-tools-6cexrur_')
REPO = Path('/home/aloknagaonkar46/RB-ITOS-AI')


def run(folder, *args):
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, str(folder / "cli.py"), *args],
        cwd=folder, env=environment,
        text=True, capture_output=True, check=False,
    )


def copied(tmp_path):
    target = tmp_path / "package"
    shutil.copytree(PACKAGE, target)
    return target


def test_check_without_database_or_credential_arguments():
    result = run(PACKAGE, "check", "--repo", str(REPO))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["database_access_performed"] is False
    assert report["credentials_opened"] is False
    assert report["order_actions_available"] is False


def test_modified_module_rejected(tmp_path):
    folder = copied(tmp_path)
    with (folder / "operational_lifecycle_review.py").open("a") as stream:
        stream.write("\n# changed\n")
    result = run(folder, "check", "--repo", str(REPO))
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "PACKAGE_OR_RUNTIME_CHECK_FAILED"


def test_modified_manifest_rejected(tmp_path):
    folder = copied(tmp_path)
    (folder / "manifest.json").write_text('{"bad":"SYNTHETIC-PRIVATE-TEXT"}')
    result = run(folder, "check", "--repo", str(REPO))
    assert result.returncode == 2
    assert "SYNTHETIC-PRIVATE-TEXT" not in result.stdout


def test_missing_runtime_rejected(tmp_path):
    empty = tmp_path / "empty-repo"
    empty.mkdir()
    result = run(PACKAGE, "check", "--repo", str(empty))
    assert result.returncode == 2


@pytest.mark.parametrize("action", ["submit", "cancel", "release"])
def test_order_actions_unavailable(action):
    result = run(PACKAGE, action, "--repo", str(REPO))
    assert result.returncode == 2


def test_review_requires_explicit_paths():
    result = run(PACKAGE, "review", "--repo", str(REPO))
    assert result.returncode == 2
    assert "requires explicit" in result.stderr
