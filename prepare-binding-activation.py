import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from dotenv import dotenv_values, set_key

os.umask(0o077)
repo = Path.cwd().resolve()
key = "HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED"
package = repo / "hilega-atomic-binding-release-v1"
release_pin = "ea563125ccf1bb8dbb02c26679cb7b254702a185679c8260a78529e6d2bde436"
tool_path = repo / "hilega-atomic-binding-deployment/deploy.py"

def need(value, reason):
    if not value:
        raise SystemExit("STOP: " + reason)

def sha(path):
    need(path.is_file() and not path.is_symlink(),
         "regular file required: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()

need(sha(package / "manifest.json") == release_pin,
     "release manifest changed")

spec = importlib.util.spec_from_file_location(
    "binding_activation_preflight", tool_path,
)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
need(tool.check()["status"] == "ATOMIC_BINDING_ALREADY_APPLIED",
     "verified deployed atomic-binding release required")

result = subprocess.run(
    [sys.executable, "check-preparation-paused.py"],
    cwd=repo, capture_output=True, text=True,
    env={**os.environ, "PYTHONPATH": "backend:."},
)
need(result.returncode == 0, "paused-state check failed; run it directly")
state = json.loads(result.stdout)
need(
    state["process_identities_match"] is True
    and state["controller_mode"] == "PAUSED"
    and state["execution_route"] == "PREPARATION_ONLY"
    and not any(state["activity_counts"].values())
    and state["journal_prefix_matches"] is True
    and state["journal_tail_remaining_records"] == 0,
    "application state requires review",
)

env_path = repo / ".env"
env_hash = sha(env_path)
config = dotenv_values(env_path)
need(config.get(key, "0") == "0", "binding mode is not off")

rows = tool.managed.inspect(repo)["active_processes"]
need(len(rows) == 3 and {row["role"] for row in rows} == {
    "api", "worker", "production-source-worker",
}, "expected exactly three application processes")

previous_path = (
    repo / "backups/hilega-atomic-binding-maintenance-dr3gn23_"
    / "startup-private.json"
)
previous = json.loads(previous_path.read_text())

def ticks(proc):
    return int(proc.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19])

startup = {}
for row in rows:
    role = row["role"]
    proc = Path("/proc") / str(row["pid"])
    need(ticks(proc) == row["start_ticks"], "process identity changed")
    args = [
        value.decode()
        for value in proc.joinpath("cmdline").read_bytes().split(b"\0")
        if value
    ]
    need(args == previous[role]["argv"]
         and proc.joinpath("cwd").resolve() == repo,
         "process launcher or directory changed")
    environment = dict(
        item.decode().split("=", 1)
        for item in proc.joinpath("environ").read_bytes().split(b"\0")
        if b"=" in item
    )
    need(environment.get(key, "0") == "0"
         and environment.get("HILEGA_PRODUCTION_EXECUTION_ROUTE")
             == "PREPARATION_ONLY",
         "unexpected process configuration")
    logs = []
    for number in (1, 2):
        path = proc.joinpath("fd", str(number)).readlink()
        need(path.is_absolute()
             and path.resolve().is_relative_to((repo / "data/logs").resolve()),
             "unexpected log destination")
        tool.guard.target(repo, str(path.relative_to(repo)))
        sha(path)
        logs.append(str(path))
    need(ticks(proc) == row["start_ticks"], "process changed during capture")
    startup[role] = dict(
        argv=args, env=environment, logs=logs,
        pid=row["pid"], start_ticks=row["start_ticks"],
    )

need(sha(env_path) == env_hash, "environment changed during preparation")
need(tool.managed.inspect(repo)["active_processes"] == rows,
     "process inventory changed")

backup = Path(tempfile.mkdtemp(
    prefix="hilega-binding-activation-", dir=repo / "backups",
))
shutil.copyfile(env_path, backup / "original.env")
candidate = backup / "candidate.env"
shutil.copyfile(env_path, candidate)
set_key(str(candidate), key, "1", quote_mode="always")
candidate_config = dotenv_values(candidate)
changed = {
    name for name in set(config) | set(candidate_config)
    if config.get(name) != candidate_config.get(name)
}
need(changed == {key} and candidate_config[key] == "1",
     "candidate changed settings beyond the binding flag")

with (backup / "startup-private.json").open("x") as stream:
    json.dump(startup, stream, indent=2)

metadata = [
    "data/runtime/api.json",
    "data/runtime/worker.json",
    "data/runtime/hilega-preparation-source.json",
    "backups/hilega-preparation-activation-cvtlkibq/maintenance.json",
]
for name in metadata:
    source = repo / name
    expected = sha(source)
    destination = backup / "original-metadata" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    need(sha(destination) == expected, "metadata backup mismatch")

release = json.loads((package / "manifest.json").read_text())
plan = dict(
    model="HILEGA_LOCAL_BINDING_ACTIVATION_PLAN_V1",
    status="BINDING_ACTIVATION_PREPARED_NOT_APPLIED",
    root=str(repo), backup=str(backup), package=str(package),
    release_manifest_sha256=release_pin,
    database=str(repo / "data/research/hilega-production-workspace/sim.sqlite"),
    original_env_sha256=env_hash,
    candidate_env_sha256=sha(candidate),
    startup_sha256=sha(backup / "startup-private.json"),
    code_files=release["files"],
    dependencies=release["dependencies"],
    processes=rows,
    metadata_paths=metadata,
    planned_configuration_changes={key: "1"},
    controller_must_remain="PAUSED",
    execution_route_must_remain="PREPARATION_ONLY",
    guard_files={
        name: sha(repo / name) for name in (
            "check-preparation-paused.py",
            "hilega-production-application-deployment/managed_processes.py",
            "hilega-production-application-deployment/deploy.py",
            "scripts/hilega_production_simulator_bridge.py",
        )
    },
    applied=False,
    services_restarted=False,
    production_execution_enabled=False,
)
plan_path = backup / "activation-plan.json"
with plan_path.open("x") as stream:
    json.dump(plan, stream, indent=2)

print(json.dumps({
    "status": plan["status"],
    "backup": str(backup),
    "plan_sha256": sha(plan_path),
    "processes": rows,
    "planned_configuration_changes": plan["planned_configuration_changes"],
    "controller_mode": "PAUSED",
    "execution_route": "PREPARATION_ONLY",
    "running_configuration_changed": False,
    "services_restarted": False,
    "production_execution_enabled": False,
}, indent=2))