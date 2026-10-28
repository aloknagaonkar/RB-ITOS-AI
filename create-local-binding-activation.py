import ast
import hashlib
from pathlib import Path

repo = Path.cwd().resolve()
folder = repo / "hilega-local-binding-activation"
base = repo / "hilega-atomic-binding-deployment/deploy.py"

if folder.exists() or folder.is_symlink():
    raise SystemExit("STOP: activation-tool directory already exists")
if not base.is_file() or base.is_symlink():
    raise SystemExit("STOP: regular deployment helper required")

base_text = base.read_text()
functions = {
    node.name: node
    for node in ast.parse(base_text).body
    if isinstance(node, ast.FunctionDef)
}
if "workspace" not in functions:
    raise SystemExit("STOP: workspace guard missing")
workspace_code = ast.get_source_segment(base_text, functions["workspace"])

tool = r'''"""Local binding flag only. No process control, code apply or database restore."""
import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
KEY = "HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED"
PLAN_REL = "backups/hilega-binding-activation-5vaxo1ah/activation-plan.json"
PIN_PLAN = "44bef25e2036ffa0aa104f5f5d2f74a7d93b14245efc1d998eb7728faaa5b05d"
PIN_RELEASE = "ea563125ccf1bb8dbb02c26679cb7b254702a185679c8260a78529e6d2bde436"

helper_path = ROOT / "hilega-atomic-binding-deployment/deploy.py"
if helper_path.is_symlink() or not helper_path.is_file():
    raise ValueError("REGULAR_HELPER_REQUIRED")
if hashlib.sha256(helper_path.read_bytes()).hexdigest() != "__HELPER_SHA__":
    raise ValueError("DEPLOYMENT_HELPER_CHANGED")
spec = importlib.util.spec_from_file_location("_local_binding_helpers", helper_path)
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
guard = legacy.guard
Blocked = guard.Blocked
need = guard.need


def sha(path):
    need(path.is_file() and not path.is_symlink(), "REGULAR_FILE_REQUIRED")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stopped():
    legacy.managed.require_stopped(ROOT)


__WORKSPACE_CODE__


def database_state(plan):
    application = Path(plan["database"])
    application_fingerprint = workspace(plan)
    adapter = guard.target(
        ROOT, "data/research/hilega-broker-adapter-closed/adapter.sqlite",
    )
    sha(adapter)
    need(application.stat().st_dev == adapter.stat().st_dev,
         "SAME_FILESYSTEM_REQUIRED")
    for path in (application, adapter):
        with closing(sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, timeout=10,
        )) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            need(db.execute("PRAGMA journal_mode").fetchone()[0] == "delete",
                 "DELETE_JOURNAL_REQUIRED")
            if path == adapter:
                meta = json.loads(db.execute(
                    "SELECT data FROM meta WHERE id=1"
                ).fetchone()[0])
                need(meta.get("mode") == "LIVE_CLOSED"
                     and re.fullmatch(
                         r"UPSTOX:[0-9a-f]{64}", str(meta.get("scope", ""))
                     ) is not None,
                     "LIVE_CLOSED_PINNED_ADAPTER_REQUIRED")
                for table in ("requests", "attempts", "receipts"):
                    need(db.execute(
                        "SELECT COUNT(*) FROM " + table
                    ).fetchone()[0] == 0, "ADAPTER_ACTIVITY_REQUIRES_REVIEW")
                adapter_fingerprint = hashlib.sha256(
                    "\n".join(db.iterdump()).encode()
                ).hexdigest()
    return application_fingerprint, adapter_fingerprint


def context():
    plan_path = guard.target(ROOT, PLAN_REL)
    need(sha(plan_path) == PIN_PLAN, "ACTIVATION_PLAN_CHANGED")
    plan = guard.read_json(plan_path)
    backup = plan_path.parent
    package = ROOT / "hilega-atomic-binding-release-v1"
    need(
        plan["model"] == "HILEGA_LOCAL_BINDING_ACTIVATION_PLAN_V1"
        and plan["root"] == str(ROOT)
        and plan["backup"] == str(backup)
        and plan["package"] == str(package)
        and plan["release_manifest_sha256"] == PIN_RELEASE,
        "ACTIVATION_PLAN_IDENTITY_INVALID",
    )
    need(plan["planned_configuration_changes"] == {KEY: "1"},
         "EXACT_BINDING_FLAG_CHANGE_REQUIRED")
    need(sha(backup / "original.env") == plan["original_env_sha256"],
         "ORIGINAL_ENV_BACKUP_CHANGED")
    need(sha(backup / "candidate.env") == plan["candidate_env_sha256"],
         "CANDIDATE_ENV_CHANGED")
    need(sha(backup / "startup-private.json") == plan["startup_sha256"],
         "STARTUP_RECORD_CHANGED")
    old = dotenv_values(backup / "original.env")
    new = dotenv_values(backup / "candidate.env")
    changed = {
        name for name in set(old) | set(new)
        if old.get(name) != new.get(name)
    }
    need(changed == {KEY} and old.get(KEY, "0") == "0" and new.get(KEY) == "1",
         "ONLY_BINDING_FLAG_MAY_CHANGE")
    need(
        old.get("HILEGA_PRODUCTION_EXECUTION_ROUTE") == "PREPARATION_ONLY"
        and old.get("HILEGA_PRODUCTION_WORKSPACE_MODE") == "SIMULATION_ONLY",
        "PREPARATION_ONLY_CONFIGURATION_REQUIRED",
    )
    current = sha(guard.target(ROOT, ".env"))
    need(current in {
        plan["original_env_sha256"], plan["candidate_env_sha256"],
    }, "ACTIVE_ENV_CHANGED_OUTSIDE_ACTIVATION")
    need(sha(package / "manifest.json") == PIN_RELEASE,
         "RELEASE_MANIFEST_CHANGED")
    release = guard.read_json(package / "manifest.json")
    need(plan["code_files"] == release["files"]
         and plan["dependencies"] == release["dependencies"],
         "PLAN_CODE_REFERENCES_CHANGED")
    for name, expected in {
        **plan["dependencies"], **plan["code_files"], **plan["guard_files"],
    }.items():
        need(sha(guard.target(ROOT, name)) == expected, "DEPLOYED_CODE_CHANGED")
    for name, field in (
        ("validation.json", "validation_sha256"),
        ("stage-manifest.json", "stage_manifest_sha256"),
    ):
        need(sha(package / name) == release[field],
             "VALIDATION_EVIDENCE_CHANGED")
    database_state(plan)
    return plan, backup, current


def save(backup, state):
    guard.atomic_bytes(
        backup / "activation-state.json",
        json.dumps(state, indent=2).encode(), 0o600,
    )


def check():
    plan, backup, current = context()
    path = backup / "activation-state.json"
    state = guard.read_json(path) if path.exists() else None
    if state:
        need(state["root"] == str(ROOT) and state["plan_sha256"] == PIN_PLAN,
             "ACTIVATION_STATE_IDENTITY_MISMATCH")
        need(state["phase"] in {"APPLIED", "ROLLED_BACK"},
             "INTERRUPTED_ACTIVATION_REQUIRES_RECOVERY")
    enabled = current == plan["candidate_env_sha256"]
    need(not enabled or state is not None and state["phase"] == "APPLIED",
         "UNJOURNALED_CONFIGURATION_CHANGE")
    return dict(
        status=("LOCAL_BINDING_CONFIGURATION_APPLIED" if enabled
                else "LOCAL_BINDING_ACTIVATION_CHECKS_PASS"),
        configured_binding_enabled=enabled,
        controller_mode="PAUSED", execution_route="PREPARATION_ONLY",
        process_restart_verified=False, apply_ready=False,
        production_execution_enabled=False,
    )


def apply(checkpoint=lambda phase: None):
    with guard.deployment_lock(ROOT):
        stopped()
        plan, backup, current = context()
        need(current == plan["original_env_sha256"], "BASELINE_ENV_REQUIRED")
        need(not (backup / "activation-state.json").exists(),
             "ACTIVATION_STATE_EXISTS_REVIEW_BEFORE_RETRY")
        before = database_state(plan)
        mode = (ROOT / ".env").stat().st_mode & 0o777
        state = dict(
            model="HILEGA_LOCAL_BINDING_CONFIGURATION_TRANSACTION_V1",
            root=str(ROOT), plan_sha256=PIN_PLAN, phase="PREPARED",
            original_mode=mode, production_execution_enabled=False,
        )
        save(backup, state)
        try:
            stopped()
            need(sha(ROOT / ".env") == plan["original_env_sha256"],
                 "ACTIVE_ENV_CHANGED")
            need(sha(backup / "candidate.env") == plan["candidate_env_sha256"],
                 "CANDIDATE_ENV_CHANGED")
            need(database_state(plan) == before, "DATABASE_CHANGED")
            guard.atomic_bytes(
                ROOT / ".env", (backup / "candidate.env").read_bytes(), mode,
            )
            checkpoint("AFTER_ENV_REPLACE")
            stopped()
            need(database_state(plan) == before, "DATABASE_CHANGED")
            need(sha(ROOT / ".env") == plan["candidate_env_sha256"],
                 "ACTIVATION_WRITE_MISMATCH")
            state["phase"] = "APPLIED"
            save(backup, state)
        except BaseException:
            state["phase"] = "INTERRUPTED_REQUIRES_RECOVERY"
            save(backup, state)
            raise
    return dict(
        status="LOCAL_BINDING_CONFIG_APPLIED_SERVICES_STILL_STOPPED",
        backup=str(backup), configured_binding_enabled=True,
        controller_mode="PAUSED", services_started=False,
        database_modified=False, production_execution_enabled=False,
    )


def rollback():
    with guard.deployment_lock(ROOT):
        stopped()
        plan, backup, current = context()
        state = guard.read_json(backup / "activation-state.json")
        need(state["root"] == str(ROOT) and state["plan_sha256"] == PIN_PLAN,
             "ACTIVATION_STATE_IDENTITY_MISMATCH")
        before = database_state(plan)
        need(sha(backup / "original.env") == plan["original_env_sha256"],
             "ORIGINAL_ENV_BACKUP_CHANGED")
        guard.atomic_bytes(
            ROOT / ".env", (backup / "original.env").read_bytes(),
            state["original_mode"],
        )
        need(database_state(plan) == before, "DATABASE_CHANGED")
        state["phase"] = "ROLLED_BACK"
        save(backup, state)
    return dict(
        status="LOCAL_BINDING_CONFIG_RESTORED_SERVICES_STILL_STOPPED",
        configured_binding_enabled=False, services_started=False,
        database_restored=False, production_execution_enabled=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "apply", "rollback"),
                        nargs="?", default="check")
    parser.add_argument("--confirmation")
    args = parser.parse_args()
    if args.action != "check":
        need(args.confirmation == (
            "ENABLE_LOCAL_BINDING_ONLY" if args.action == "apply"
            else "RESTORE_LOCAL_BINDING_OFF"
        ), "EXPLICIT_ACTION_REQUIRED")
    return {"check": check, "apply": apply, "rollback": rollback}[args.action]()


if __name__ == "__main__":
    os.umask(0o077)
    try:
        print(json.dumps(main(), indent=2))
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({
            "status": "BLOCKED", "reason": str(exc),
            "production_execution_enabled": False,
        }))
        raise SystemExit(1)
'''

