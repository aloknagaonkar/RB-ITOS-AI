import hashlib
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
from urllib.request import Request, urlopen

from dotenv import dotenv_values

os.umask(0o077)
repo = Path.cwd().resolve()
backup = repo / "backups/hilega-auto-limit-maintenance-_mzrnlv9"
plan_path = backup / "plan.json"
state_path = backup / "rollout.json"
tool_path = repo / "hilega-auto-limit-deployment/deploy.py"
python = str(repo / ".venv/bin/python")
pin = "5d352e4ec40848793a8497f301a6c06ea20642052859fd941a256bbf3387d227"

def need(value, reason):
    if not value:
        raise RuntimeError(reason)

def sha(path):
    need(path.is_file() and not path.is_symlink(),
         "REGULAR_FILE_REQUIRED: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()

need(sha(plan_path) == pin, "MAINTENANCE_PLAN_CHANGED")
plan = json.loads(plan_path.read_text())
need(plan["root"] == str(repo) and plan["backup"] == str(backup),
     "MAINTENANCE_ROOT_MISMATCH")
need(not state_path.exists() and not state_path.is_symlink(),
     "ROLLOUT_STATE_EXISTS_REVIEW_BEFORE_RETRY")
need(sha(backup / "startup-private.json") == plan["startup_sha256"],
     "PRIVATE_STARTUP_RECORD_CHANGED")
startup = json.loads((backup / "startup-private.json").read_text())
tool_hash = sha(tool_path)

spec = importlib.util.spec_from_file_location("auto_limit_maintenance_tool", tool_path)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

def save(value):
    tool.guard.atomic_bytes(
        state_path, json.dumps(value, indent=2).encode(), 0o600,
    )

def unchanged():
    need(sha(tool_path) == tool_hash, "DEPLOYMENT_TOOL_CHANGED")
    need(sha(repo / ".env") == plan["env_sha256"], "ENVIRONMENT_CHANGED")

def inventory():
    return tool.managed.inspect(repo)["active_processes"]

def normalized(rows):
    return sorted(rows, key=lambda row: row["role"])

def process_ticks(pid):
    return int(
        Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    )

def api(path, token=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    request = Request("http://127.0.0.1:8123" + path, headers=headers)
    with urlopen(request, timeout=2) as response:
        return json.load(response)

def paused_check():
    result = subprocess.run(
        [python, "check-preparation-paused.py"],
        cwd=repo, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": "backend:."},
    )
    need(result.returncode == 0, "PAUSED_STATE_CHECK_FAILED")
    value = json.loads(result.stdout)
    need(value["process_identities_match"] is True
         and value["controller_mode"] == "PAUSED"
         and value["execution_route"] == "PREPARATION_ONLY"
         and not any(value["activity_counts"].values())
         and value["journal_prefix_matches"] is True
         and value["journal_tail_remaining_records"] == 0,
         "APPLICATION_STATE_REQUIRES_REVIEW")
    return value

unchanged()
need(tool.check()["status"] == "AUTO_LIMIT_CODE_CHECKS_PASS",
     "DEPLOYMENT_CHECK_FAILED")
paused_check()
expected = plan["processes"]
need(normalized(inventory()) == normalized(expected),
     "PROCESS_INVENTORY_CHANGED")

# Verify that preparation-era metadata has not changed since recovery preparation.
for name in plan["metadata_paths"]:
    original = backup / "original-metadata" / name
    need(sha(repo / name) == sha(original), "PROCESS_METADATA_CHANGED: " + name)

config = dotenv_values(repo / ".env")
api_env = startup["api"]["env"]

def setting(name):
    return api_env.get(name, config.get(name) or "")

token_file = setting("HILEGA_PRODUCTION_CONTROL_TOKEN_FILE")
if token_file:
    path = Path(token_file)
    token = (path if path.is_absolute() else repo / path).read_text().strip()
else:
    token = setting("HILEGA_PRODUCTION_CONTROL_TOKEN")
need(isinstance(token, str) and len(token) >= 32,
     "API_AUTHENTICATION_UNAVAILABLE")
summary = api("/api/hilega-production/execution-preparation", token)
need(summary.get("route") == "PREPARATION_ONLY"
     and summary.get("submission_gate") == "CLOSED_IN_CODE"
     and summary.get("production_execution_enabled") is False,
     "AUTHENTICATED_PREPARATION_STATE_MISMATCH")

handles = []
children = {}
state = dict(
    phase="PREFLIGHT_COMPLETE", original_processes=expected, children={},
    tool_sha256=tool_hash, production_execution_enabled=False,
)
try:
    # Open and verify every process handle before signalling any process.
    for row in expected:
        role, pid = row["role"], row["pid"]
        fd = os.pidfd_open(pid)
        handles.append((role, fd))
        proc = Path("/proc") / str(pid)
        args = [
            item.decode()
            for item in proc.joinpath("cmdline").read_bytes().split(b"\0")
            if item
        ]
        need(
            process_ticks(pid) == row["start_ticks"]
            and startup[role]["pid"] == pid
            and startup[role]["start_ticks"] == row["start_ticks"]
            and args == startup[role]["argv"]
            and proc.joinpath("cwd").resolve() == repo,
            "PROCESS_IDENTITY_CHANGED: " + role,
        )
        for name in startup[role]["logs"]:
            path = Path(name)
            need(path.is_absolute()
                 and path.resolve().is_relative_to((repo / "data/logs").resolve()),
                 "UNEXPECTED_LOG_DESTINATION")
            relative = str(path.relative_to(repo))
            tool.guard.target(repo, relative)
            sha(path)

    unchanged()
    need(normalized(inventory()) == normalized(expected),
         "PROCESS_INVENTORY_CHANGED_BEFORE_STOP")
    state["phase"] = "STOPPING_APPLICATION"
    save(state)

    order = {"production-source-worker": 0, "worker": 1, "api": 2}
    for role, fd in sorted(handles, key=lambda item: order[item[0]]):
        signal.pidfd_send_signal(fd, signal.SIGTERM)

    pending = {fd for _, fd in handles}
    deadline = time.monotonic() + 30
    while pending:
        remaining = deadline - time.monotonic()
        need(remaining > 0, "PROCESS_EXIT_TIMEOUT_NO_FORCE_KILL")
        exited, _, _ = select.select(list(pending), [], [], remaining)
        pending.difference_update(exited)

    tool.stopped()
    unchanged()
    state["phase"] = "APPLICATION_STOPPED"
    save(state)

    applied = tool.apply()
    state["phase"] = "CODE_APPLIED_SERVICES_STOPPED"
    state["code_transaction"] = applied["transaction"]
    save(state)
    print(json.dumps(applied, indent=2), flush=True)

    def launch(role):
        item = startup[role]
        unchanged()
        with Path(item["logs"][0]).open("ab", buffering=0) as out, \
             Path(item["logs"][1]).open("ab", buffering=0) as err:
            child = subprocess.Popen(
                item["argv"], cwd=repo, env=item["env"],
                stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                start_new_session=True,
            )
        children[role] = child
        state["children"][role] = dict(
            pid=child.pid, start_ticks=process_ticks(child.pid),
        )
        save(state)

    state["phase"] = "STARTING_APPLICATION"
    save(state)
    for role in ("worker", "api", "production-source-worker"):
        launch(role)

    # Preserve enrollment metadata, replacing only the managed child IDs.
    source_pid = children["production-source-worker"].pid
    source_ticks = state["children"]["production-source-worker"]["start_ticks"]
    source_record = repo / "data/runtime/hilega-preparation-source.json"
    tool.guard.atomic_bytes(source_record, json.dumps(dict(
        pid=source_pid, start_ticks=source_ticks, root=str(repo),
        role="production-source-worker",
    ), indent=2).encode(), 0o600)

    maintenance_path = (
        repo / "backups/hilega-preparation-activation-cvtlkibq/maintenance.json"
    )
    previous = json.loads(maintenance_path.read_text())
    previous["children"] = {
        "worker": children["worker"].pid,
        "api": children["api"].pid,
        "source": source_pid,
    }
    previous["phase"] = "PREPARATION_ONLY_ACTIVE_PAUSED"
    tool.guard.atomic_bytes(
        maintenance_path, json.dumps(previous, indent=2).encode(), 0o600,
    )
    state["phase"] = "STARTED_PENDING_VERIFICATION"
    save(state)

    deadline = time.monotonic() + 45
    verified = health = None
    while time.monotonic() < deadline:
        need(all(child.poll() is None for child in children.values()),
             "RESTARTED_PROCESS_EXITED_INSPECT_LOGS")
        try:
            health = api("/api/health")
            summary = api("/api/hilega-production/execution-preparation", token)
            pricing = api(
                "/api/hilega-production/execution-preparation/pricing", token,
            )
            verified = paused_check()
            current = inventory()
            wanted = [
                dict(role=role, **identity)
                for role, identity in state["children"].items()
            ]
            if (
                normalized(current) == normalized(wanted)
                and health.get("status") == "ok"
                and health.get("execution") == "not_enabled"
                and summary.get("route") == "PREPARATION_ONLY"
                and summary.get("submission_gate") == "CLOSED_IN_CODE"
                and summary.get("production_execution_enabled") is False
                and pricing.get("production_ready") is False
            ):
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        raise RuntimeError("POST_DEPLOYMENT_VERIFICATION_INCOMPLETE")

    unchanged()
    need(tool.check()["status"] == "AUTO_LIMIT_ALREADY_APPLIED",
         "DEPLOYED_FILES_DO_NOT_MATCH_RELEASE")
    state["phase"] = "AUTO_LIMIT_CODE_DEPLOYED_PAUSED_VERIFIED"
    save(state)
    print(json.dumps(dict(
        status=state["phase"],
        backup=str(backup),
        code_transaction=state["code_transaction"],
        processes=state["children"],
        health=health,
        execution_route="PREPARATION_ONLY",
        controller_mode="PAUSED",
        activity_counts=verified["activity_counts"],
        bridge_health=verified["bridge_health"],
        automatic_candidate_code_deployed=True,
        fresh_signal_admission_verified=False,
        configuration_changed=False,
        production_execution_enabled=False,
    ), indent=2))
except BaseException as exc:
    if state_path.exists():
        state["failure_after_phase"] = state["phase"]
        state["phase"] = "REQUIRES_REVIEW_NO_AUTOMATIC_RETRY"
        state["error_type"] = type(exc).__name__
        save(state)
    print(json.dumps(dict(
        status="STOPPED_FOR_REVIEW",
        reason=str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__,
        recovery_state=str(state_path),
        automatic_retry=False,
        production_execution_enabled=False,
    ), indent=2))
    raise SystemExit(1)
finally:
    for _, fd in handles:
        os.close(fd)