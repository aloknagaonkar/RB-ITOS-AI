import hashlib
import json
from pathlib import Path
import shutil
import zipfile

repo = Path.cwd().resolve()
stage = Path.home() / "hilega-atomic-binding-stage-v1"
package = repo / "hilega-atomic-binding-release-v1"
archive = repo / "hilega-atomic-binding-release-v1.zip"

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

# Confirm the currently deployed automatic-candidate baseline.
previous = repo / "hilega-auto-limit-release-v1/manifest.json"
need(
    sha(previous)
    == "13f052acf497ca10ac4b1f3a289f6ede36559b37e273a5143c5a15ebf6773665",
    "previous release manifest changed",
)
baseline_release = json.loads(previous.read_text())
for name in baseline_release["runtime_files"]:
    need(sha(repo / name) == baseline_release["files"][name],
         "deployed runtime changed: " + name)

stage_manifest_path = stage / "ATOMIC_BINDING_STAGE.json"
sha(stage_manifest_path)
staged = json.loads(stage_manifest_path.read_text())
need(
    staged.get("model") == "HILEGA_ATOMIC_DISABLED_BINDING_STAGE_V1"
    and staged.get("production_execution_enabled") is False,
    "unexpected stage identity",
)
for name, expected in staged["files"].items():
    need(sha(stage / name) == expected,
         "validated stage changed: " + name)

reports = sorted(stage.glob("ATOMIC_BINDING_REGRESSION-*.json"))
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
    "passing validation for this stage required",
)

runtime = [
    "backend/market_lab/hilega_execution_port_v1/adapter.py",
    "backend/market_lab/hilega_preparation_runtime_v1/source.py",
    "backend/market_lab/hilega_preparation_runtime_v1/atomic_binding.py",
]
tests = ["tests/test_hilega_atomic_disabled_binding_v1.py"]
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
         "supporting runtime differs from tested stage: " + name)
    dependencies[name] = sha(path)

for name in staged["files"]:
    if name.startswith(("backend/", "tests/")):
        continue
    need(sha(repo / name) == staged["files"][name],
         "supporting dependency changed: " + name)
    dependencies[name] = staged["files"][name]

# All checks precede package creation.
package.mkdir()
for name in payload:
    destination = package / "files" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(stage / name, destination)

shutil.copy2(report_path, package / "validation.json")
shutil.copy2(stage_manifest_path, package / "stage-manifest.json")

manifest = dict(
    model="HILEGA_ATOMIC_DISABLED_BINDING_RELEASE_V1",
    scope="ATOMIC_PREPARATION_HOLD_TO_DISABLED_ADAPTER_REQUEST",
    runtime_files=runtime,
    test_files=tests,
    files={name: sha(package / "files" / name) for name in payload},
    target_baseline=before,
    dependencies=dependencies,
    validation_sha256=sha(package / "validation.json"),
    stage_manifest_sha256=sha(package / "stage-manifest.json"),
    binding_opt_in="HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED",
    binding_mode_default="0",
    binding_activation_included=False,
    route_activation_included=False,
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

print(json.dumps(dict(
    status="ATOMIC_BINDING_RELEASE_PACKAGED_NOT_APPLIED",
    package=str(package),
    archive=str(archive),
    archive_sha256=sha(archive),
    manifest_sha256=sha(manifest_path),
    runtime_files=len(runtime),
    test_files=len(tests),
    binding_activation_included=False,
    applied=False,
    services_restarted=False,
    production_execution_enabled=False,
), indent=2))