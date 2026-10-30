from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

root = Path.cwd().resolve()
stage = root / "hilega-observation-supervision-stage-wpltzt_o"
units_dir = Path.home() / ".config/systemd/user"
units = [
    "hilega-observation-analytics.service",
    "hilega-observation-readiness.service",
]


def need(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def run(*args):
    return subprocess.run(args, cwd=root, check=True)


def sha(path):
    need(path.is_file() and not path.is_symlink(),
         "REGULAR_FILE_REQUIRED")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_rows():
    modules = {
        b"market_lab.live_shadow_worker_v1": "analytics",
        b"market_lab.operational_readiness_v1": "readiness",
    }
    rows = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            args = (p / "cmdline").read_bytes().split(b"\0")
            for module, role in modules.items():
                if module in args:
                    need((p / "cwd").resolve() == root,
                         "OBSERVATION_PROCESS_OTHER_REPOSITORY")
                    ticks = (p / "stat").read_text().rsplit(")", 1)[1].split()[19]
                    rows.append(dict(pid=int(p.name), role=role, ticks=ticks))
        except OSError:
            pass
    return rows


def same_process(row):
    p = Path("/proc") / str(row["pid"])
    try:
        return (
            p.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19]
            == row["ticks"]
        )
    except OSError:
        return False


need(stage.is_dir() and not stage.is_symlink(), "STAGE_REQUIRED")
pins = json.loads((stage / "shell-before.json").read_text())
pins["hilega_supervised_control.py"] = (
    stage / "control-before.sha256"
).read_text().strip()

for name, expected in pins.items():
    need(sha(root / "scripts" / name) == expected,
         "INSTALLED_SCRIPT_CHANGED_" + name)
    candidate = stage / name
    sha(candidate)
    if name.endswith(".sh"):
        run("bash", "-n", str(candidate))
    else:
        compile(candidate.read_bytes(), str(candidate), "exec")

units_dir.mkdir(parents=True, exist_ok=True)
for name in units:
    target = units_dir / name
    need(not target.exists() and not target.is_symlink(),
         "OBSERVATION_UNIT_ALREADY_EXISTS")
    sha(stage / name)

run("systemd-analyze", "--user", "verify",
    *[str(stage / name) for name in units])
run(str(root / ".venv/bin/python"), "check-preparation-paused.py")

rows = process_rows()
for role in ("analytics", "readiness"):
    need(sum(r["role"] == role for r in rows) <= 1,
         "DUPLICATE_OBSERVATION_PROCESS")

backup_root = root / "backups"
backup_root.mkdir(exist_ok=True)
backup = Path(tempfile.mkdtemp(
    prefix="hilega-observation-supervision-", dir=backup_root))
for name in pins:
    shutil.copy2(root / "scripts" / name, backup / name)

report = dict(
    backup=str(backup), previous_processes=rows,
    started_at=datetime.now(timezone.utc).isoformat(),
    production_execution_enabled=False,
)


def phase(value):
    report["phase"] = value
    (backup / "deployment.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"phase": value, "backup": str(backup)}), flush=True)


def install(source, target, mode):
    fd, temporary = tempfile.mkstemp(prefix=".install-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(source.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


phase("PREPARED")
try:
    # Stop only the identified observation processes.
    for row in rows:
        need(same_process(row), "OBSERVATION_IDENTITY_CHANGED")
        os.kill(row["pid"], signal.SIGTERM)

    deadline = time.monotonic() + 30
    while any(same_process(r) for r in rows):
        need(time.monotonic() < deadline,
             "OBSERVATION_STOP_TIMEOUT_NO_FORCED_KILL")
        time.sleep(0.2)
    phase("OBSERVATION_PROCESSES_STOPPED")

    for name in pins:
        target = root / "scripts" / name
        need(sha(target) == pins[name], "SCRIPT_CHANGED_BEFORE_INSTALL")
        mode = target.stat().st_mode & 0o777
        install(stage / name, target, mode)

    for name in units:
        install(stage / name, units_dir / name, 0o600)
    phase("FILES_INSTALLED")

    run("systemctl", "--user", "daemon-reload")
    run("systemctl", "--user", "enable", "--now", *units)
    phase("SUPERVISED_OBSERVATION_STARTED")

    run("systemctl", "--user", "show", *units,
        "-p", "Id", "-p", "ActiveState", "-p", "SubState",
        "-p", "MainPID", "-p", "Restart", "-p", "UnitFileState")
    run(str(root / ".venv/bin/python"), "check-preparation-paused.py")
    phase("INSTALLED_PAUSED_CHECK_PASSED")
    print("Fresh heartbeat/report verification still required.")
except BaseException:
    phase("STOPPED_FOR_REVIEW")
    print("Do not rerun installer; retain backup and deployment.json.")
    raise