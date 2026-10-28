from pathlib import Path
import hashlib

folder = Path("hilega-auto-limit-deployment")
if folder.exists() or folder.is_symlink():
    raise SystemExit("STOP: deployment tool directory already exists")

guard_path = Path("hilega-production-application-deployment/deploy.py")
managed_path = guard_path.with_name("managed_processes.py")
for path in (guard_path, managed_path):
    if path.is_symlink() or not path.is_file():
        raise SystemExit("STOP: regular helper required: " + str(path))

tool = r'''"""Preparation-route code deployment. Default action is read-only check."""
import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
PIN_MANIFEST = "13f052acf497ca10ac4b1f3a289f6ede36559b37e273a5143c5a15ebf6773665"
PIN_PLAN = "5d352e4ec40848793a8497f301a6c06ea20642052859fd941a256bbf3387d227"
PLAN_REL = "backups/hilega-auto-limit-maintenance-_mzrnlv9/plan.json"
PAYLOAD = {
    "backend/market_lab/hilega_preparation_runtime_v1/source.py",
    "backend/market_lab/hilega_preparation_runtime_v1/limit_candidate.py",
    "tests/test_hilega_limit_candidate_v1.py",
    "tests/test_hilega_auto_limit_wiring_v1.py",
}

def load_helper(name, path, expected):
    if path.is_symlink() or not path.is_file():
        raise ValueError("REGULAR_HELPER_REQUIRED")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("DEPLOYMENT_HELPER_CHANGED")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

guard = load_helper(
    "_auto_limit_file_guards",
    ROOT / "hilega-production-application-deployment/deploy.py",
    "__GUARD_SHA__",
)
managed = load_helper(
    "_auto_limit_process_guards",
    ROOT / "hilega-production-application-deployment/managed_processes.py",
    "__MANAGED_SHA__",
)
Blocked = guard.Blocked
need = guard.need

def sha(path):
    need(path.is_file() and not path.is_symlink(), "REGULAR_FILE_REQUIRED")
    return hashlib.sha256(path.read_bytes()).hexdigest()

def stopped():
    managed.require_stopped(ROOT)

def workspace(plan):
    path = Path(plan["database"])
    need(path == ROOT / "data/research/hilega-production-workspace/sim.sqlite",
         "WORKSPACE_PATH_CHANGED")
    sha(path)
    with closing(sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10,
    )) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        control = json.loads(db.execute(
            "SELECT data FROM control WHERE id=1"
        ).fetchone()[0])
        route = json.loads(db.execute(
            "SELECT data FROM preparation_route WHERE id=1"
        ).fetchone()[0])
        need(control["mode"] == "PAUSED", "CONTROLLER_MUST_REMAIN_PAUSED")
        need(route == {
            "route": "PREPARATION_ONLY",
            "model": "APPLICATION_PREPARATION_ROUTE_V1",
        }, "PERSISTED_PREPARATION_ROUTE_REQUIRED")
        stop = db.execute(
            "SELECT generation,handled FROM sim_stop_state WHERE id=1"
        ).fetchone()
        need(stop is not None and stop[0] == stop[1], "STOP_PENDING")
        for table in (
            "intents", "sim_orders", "sim_fills", "sim_allocation_reservations",
            "preparation_plans", "preparation_shadow_holds", "preparation_outbox",
        ):
            need(db.execute(
                "SELECT COUNT(*) FROM " + table
            ).fetchone()[0] == 0, "WORKSPACE_ACTIVITY_REQUIRES_REVIEW")
        return hashlib.sha256(
            "\n".join(db.iterdump()).encode()
        ).hexdigest()

def context(payload=True):
    plan_path = guard.target(ROOT, PLAN_REL)
    need(sha(plan_path) == PIN_PLAN, "MAINTENANCE_PLAN_CHANGED")
    plan = guard.read_json(plan_path)
    backup = plan_path.parent
    package = ROOT / "hilega-auto-limit-release-v1"
    need(plan["root"] == str(ROOT)
         and plan["backup"] == str(backup)
         and plan["package"] == str(package), "MAINTENANCE_ROOT_MISMATCH")
    need(plan["manifest_sha256"] == PIN_MANIFEST, "PLAN_RELEASE_MISMATCH")
    need(sha(backup / "startup-private.json") == plan["startup_sha256"],
         "PRIVATE_STARTUP_RECORD_CHANGED")
    need(sha(ROOT / ".env") == plan["env_sha256"], "ENVIRONMENT_CHANGED")
    config = dotenv_values(ROOT / ".env")
    need(config.get("HILEGA_PRODUCTION_EXECUTION_ROUTE") == "PREPARATION_ONLY"
         and config.get("HILEGA_PRODUCTION_WORKSPACE_MODE") == "SIMULATION_ONLY",
         "CONFIGURATION_REQUIRES_REVIEW")
    for name, expected in plan["guard_files"].items():
        need(sha(guard.target(ROOT, name)) == expected, "GUARD_FILE_CHANGED")
    manifest_path = guard.target(package, "manifest.json")
    need(sha(manifest_path) == PIN_MANIFEST, "RELEASE_MANIFEST_CHANGED")
    release = guard.read_json(manifest_path)
    need(set(release["files"]) == PAYLOAD
         and set(release["target_baseline"]) == PAYLOAD,
         "EXACT_RELEASE_FILES_REQUIRED")
    for name, expected in release["dependencies"].items():
        need(sha(guard.target(ROOT, name)) == expected, "DEPENDENCY_CHANGED")
    for name, field in (
        ("validation.json", "validation_sha256"),
        ("stage-manifest.json", "stage_manifest_sha256"),
    ):
        need(sha(guard.target(package, name)) == release[field],
             "VALIDATION_EVIDENCE_CHANGED")
    proof = guard.read_json(package / "validation.json")
    need(proof.get("status") == "PASS" and proof.get("pytest_exit_code") == 0,
         "PASSING_VALIDATION_REQUIRED")
    if payload:
        for name, expected in release["files"].items():
            need(sha(guard.target(package / "files", name)) == expected,
                 "PACKAGED_FILE_CHANGED")
    workspace(plan)
    return plan, release, package, backup / "code-transaction"

def current(name):
    path = guard.target(ROOT, name)
    return sha(path) if path.exists() else None

def journal(transaction, value):
    guard.atomic_bytes(
        transaction / "state.json", json.dumps(value, indent=2).encode(), 0o600,
    )

def check():
    plan, release, package, transaction = context()
    expected = release["target_baseline"]
    status = "AUTO_LIMIT_CODE_CHECKS_PASS"
    if (transaction / "state.json").exists():
        state = guard.read_json(transaction / "state.json")
        need(state["root"] == str(ROOT) and state["plan_sha256"] == PIN_PLAN,
             "TRANSACTION_IDENTITY_MISMATCH")
        need(state["phase"] == "APPLIED", "RECOVERY_REVIEW_REQUIRED")
        expected = release["files"]
        status = "AUTO_LIMIT_ALREADY_APPLIED"
    need(all(current(name) == expected[name] for name in PAYLOAD),
         "TARGET_CHANGED")
    return dict(
        status=status, controller_mode="PAUSED",
        execution_route="PREPARATION_ONLY", apply_ready=False,
        processes_signalled=False, production_execution_enabled=False,
    )

def apply(checkpoint=lambda name: None):
    with guard.deployment_lock(ROOT):
        stopped()
        plan, release, package, transaction = context()
        need(not transaction.exists(), "TRANSACTION_ALREADY_EXISTS")
        need(all(current(n) == release["target_baseline"][n] for n in PAYLOAD),
             "TARGET_CHANGED")
        transaction.mkdir(mode=0o700)
        modes = {}
        for name in sorted(PAYLOAD):
            path = guard.target(ROOT, name)
            modes[name] = path.stat().st_mode & 0o777 if path.exists() else 0o644
            if path.exists():
                guard.atomic_bytes(
                    guard.target(transaction / "original", name),
                    path.read_bytes(), modes[name],
                )
        database_before = workspace(plan)
        with closing(sqlite3.connect(
            Path(plan["database"]).as_uri() + "?mode=ro", uri=True,
        )) as source, closing(sqlite3.connect(
            transaction / "stopped-workspace.sqlite"
        )) as destination:
            source.backup(destination)
        os.chmod(transaction / "stopped-workspace.sqlite", 0o600)
        state = dict(
            model="HILEGA_AUTO_LIMIT_CODE_TRANSACTION_V1",
            root=str(ROOT), plan_sha256=PIN_PLAN,
            before=release["target_baseline"], files=release["files"],
            modes=modes, phase="BACKUP_COMPLETE",
            database_fingerprint=database_before,
            production_execution_enabled=False,
        )
        journal(transaction, state)
        try:
            state["phase"] = "APPLYING"
            journal(transaction, state)
            for name in sorted(PAYLOAD):
                stopped()
                need(workspace(plan) == database_before, "DATABASE_CHANGED")
                need(sha(ROOT / ".env") == plan["env_sha256"], "ENVIRONMENT_CHANGED")
                need(current(name) == state["before"][name], "TARGET_CHANGED")
                source = guard.target(package / "files", name)
                need(sha(source) == state["files"][name], "PACKAGED_FILE_CHANGED")
                guard.atomic_bytes(
                    guard.target(ROOT, name), source.read_bytes(), modes[name],
                )
                checkpoint(name)
            stopped()
            need(workspace(plan) == database_before, "DATABASE_CHANGED")
            state["phase"] = "APPLIED"
            journal(transaction, state)
        except BaseException:
            state["phase"] = "INTERRUPTED_REQUIRES_RECOVERY"
            journal(transaction, state)
            raise
    return dict(
        status="AUTO_LIMIT_CODE_APPLIED_SERVICES_STILL_STOPPED",
        transaction=str(transaction), services_started=False,
        database_modified=False, configuration_changed=False,
        production_execution_enabled=False,
    )

def rollback():
    with guard.deployment_lock(ROOT):
        stopped()
        plan, release, package, transaction = context(payload=False)
        state = guard.read_json(transaction / "state.json")
        need(state["root"] == str(ROOT) and state["plan_sha256"] == PIN_PLAN
             and state["before"] == release["target_baseline"]
             and state["files"] == release["files"],
             "TRANSACTION_IDENTITY_MISMATCH")
        for name in sorted(PAYLOAD):
            need(current(name) in {state["before"][name], state["files"][name]},
                 "TARGET_CHANGED_OUTSIDE_TRANSACTION")
            if state["before"][name] is not None:
                need(sha(guard.target(transaction / "original", name))
                     == state["before"][name], "ORIGINAL_BACKUP_CHANGED")
        for name in sorted(PAYLOAD):
            stopped()
            workspace(plan)
            path = guard.target(ROOT, name)
            need(current(name) in {state["before"][name], state["files"][name]},
                 "TARGET_CHANGED_DURING_RECOVERY")
            if state["before"][name] is None:
                path.unlink(missing_ok=True)
                guard.fsync_directory(path.parent)
            else:
                original = guard.target(transaction / "original", name)
                need(sha(original) == state["before"][name], "ORIGINAL_BACKUP_CHANGED")
                guard.atomic_bytes(path, original.read_bytes(), state["modes"][name])
        state["phase"] = "ROLLED_BACK"
        journal(transaction, state)
    return dict(
        status="AUTO_LIMIT_CODE_ROLLED_BACK_SERVICES_STILL_STOPPED",
        database_restored=False, configuration_changed=False,
        services_started=False, production_execution_enabled=False,
    )

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "apply", "rollback"),
                        nargs="?", default="check")
    parser.add_argument("--confirmation")
    args = parser.parse_args()
    if args.action != "check":
        required = (
            "APPLY_AUTO_LIMIT_CODE_ONLY" if args.action == "apply"
            else "ROLLBACK_AUTO_LIMIT_CODE_ONLY"
        )
        need(args.confirmation == required, "EXPLICIT_ACTION_REQUIRED")
    return {"check": check, "apply": apply, "rollback": rollback}[args.action]()

if __name__ == "__main__":
    os.umask(0o077)
    try:
        print(json.dumps(main(), indent=2))
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps(dict(
            status="BLOCKED", reason=str(exc),
            production_execution_enabled=False,
        )))
        raise SystemExit(1)
'''

