"""Pinned fixture validation. No operational trading action."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

folder = Path(__file__).resolve().parent
root = Path.cwd().resolve()
manifest = json.loads((folder / "manifest.json").read_text())

def verify():
    for base, entries in (
        (folder, manifest["package_sha256"]),
        (root, manifest["runtime_sha256"]),
    ):
        for name, expected in entries.items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise SystemExit("STOP: invalid pinned path")
            path = base / relative
            if (not path.is_file() or path.is_symlink()
                    or any(p.is_symlink() for p in path.parents)):
                raise SystemExit("STOP: regular pinned file required")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise SystemExit("STOP: source hash mismatch: " + name)

verify()
environment = dict(os.environ)
environment["PYTHONPATH"] = os.pathsep.join(map(str, (
    folder, root / "backend", root / "tests", root,
)))
result = subprocess.run(
    [sys.executable, "-m", "pytest", "-q",
     *[str(folder / name) for name in manifest["test_files"]]],
    cwd=root, env=environment, check=False,
)
verify()
report = dict(
    status="PASS" if result.returncode == 0 else "FAILED_REVIEW_REQUIRED",
    assessed_at=datetime.now(timezone.utc).isoformat(),
    pytest_exit_code=result.returncode,
    scope="SYNTHETIC_TEMPORARY_DATABASES_ONLY",
    fixture_event_flow_packaged=True,
    running_service_hook_installed=False,
    live_transport_integrated=False,
    partial_entry_exit_supported=False,
    live_evidence_assessed=False,
    orders_sent_to_upstox=False,
    production_execution_enabled=False,
    reservation_release_permission=False,
    production_ready=False,
)
output = folder / (
    "VALIDATION-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    + ".json")
output.write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
print("Report:", output)
raise SystemExit(result.returncode)
