cd "$HOME/RB-ITOS-AI" || exit 1
.venv/bin/python -u - <<'PY'
import hashlib
import json
import os
import select
import signal
import sqlite3
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen
from dotenv import dotenv_values

os.umask(0o077)
repo = Path.cwd().resolve()
python = str(repo / ".venv/bin/python")
folder = repo / "backups/hilega-preparation-activation-cvtlkibq"
tool = repo / "hilega-preparation-route-activation/activate.py"
plan = json.loads((folder / "activation-plan.json").read_text())
state_path = folder / "maintenance.json"
startup_path = folder / "original-startup.json"
source_pidfile = repo / "data/runtime/hilega-preparation-source.json"

if (state_path.exists() or startup_path.exists()
        or (folder / "transaction").exists()
        or source_pidfile.exists() or source_pidfile.is_symlink()):
    raise SystemExit("STOP: prior maintenance state exists; review before retry")

def command(action, *extra):
    result = subprocess.run(
        [python, str(tool), action, "--plan", str(folder), *extra],
        cwd=repo, capture_output=True, text=True,
    )
    print(result.stdout, end="", flush=True)
    if result.returncode:
        raise SystemExit("STOP: activation command failed; retain transaction for recovery")
    return json.loads(result.stdout)

def save(path, value):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)

checked = command("check")
if checked["status"] != "PREPARATION_ACTIVATION_CHECKS_PASS":
    raise SystemExit("STOP: unexpected activation check")

# Recheck the complete application-process inventory before signalling.
import sys
sys.path.insert(0, str(repo / "hilega-production-application-deployment"))
from managed_processes import inspect as inventory, require_stopped

current = inventory(repo)["active_processes"]
expected = plan["application_processes"]
if sorted(current, key=lambda r:r["role"]) != sorted(expected, key=lambda r:r["role"]):
    raise SystemExit("STOP: process inventory changed since plan")

launch = {}
handles = []
state = {"phase": "PREFLIGHT", "children": {}, "production_execution_enabled": False}
try:
    for row in expected:
        proc = Path("/proc") / str(row["pid"])
        fd = os.pidfd_open(row["pid"])
        handles.append(fd)
        args = [x.decode() for x in proc.joinpath("cmdline").read_bytes().split(b"\0") if x]
        ticks = int(proc.joinpath("stat").read_text().rsplit(")",1)[1].split()[19])
        if (args[1:] != ["-m", "market_lab.runtime", row["role"]]
                or proc.joinpath("cwd").resolve() != repo
                or ticks != row["start_ticks"]):
            raise SystemExit("STOP: process identity or launcher changed")
        startup = dict(
            item.decode().split("=",1)
            for item in proc.joinpath("environ").read_bytes().split(b"\0")
            if b"=" in item
        )
        logs = []
        for number in (1,2):
            path = proc.joinpath("fd",str(number)).readlink()
            if (not path.is_absolute() or not path.is_file() or path.is_symlink()
                    or not path.resolve().is_relative_to((repo/"data/logs").resolve())):
                raise SystemExit("STOP: application log destination changed")
            logs.append(str(path))
        launch[row["role"]] = {"env": startup, "logs": logs}

    config = dotenv_values(repo/".env")
    api_env = launch["api"]["env"]
    def setting(name):
        return api_env.get(name, config.get(name) or "")
    token_file = setting("HILEGA_PRODUCTION_CONTROL_TOKEN_FILE")
    if token_file:
        path = Path(token_file)
        token = (path if path.is_absolute() else repo/path).read_text().strip()
    else:
        token = setting("HILEGA_PRODUCTION_CONTROL_TOKEN")
    if len(token) < 32:
        raise SystemExit("STOP: API authentication unavailable")

    # Private recovery material; never print or commit this file.
    save(startup_path, launch)
    save(state_path, state)
    for fd in handles:
        signal.pidfd_send_signal(fd, signal.SIGTERM)
    pending = set(handles)
    deadline = time.monotonic()+30
    while pending:
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise SystemExit("STOP: application processes have not both exited")
        exited,_,_ = select.select(list(pending),[],[],remaining)
        pending.difference_update(exited)
finally:
    for fd in handles:
        os.close(fd)

require_stopped(repo)
state["phase"] = "APPLICATION_STOPPED"
save(state_path,state)

activated = command(
    "apply", "--services-stopped",
    "--confirmation", "ENROLL_PREPARATION_ONLY",
)
if activated["status"] != "ENROLLED_SERVICES_STILL_STOPPED":
    raise SystemExit("STOP: unexpected enrollment result")
state["phase"] = "ENROLLED_SERVICES_STOPPED"
save(state_path,state)