tests = r'''import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location(
    "auto_limit_deployment", Path(__file__).with_name("deploy.py"),
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
    package = root / "hilega-auto-limit-release-v1"
    backup = (root / tool.PLAN_REL).parent
    before, files = {}, {}
    for i, name in enumerate(sorted(tool.PAYLOAD)):
        source = package / "files" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("new-" + str(i))
        files[name] = sha(source)
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if i != 3:
            target.write_text("old-" + str(i))
        before[name] = sha(target) if target.exists() else None
    put(package / "validation.json", {"status": "PASS", "pytest_exit_code": 0})
    put(package / "stage-manifest.json", {"synthetic": True})
    release = dict(
        files=files, target_baseline=before, dependencies={},
        validation_sha256=sha(package / "validation.json"),
        stage_manifest_sha256=sha(package / "stage-manifest.json"),
    )
    put(package / "manifest.json", release)
    monkeypatch.setattr(tool, "PIN_MANIFEST", sha(package / "manifest.json"))
    (root / ".env").write_text(
        "HILEGA_PRODUCTION_EXECUTION_ROUTE=PREPARATION_ONLY\n"
        "HILEGA_PRODUCTION_WORKSPACE_MODE=SIMULATION_ONLY\n"
    )
    put(backup / "startup-private.json", {"synthetic": True})
    database = root / "data/research/hilega-production-workspace/sim.sqlite"
    database.parent.mkdir(parents=True, exist_ok=True)
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
        for table in (
            "intents", "sim_orders", "sim_fills", "sim_allocation_reservations",
            "preparation_plans", "preparation_shadow_holds", "preparation_outbox",
        ):
            db.execute("CREATE TABLE " + table + "(id TEXT)")
    plan = dict(
        root=str(root), backup=str(backup), package=str(package),
        database=str(database), manifest_sha256=tool.PIN_MANIFEST,
        env_sha256=sha(root / ".env"),
        startup_sha256=sha(backup / "startup-private.json"), guard_files={},
    )
    put(root / tool.PLAN_REL, plan)
    monkeypatch.setattr(tool, "PIN_PLAN", sha(root / tool.PLAN_REL))
    return root, package, backup, database, before


def test_apply_and_rollback_preserve_database_and_configuration(setup):
    root, package, backup, database, before = setup
    db_before = database.read_bytes()
    env_before = (root / ".env").read_bytes()
    assert tool.check()["status"] == "AUTO_LIMIT_CODE_CHECKS_PASS"
    assert tool.apply()["services_started"] is False
    assert tool.check()["status"] == "AUTO_LIMIT_ALREADY_APPLIED"
    assert tool.rollback()["database_restored"] is False
    assert {name: tool.current(name) for name in tool.PAYLOAD} == before
    assert database.read_bytes() == db_before
    assert (root / ".env").read_bytes() == env_before


def test_running_processes_block_apply(setup, monkeypatch):
    def running():
        raise tool.Blocked("STILL_RUNNING")
    monkeypatch.setattr(tool, "stopped", running)
    with pytest.raises(tool.Blocked, match="STILL_RUNNING"):
        tool.apply()
    assert not (setup[2] / "code-transaction").exists()


@pytest.mark.parametrize("change", ["target", "payload", "env", "manifest"])
def test_changed_inputs_block_before_apply(setup, change):
    root, package, backup, database, before = setup
    name = next(n for n, value in before.items() if value is not None)
    path = {
        "target": root / name, "payload": package / "files" / name,
        "env": root / ".env", "manifest": package / "manifest.json",
    }[change]
    path.write_text("changed")
    with pytest.raises((tool.Blocked, ValueError)):
        tool.apply()
    assert not (backup / "code-transaction").exists()


def test_interrupted_apply_can_restore_original_files(setup):
    class Interrupted(BaseException):
        pass
    def interrupt(name):
        raise Interrupted()
    with pytest.raises(Interrupted):
        tool.apply(checkpoint=interrupt)
    tool.rollback()
    assert {n: tool.current(n) for n in tool.PAYLOAD} == setup[4]


def test_changed_original_backup_blocks_rollback(setup):
    tool.apply()
    name = next(n for n, value in setup[4].items() if value is not None)
    (setup[2] / "code-transaction/original" / name).write_text("changed")
    with pytest.raises(tool.Blocked, match="ORIGINAL_BACKUP_CHANGED"):
        tool.rollback()


def test_new_workspace_activity_blocks_rollback(setup):
    tool.apply()
    with sqlite3.connect(setup[3]) as db:
        db.execute("INSERT INTO intents VALUES('unexpected')")
    with pytest.raises(tool.Blocked, match="WORKSPACE_ACTIVITY"):
        tool.rollback()
'''

tool = tool.replace(
    "__GUARD_SHA__", hashlib.sha256(guard_path.read_bytes()).hexdigest()
).replace(
    "__MANAGED_SHA__", hashlib.sha256(managed_path.read_bytes()).hexdigest()
)
for name, text in (("deploy.py", tool), ("test_deploy.py", tests)):
    compile(text, name, "exec")

folder.mkdir()
for name, text in (("deploy.py", tool), ("test_deploy.py", tests)):
    (folder / name).write_text(text)

print("Created:", folder)
print("Syntax checked. Tests not executed. No processes stopped or code applied.")