tests = r'''import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location(
    "local_binding_activation", Path(__file__).with_name("activate.py"),
)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(tool, "ROOT", root)
    monkeypatch.setattr(tool, "stopped", lambda: None)
    backup = (root / tool.PLAN_REL).parent
    backup.mkdir(parents=True)
    original = (
        "HILEGA_PRODUCTION_EXECUTION_ROUTE=PREPARATION_ONLY\n"
        "HILEGA_PRODUCTION_WORKSPACE_MODE=SIMULATION_ONLY\n"
    )
    (root / ".env").write_text(original)
    (backup / "original.env").write_text(original)
    (backup / "candidate.env").write_text(original + tool.KEY + "=1\n")
    put(backup / "startup-private.json", {"synthetic": True})

    code = root / "backend/test.py"
    code.parent.mkdir()
    code.write_text("synthetic code")
    package = root / "hilega-atomic-binding-release-v1"
    put(package / "validation.json", {"status": "PASS"})
    put(package / "stage-manifest.json", {"synthetic": True})
    release = dict(
        files={"backend/test.py": sha(code)}, dependencies={},
        validation_sha256=sha(package / "validation.json"),
        stage_manifest_sha256=sha(package / "stage-manifest.json"),
    )
    put(package / "manifest.json", release)
    monkeypatch.setattr(tool, "PIN_RELEASE", sha(package / "manifest.json"))

    database = root / "data/research/hilega-production-workspace/sim.sqlite"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as db:
        db.executescript(
            "CREATE TABLE control(id INTEGER PRIMARY KEY,data TEXT);"
            "CREATE TABLE preparation_route(id INTEGER PRIMARY KEY,data TEXT);"
            "CREATE TABLE sim_stop_state(id INTEGER PRIMARY KEY,"
            "generation INTEGER,handled INTEGER);"
        )
        db.execute("INSERT INTO control VALUES(1,?)",
                   (json.dumps({"mode": "PAUSED"}),))
        db.execute("INSERT INTO preparation_route VALUES(1,?)", (json.dumps({
            "route": "PREPARATION_ONLY",
            "model": "APPLICATION_PREPARATION_ROUTE_V1",
        }),))
        db.execute("INSERT INTO sim_stop_state VALUES(1,0,0)")
        for name in (
            "intents", "sim_orders", "sim_fills", "sim_allocation_reservations",
            "preparation_plans", "preparation_shadow_holds", "preparation_outbox",
        ):
            db.execute("CREATE TABLE " + name + "(id TEXT)")

    adapter = root / "data/research/hilega-broker-adapter-closed/adapter.sqlite"
    adapter.parent.mkdir(parents=True)
    with sqlite3.connect(adapter) as db:
        db.execute("CREATE TABLE meta(id INTEGER PRIMARY KEY,data TEXT)")
        db.execute("INSERT INTO meta VALUES(1,?)", (json.dumps({
            "mode": "LIVE_CLOSED", "scope": "UPSTOX:" + "a" * 64,
        }),))
        for name in ("requests", "attempts", "receipts"):
            db.execute("CREATE TABLE " + name + "(id TEXT)")

    plan = dict(
        model="HILEGA_LOCAL_BINDING_ACTIVATION_PLAN_V1",
        root=str(root), backup=str(backup), package=str(package),
        database=str(database), release_manifest_sha256=tool.PIN_RELEASE,
        planned_configuration_changes={tool.KEY: "1"},
        original_env_sha256=sha(backup / "original.env"),
        candidate_env_sha256=sha(backup / "candidate.env"),
        startup_sha256=sha(backup / "startup-private.json"),
        code_files=release["files"], dependencies={}, guard_files={},
    )
    put(root / tool.PLAN_REL, plan)
    monkeypatch.setattr(tool, "PIN_PLAN", sha(root / tool.PLAN_REL))
    return root, backup, database, adapter


def test_apply_rollback_change_only_environment(setup):
    root, backup, database, adapter = setup
    original = (root / ".env").read_bytes()
    before = database.read_bytes(), adapter.read_bytes()
    assert tool.check()["configured_binding_enabled"] is False
    assert tool.apply()["services_started"] is False
    assert tool.check()["configured_binding_enabled"] is True
    assert tool.rollback()["database_restored"] is False
    assert (root / ".env").read_bytes() == original
    assert (database.read_bytes(), adapter.read_bytes()) == before


def test_running_processes_block_activation(setup, monkeypatch):
    def running():
        raise tool.Blocked("STILL_RUNNING")
    monkeypatch.setattr(tool, "stopped", running)
    with pytest.raises(tool.Blocked, match="STILL_RUNNING"):
        tool.apply()
    assert not (setup[1] / "activation-state.json").exists()


@pytest.mark.parametrize("which", ["candidate", "code", "environment"])
def test_changed_inputs_block_activation(setup, which):
    root, backup, _, _ = setup
    path = {
        "candidate": backup / "candidate.env",
        "code": root / "backend/test.py",
        "environment": root / ".env",
    }[which]
    path.write_text("changed")
    with pytest.raises(tool.Blocked):
        tool.apply()
    assert not (backup / "activation-state.json").exists()


@pytest.mark.parametrize("kind", ["application", "adapter", "binding"])
def test_existing_activity_blocks_activation(setup, kind):
    path = setup[3] if kind == "adapter" else setup[2]
    with sqlite3.connect(path) as db:
        if kind == "binding":
            db.execute("CREATE TABLE preparation_request_bindings(id TEXT)")
        table = {
            "application": "intents", "adapter": "requests",
            "binding": "preparation_request_bindings",
        }[kind]
        db.execute("INSERT INTO " + table + " VALUES('existing')")
    with pytest.raises(tool.Blocked):
        tool.apply()


def test_interruption_after_environment_write_is_recoverable(setup):
    class Interrupted(BaseException):
        pass
    def fail(phase):
        raise Interrupted()
    with pytest.raises(Interrupted):
        tool.apply(checkpoint=fail)
    with pytest.raises(tool.Blocked, match="INTERRUPTED_ACTIVATION"):
        tool.check()
    tool.rollback()
    assert tool.check()["configured_binding_enabled"] is False


def test_extra_candidate_setting_is_rejected_even_with_matching_hash(setup, monkeypatch):
    root, backup, _, _ = setup
    candidate = backup / "candidate.env"
    candidate.write_text(candidate.read_text() + "UNRELATED_SETTING=1\n")
    path = root / tool.PLAN_REL
    plan = json.loads(path.read_text())
    plan["candidate_env_sha256"] = sha(candidate)
    put(path, plan)
    monkeypatch.setattr(tool, "PIN_PLAN", sha(path))
    with pytest.raises(tool.Blocked, match="ONLY_BINDING_FLAG"):
        tool.apply()


def test_new_activity_blocks_rollback(setup):
    tool.apply()
    with sqlite3.connect(setup[3]) as db:
        db.execute("INSERT INTO requests VALUES('new')")
    before = (setup[0] / ".env").read_bytes()
    with pytest.raises(tool.Blocked, match="ADAPTER_ACTIVITY"):
        tool.rollback()
    assert (setup[0] / ".env").read_bytes() == before


def test_external_configuration_change_is_not_overwritten(setup):
    tool.apply()
    path = setup[0] / ".env"
    path.write_text(path.read_text() + "EXTERNAL_CHANGE=1\n")
    before = path.read_bytes()
    with pytest.raises(tool.Blocked, match="ACTIVE_ENV_CHANGED"):
        tool.rollback()
    assert path.read_bytes() == before
'''

tool = tool.replace(
    "__HELPER_SHA__", hashlib.sha256(base.read_bytes()).hexdigest()
).replace("__WORKSPACE_CODE__", workspace_code)

for name, text in (("activate.py", tool), ("test_activate.py", tests)):
    compile(text, name, "exec")

folder.mkdir()
(folder / "activate.py").write_text(tool)
(folder / "test_activate.py").write_text(tests)
print("Created:", folder)
print("Syntax checked. Tests not executed. No activation performed.")