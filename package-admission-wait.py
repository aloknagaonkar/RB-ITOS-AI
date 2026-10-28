import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from dotenv import dotenv_values

repo = Path.cwd().resolve()
stage = Path.home() / "hilega-admission-wait-stage-v1"
package = repo / "hilega-admission-wait-release-v1"
archive = repo / "hilega-admission-wait-release-v1.zip"

def need(value, reason):
    if not value:
        raise SystemExit("STOP: " + reason)

def sha(path):
    need(path.is_file() and not path.is_symlink(),
         "regular file required: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()

need(
    not package.exists() and not package.is_symlink()
    and not archive.exists() and not archive.is_symlink(),
    "fresh package and archive paths required",
)

previous = repo / "hilega-atomic-binding-release-v1/manifest.json"
need(
    sha(previous)
    == "ea563125ccf1bb8dbb02c26679cb7b254702a185679c8260a78529e6d2bde436",
    "previous release manifest changed",
)
previous_release = json.loads(previous.read_text())
for name in previous_release["runtime_files"]:
    need(sha(repo / name) == previous_release["files"][name],
         "deployed runtime changed: " + name)

required_config = {
    "HILEGA_PRODUCTION_EXECUTION_ROUTE": "PREPARATION_ONLY",
    "HILEGA_PRODUCTION_WORKSPACE_MODE": "SIMULATION_ONLY",
    "HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED": "1",
}
sha(repo / ".env")
config = dotenv_values(repo / ".env")
need(all(config.get(key) == value for key, value in required_config.items()),
     "configuration differs from the expected enabled-binding baseline")

stage_manifest_path = stage / "ADMISSION_WAIT_STAGE.json"
sha(stage_manifest_path)
staged = json.loads(stage_manifest_path.read_text())
need(
    staged.get("model") == "HILEGA_PREPARATION_WAIT_ADMISSION_STAGE_V1",
    "unexpected stage identity",
)
for name, expected in staged["files"].items():
    need(sha(stage / name) == expected,
         "validated staged file changed: " + name)

reports = sorted(stage.glob("ADMISSION_WAIT_REGRESSION-*.json"))
need(bool(reports), "validation report missing")
report_path = reports[-1]
sha(report_path)
report = json.loads(report_path.read_text())
need(
    report.get("status") == "PASS"
    and report.get("pytest_exit_code") == 0
    and report.get("stage") == str(stage)
    and report.get("applied") is False
    and report.get("services_restarted") is False
    and report.get("production_execution_enabled") is False,
    "latest validation must pass for this exact stage",
)

runtime = [
    "backend/market_lab/hilega_preparation_runtime_v1/source.py",
]
tests = ["tests/test_hilega_preparation_wait_admission_v1.py"]
payload = runtime + tests

before = {}
for name in payload:
    path = repo / name
    need(not path.is_symlink(), "target symlink: " + name)
    before[name] = sha(path) if path.exists() else None
    compile((stage / name).read_text(), name, "exec")

dependencies = {}
for path in sorted((stage / "backend/market_lab").rglob("*")):
    if path.suffix not in {".py", ".json"}:
        continue
    name = str(path.relative_to(stage))
    if name in runtime:
        continue
    need(sha(repo / name) == sha(path),
         "supporting runtime differs from validated stage: " + name)
    dependencies[name] = sha(path)

for name in staged["files"]:
    if name.startswith(("backend/", "tests/")):
        continue
    need(sha(repo / name) == staged["files"][name],
         "supporting dependency changed: " + name)
    dependencies[name] = staged["files"][name]

package.mkdir()
for name in payload:
    destination = package / "files" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(stage / name, destination)

shutil.copy2(report_path, package / "validation.json")
shutil.copy2(stage_manifest_path, package / "stage-manifest.json")

manifest = dict(
    model="HILEGA_PREPARATION_WAIT_ADMISSION_RELEASE_V1",
    scope="PREPARATION_LOCAL_BASELINE_REFRESH_ONLY",
    runtime_files=runtime,
    test_files=tests,
    files={name: sha(package / "files" / name) for name in payload},
    target_baseline=before,
    dependencies=dependencies,
    required_configuration=required_config,
    validation_sha256=sha(package / "validation.json"),
    stage_manifest_sha256=sha(package / "stage-manifest.json"),
    configuration_change_included=False,
    route_activation_included=False,
    controller_arming_included=False,
    applied=False,
    services_restarted=False,
    production_execution_enabled=False,
)
manifest_path = package / "manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2))

with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as output:
    for path in sorted(package.rglob("*")):
        if path.is_file():
            output.write(path, path.relative_to(repo))

print(json.dumps({
    "status": "ADMISSION_WAIT_RELEASE_PACKAGED_NOT_APPLIED",
    "package": str(package),
    "archive": str(archive),
    "archive_sha256": sha(archive),
    "manifest_sha256": sha(manifest_path),
    "runtime_files": len(runtime),
    "test_files": len(tests),
    "required_binding_mode": "1",
    "configuration_change_included": False,
    "controller_arming_included": False,
    "applied": False,
    "production_execution_enabled": False,
}, indent=2))