if hashlib.sha256((repo/".env").read_bytes()).hexdigest() != plan["candidate_env_sha256"]:
    raise SystemExit("STOP: active configuration does not match candidate")

children = {}
for role in ("worker","api"):
    startup = dict(launch[role]["env"])
    startup.update(plan["planned_configuration_changes"])
    startup["PYTHONPATH"] = str(repo/"backend")+os.pathsep+startup.get("PYTHONPATH","")
    out_path, err_path = map(Path,launch[role]["logs"])
    with out_path.open("ab",buffering=0) as out, err_path.open("ab",buffering=0) as err:
        children[role] = subprocess.Popen(
            [python,"-m","market_lab.runtime",role],
            cwd=repo,env=startup,stdin=subprocess.DEVNULL,
            stdout=out,stderr=err,start_new_session=True,
        )
    state["children"][role] = children[role].pid
    save(state_path,state)

# Dedicated preparation-only watcher; no synthetic cash/fill arguments.
source_env = dict(launch["api"]["env"])
source_env.update(plan["planned_configuration_changes"])
source_env["PYTHONPATH"] = str(repo/"backend")+os.pathsep+source_env.get("PYTHONPATH","")
with (repo/"data/logs/hilega-preparation-source.log").open("ab",buffering=0) as log:
    children["source"] = subprocess.Popen(
        [python,"-u",str(repo/"scripts/hilega_production_simulator_bridge.py"),
         "--watch","--env-file",str(repo/".env"),
         "--source",str(repo/"data/live-observation/hilega-directional-v1/step-audit.jsonl")],
        cwd=repo,env=source_env,stdin=subprocess.DEVNULL,
        stdout=log,stderr=log,start_new_session=True,
    )
state["children"]["source"] = children["source"].pid
state["phase"] = "PROCESSES_STARTED_PENDING_VERIFICATION"
save(state_path,state)

def api(path):
    request = Request(
        "http://127.0.0.1:8123"+path,
        headers={"Authorization":"Bearer "+token},
    )
    with urlopen(request,timeout=2) as response:
        return json.load(response)

database = Path(plan["database"])
summary = pricing = health = bridge_health = None
deadline = time.monotonic()+45
while time.monotonic() < deadline:
    if any(child.poll() is not None for child in children.values()):
        raise SystemExit("STOP: a process exited; inspect existing logs and maintenance.json")
    try:
        with urlopen("http://127.0.0.1:8123/api/health",timeout=2) as response:
            health = json.load(response)
        summary = api("/api/hilega-production/execution-preparation")
        pricing = api("/api/hilega-production/execution-preparation/pricing")
        db = sqlite3.connect(database.resolve().as_uri()+"?mode=ro",uri=True,timeout=2)
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            control = json.loads(db.execute("SELECT data FROM control WHERE id=1").fetchone()[0])
            row = db.execute("SELECT data FROM sim_bridge_health WHERE id=1").fetchone()
            bridge_health = json.loads(row[0]) if row else {}
            counts = {
                name: db.execute("SELECT COUNT(*) FROM "+name).fetchone()[0]
                for name in (
                    "intents","sim_orders","sim_fills","sim_allocation_reservations",
                    "preparation_plans","preparation_shadow_holds","preparation_outbox",
                )
            }
        finally:
            db.close()
        if (health.get("status")=="ok" and health.get("execution")=="not_enabled"
                and summary.get("route")=="PREPARATION_ONLY"
                and summary.get("submission_gate")=="CLOSED_IN_CODE"
                and summary.get("production_execution_enabled") is False
                and pricing.get("production_ready") is False
                and control["mode"]=="PAUSED" and not any(counts.values())
                and bridge_health.get("pid")==children["source"].pid
                and bridge_health.get("phase")=="RUNNING"):
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit("STOP: activation verification incomplete; retain state and do not resume")

source_pid = children["source"].pid
source_ticks = int(
    Path(f"/proc/{source_pid}/stat").read_text().rsplit(")",1)[1].split()[19]
)
with source_pidfile.open("x") as stream:
    json.dump(dict(pid=source_pid,start_ticks=source_ticks,root=str(repo),
                   role="production-source-worker"),stream,indent=2)

state["phase"] = "PREPARATION_ONLY_ACTIVE_PAUSED"
save(state_path,state)
print(json.dumps({
    "status": state["phase"],
    "processes": state["children"],
    "health": health,
    "execution_route": summary["route"],
    "submission_gate": summary["submission_gate"],
    "controller_mode": control["mode"],
    "activity_counts": counts,
    "source_worker_phase": bridge_health["phase"],
    "fresh_signal_admission_verified": False,
    "recovery_transaction": activated["transaction"],
    "production_execution_enabled": False,
},indent=2))
PY