"""Current installed entry code + isolated synthetic lifecycle rehearsal."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path.cwd().resolve()
folder = root / "hilega-application-lifecycle-rehearsal-tools-v1"
source = "backend/market_lab/hilega_preparation_runtime_v1/source.py"
old = "049b877d43a38bc90621f06e1b28ce0ffb37bc5b7f0e9794d7d66b298ac0222e"
current = "8163ca0db32a5fc95358368d2f474a6f0e083c853cb97008b7574f1241310f71"


def digest(path):
    if (path.is_symlink() or not path.is_file()
            or any(p.is_symlink() for p in path.parents)):
        raise SystemExit("STOP: regular file required: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


manifest = folder / "manifest.json"
manifest_hash = digest(manifest)
if manifest_hash != (
    "c5b89a085109d625bd9fb22760d298897f5b9da52b79c11d033946c54c5b1356"
):
    raise SystemExit("STOP: rehearsal manifest changed")
value = json.loads(manifest.read_text())
if value["installed_source_sha256"].get(source) != old:
    raise SystemExit("STOP: original Source baseline changed")

checked = {}
for section, base in (
    ("package_sha256", folder),
    ("installed_source_sha256", root),
):
    for name, expected in value[section].items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise SystemExit("STOP: invalid manifest path")
        if section == "installed_source_sha256" and name == source:
            expected = current
        path = base / relative
        if digest(path) != expected:
            raise SystemExit("STOP: fingerprint mismatch: " + str(path))
        checked[path] = expected
checked[manifest] = manifest_hash

environment = dict(os.environ)
environment["PYTHONPATH"] = os.pathsep.join(map(str, (
    folder, root / "backend", root / "tests", root,
)))
result = subprocess.run(
    [sys.executable, "-m", "pytest", "-q", str(folder)],
    cwd=root, env=environment, check=False,
)

for path, expected in checked.items():
    if digest(path) != expected:
        raise SystemExit("STOP: verified source changed during rehearsal")

report = {
    "status": "PASS" if result.returncode == 0 else "FAILED_REVIEW_REQUIRED",
    "assessed_at": datetime.now(timezone.utc).isoformat(),
    "pytest_exit_code": result.returncode,
    "scope": "SYNTHETIC_TEMPORARY_DATABASES_ONLY",
    "installed_source_sha256": current,
    "original_rehearsal_manifest_preserved": True,
    "separate_fixture_execution_handoff": True,
    "production_dispatch_integrated": False,
    "services_restarted": False,
    "live_evidence_assessed": False,
    "orders_sent_to_upstox": False,
    "production_execution_enabled": False,
    "reservation_release_permission": False,
    "production_ready": False,
}
output = root / (
    "CURRENT_LIFECYCLE_REHEARSAL-"
    + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
)
output.write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
print("Report:", output)
raise SystemExit(result.returncode)