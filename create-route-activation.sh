~/RB-ITOS-AI/.venv/bin/python - <<'PY'
import ast
from pathlib import Path

repo = Path.home() / "RB-ITOS-AI"
folder = repo / "hilega-preparation-route-activation"
if folder.exists() or folder.is_symlink():
    raise SystemExit("STOP: activation-tool directory already exists")

module = r'''"""Guarded preparation enrollment/recovery. No service start/stop or resume."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys

TOOLS = Path(__file__).resolve().parents[1] / "hilega-production-application-deployment"
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location("route_activation_guards", TOOLS/"deploy.py")
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
from managed_processes import require_stopped

BEFORE = "d651e0e8d7c36ba7ed5eeb257ddd3bd3676c158b734035e812d9c2c7ed32138a"
CANDIDATE = "53db2a87853392fc69a2641709c31a98a05329968ef64dc50927bb187f00b892"
RELEASE = "3f583f5cd16034382cc773a4a4c08396c79675885905f6394bad8dd3b6b79369"
Blocked = g.Blocked


def ro(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    return db


def logical_hash(path):
    db = ro(path)
    try:
        return hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()
    finally:
        db.close()


def clone(source, destination):
    src = ro(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def code_check(root):
    package = root/"hilega-production-pricing-preview-release-v1"
    g.need(g.sha(package/"manifest.json")==RELEASE, "DEPLOYED_RELEASE_IDENTITY_CHANGED")
    manifest = g.read_json(package/"manifest.json")
    for name, wanted in {**manifest["unchanged_dependencies"], **manifest["files"]}.items():
        path = g.target(root, name)
        g.need(path.is_file() and g.sha(path)==wanted, "DEPLOYED_CODE_CHANGED_"+name)


def read_plan(root, folder):
    from dotenv import dotenv_values
    root, folder = Path(root).resolve(), Path(folder).absolute()
    g.need(not folder.is_symlink() and
           folder.resolve().is_relative_to(root/"backups") and
           folder.stat().st_mode & 0o077 == 0, "PRIVATE_PLAN_DIRECTORY_REQUIRED")
    plan = g.read_json(folder/"activation-plan.json")
    database = root/"data/research/hilega-production-workspace/sim.sqlite"
    g.need(plan.get("model")=="HILEGA_PREPARATION_ACTIVATION_PLAN_V1"
           and plan.get("root")==str(root)
           and plan.get("database")==str(database), "ACTIVATION_PLAN_SCOPE_INVALID")
    g.target(root, ".env")
    g.target(root, str(database.relative_to(root)))
    g.need(g.sha(folder/"before.env")==BEFORE
           and g.sha(folder/"candidate.env")==CANDIDATE
           and plan.get("original_env_sha256")==BEFORE
           and plan.get("candidate_env_sha256")==CANDIDATE,
           "ACTIVATION_CONFIGURATION_CHANGED")
    changes = {
        "HILEGA_PRODUCTION_EXECUTION_ROUTE": "PREPARATION_ONLY",
        "HILEGA_PRODUCTION_WORKSPACE_MODE": "SIMULATION_ONLY",
        "HILEGA_PRODUCTION_SIM_DB": str(database),
        "HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED": "1",
        "HILEGA_PREPARATION_CAPTURE_ON_SIGNAL": "1",
    }
    g.need(plan.get("planned_configuration_changes")==changes,
           "ACTIVATION_SETTINGS_INVALID")
    before = dotenv_values(folder/"before.env")
    after = dotenv_values(folder/"candidate.env")
    g.need(all(after.get(k)==v for k,v in changes.items())
           and all(before.get(k)==after.get(k)
                   for k in set(before)|set(after) if k not in changes),
           "UNRELATED_CONFIGURATION_CHANGED")
    return plan, database


def post_check(database):
    db = ro(database)
    try:
        control = json.loads(db.execute("SELECT data FROM control WHERE id=1").fetchone()[0])
        g.need(control["mode"]=="PAUSED", "CONTROLLER_MUST_REMAIN_PAUSED")
        route = json.loads(db.execute("SELECT data FROM preparation_route WHERE id=1").fetchone()[0])
        g.need(route=={"route":"PREPARATION_ONLY","model":"APPLICATION_PREPARATION_ROUTE_V1"},
               "PERSISTED_ROUTE_INVALID")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in (
            "intents","sim_orders","sim_fills","sim_allocation_reservations",
            "preparation_plans","preparation_shadow_holds","preparation_outbox",
            "preparation_consumed",
        ):
            if name in tables:
                g.need(not db.execute("SELECT 1 FROM "+name+" LIMIT 1").fetchone(),
                       "UNEXPECTED_ACTIVITY_"+name)
    finally:
        db.close()


def enroll(root, database, changes):
    # Short-lived environment overlay; never loads credentials or calls a provider.
    previous = {k:os.environ.get(k) for k in changes}
    os.environ.update(changes)
    try:
        sys.path.insert(0, str(root/"backend"))
        from market_lab.hilega_production_foundation.core import Store, SimBroker, Service
        from market_lab.hilega_preparation_runtime_v1.source import Source
        store = Store(database)
        service = Service(store, SimBroker(store), worker_start=False)
        def forbidden():
            raise Blocked("PROVIDER_FORBIDDEN_DURING_ENROLLMENT")
        source = Source(service, run_id="PAUSED_ROUTE_ENROLLMENT", provider=forbidden)
        result = source.run_source_once(
            root/"data/live-observation/hilega-directional-v1/step-audit.jsonl"
        )
        g.need(result["status"]=="BASELINED_WAIT_NEXT_CONFIRMED_SIGNAL",
               "HISTORICAL_BASELINE_REQUIRED")
        return result["status"]
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def check(root, folder):
    plan, database = read_plan(root, folder)
    code_check(root)
    g.need(g.sha(root/".env")==BEFORE, "CURRENT_CONFIGURATION_NOT_PRE_ACTIVATION")
    g.configuration(root)
    workspace = g.workspace(database)
    return dict(status="PREPARATION_ACTIVATION_CHECKS_PASS",
                workspace=workspace, applied=False, production_execution_enabled=False)


def apply(root, folder, *, services_stopped=False, callback=None, checkpoint=lambda phase:None):
    g.need(services_stopped, "STOPPED_PROCESS_ATTESTATION_REQUIRED")
    root, folder = Path(root).resolve(), Path(folder)
    with g.deployment_lock(root):
        require_stopped(root)
        check(root, folder)
        plan, database = read_plan(root, folder)
        transaction = folder/"transaction"
        g.need(not transaction.exists(), "ACTIVATION_TRANSACTION_ALREADY_EXISTS")
        transaction.mkdir(mode=0o700)
        clone(database, transaction/"baseline.sqlite")
        baseline_hash = logical_hash(transaction/"baseline.sqlite")
        state = dict(
            model="HILEGA_ROUTE_ACTIVATION_TRANSACTION_V1",
            phase="BACKUP_COMPLETE", root=str(root), database=str(database),
            baseline_logical_hash=baseline_hash,
            env_mode=(root/".env").stat().st_mode & 0o777,
            production_execution_enabled=False,
        )
        g.journal(transaction, state)
        require_stopped(root)
        g.need(logical_hash(database)==baseline_hash, "DATABASE_CHANGED_AFTER_BACKUP")
        state["phase"]="ENROLLING"
        g.journal(transaction, state)
        (callback or enroll)(root, database, plan["planned_configuration_changes"])
        post_check(database)
        state["post_enrollment_logical_hash"]=logical_hash(database)
        state["phase"]="ENROLLED_DATABASE"
        g.journal(transaction, state)
        checkpoint("ENROLLED_DATABASE")
        require_stopped(root)
        g.need(g.sha(root/".env")==BEFORE, "CONFIGURATION_CHANGED_DURING_ACTIVATION")
        g.atomic_bytes(root/".env", (folder/"candidate.env").read_bytes(), state["env_mode"])
        state["phase"]="ENROLLED_SERVICES_STILL_STOPPED"
        g.journal(transaction, state)
        return dict(status=state["phase"], transaction=str(transaction),
                    controller_mode="PAUSED", historical_entries_replayed=False,
                    services_started=False, production_execution_enabled=False)


def rollback(root, folder, *, services_stopped=False):
    g.need(services_stopped, "STOPPED_PROCESS_ATTESTATION_REQUIRED")
    root, folder = Path(root).resolve(), Path(folder)
    with g.deployment_lock(root):
        require_stopped(root)
        _, database = read_plan(root, folder)
        transaction = folder/"transaction"
        state = g.read_json(transaction/"deployment.json")
        g.need(state.get("model")=="HILEGA_ROUTE_ACTIVATION_TRANSACTION_V1"
               and state.get("root")==str(root)
               and state.get("database")==str(database), "RECOVERY_SCOPE_INVALID")
        baseline = transaction/"baseline.sqlite"
        g.need(logical_hash(baseline)==state["baseline_logical_hash"],
               "RECOVERY_BASELINE_CHANGED")
        known = {state["baseline_logical_hash"]}
        if state.get("post_enrollment_logical_hash"):
            known.add(state["post_enrollment_logical_hash"])
        g.need(logical_hash(database) in known,
               "DATABASE_CHANGED_MANUAL_RECOVERY_REVIEW_REQUIRED")
        g.need(g.sha(root/".env") in {BEFORE,CANDIDATE},
               "CONFIGURATION_CHANGED_MANUAL_RECOVERY_REQUIRED")
        state["phase"]="RECOVERING"
        g.journal(transaction, state)
        require_stopped(root)
        clone(baseline, database)
        g.need(logical_hash(database)==state["baseline_logical_hash"],
               "DATABASE_RECOVERY_MISMATCH")
        g.atomic_bytes(root/".env", (folder/"before.env").read_bytes(), state["env_mode"])
        state["phase"]="ROLLED_BACK_SERVICES_STILL_STOPPED"
        g.journal(transaction, state)
        return dict(status=state["phase"], services_started=False,
                    production_execution_enabled=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", nargs="?", choices=["check","apply","rollback"], default="check")
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--services-stopped", action="store_true")
    p.add_argument("--confirmation")
    a = p.parse_args()
    os.umask(0o077)
    try:
        if a.action=="check":
            result=check(a.root,a.plan)
        else:
            required="ENROLL_PREPARATION_ONLY" if a.action=="apply" else "RESTORE_PRE_ENROLLMENT_STATE"
            g.need(a.confirmation==required, "EXPLICIT_ACTIVATION_ACTION_REQUIRED")
            result=(apply if a.action=="apply" else rollback)(
                a.root,a.plan,services_stopped=a.services_stopped)
        print(json.dumps(result,indent=2))
        return 0
    except Exception as exc:
        print(json.dumps(dict(status="BLOCKED",
            reason=str(exc) if isinstance(exc,Blocked) else type(exc).__name__,
            services_started=False,production_execution_enabled=False)))
        return 1


if __name__=="__main__":
    raise SystemExit(main())
'''

tests = r'''"""Temporary configuration/SQLite only; source enrollment is an injected stub."""
import json
from pathlib import Path
import sqlite3

from dotenv import set_key
import pytest
import activate as a


@pytest.fixture
def env(tmp_path,monkeypatch):
    root=tmp_path/"repo"
    root.mkdir()
    folder=root/"backups"/"plan"
    folder.mkdir(parents=True,mode=0o700)
    database=root/"data/research/hilega-production-workspace/sim.sqlite"
    database.parent.mkdir(parents=True)
    before="HILEGA_PRODUCTION_EXECUTION_ROUTE=SIMULATOR\nHILEGA_PRODUCTION_WORKSPACE_MODE=SIMULATION_ONLY\n"
    (root/".env").write_text(before)
    (folder/"before.env").write_text(before)
    (folder/"candidate.env").write_text(before)
    changes=dict(
        HILEGA_PRODUCTION_EXECUTION_ROUTE="PREPARATION_ONLY",
        HILEGA_PRODUCTION_WORKSPACE_MODE="SIMULATION_ONLY",
        HILEGA_PRODUCTION_SIM_DB=str(database),
        HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED="1",
        HILEGA_PREPARATION_CAPTURE_ON_SIGNAL="1",
    )
    for k,v in changes.items():
        set_key(str(folder/"candidate.env"),k,v)
    monkeypatch.setattr(a,"BEFORE",a.g.sha(folder/"before.env"))
    monkeypatch.setattr(a,"CANDIDATE",a.g.sha(folder/"candidate.env"))
    for k in ("HILEGA_PRODUCTION_EXECUTION_ROUTE","HILEGA_PRODUCTION_WORKSPACE_MODE"):
        monkeypatch.delenv(k,raising=False)
    monkeypatch.setattr(a,"code_check",lambda root:None)
    monkeypatch.setattr(a,"require_stopped",lambda root:None)
    with sqlite3.connect(database) as db:
        db.executescript(
            "CREATE TABLE control(id INTEGER PRIMARY KEY,data TEXT);"
            "CREATE TABLE sim_stop_state(id INTEGER PRIMARY KEY,generation INTEGER,handled INTEGER);"
            "INSERT INTO sim_stop_state VALUES(1,0,0);"
        )
        db.execute("INSERT INTO control VALUES(1,?)",(json.dumps({"mode":"PAUSED"}),))
        for t in ("intents","sim_orders","sim_fills","sim_allocation_reservations"):
            db.execute("CREATE TABLE "+t+"(id TEXT)")
    plan=dict(model="HILEGA_PREPARATION_ACTIVATION_PLAN_V1",root=str(root),
        database=str(database),original_env_sha256=a.BEFORE,
        candidate_env_sha256=a.CANDIDATE,planned_configuration_changes=changes)
    (folder/"activation-plan.json").write_text(json.dumps(plan))
    return root,folder,database


def enroll(root,database,changes):
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE preparation_route(id INTEGER PRIMARY KEY,data TEXT)")
        db.execute("INSERT INTO preparation_route VALUES(1,?)",(json.dumps(
            {"route":"PREPARATION_ONLY","model":"APPLICATION_PREPARATION_ROUTE_V1"}),))
    return "BASELINED_WAIT_NEXT_CONFIRMED_SIGNAL"


def apply(env,**kwargs):
    return a.apply(env[0],env[1],services_stopped=True,callback=enroll,**kwargs)


def test_check_is_readonly(env):
    before=a.logical_hash(env[2])
    config=(env[0]/".env").read_bytes()
    assert a.check(env[0],env[1])["applied"] is False
    assert a.logical_hash(env[2])==before
    assert (env[0]/".env").read_bytes()==config
    assert not (env[1]/"transaction").exists()


def test_enrollment_and_exact_recovery(env):
    before=a.logical_hash(env[2])
    config=(env[0]/".env").read_bytes()
    assert apply(env)["status"]=="ENROLLED_SERVICES_STILL_STOPPED"
    a.post_check(env[2])
    a.rollback(env[0],env[1],services_stopped=True)
    assert a.logical_hash(env[2])==before
    assert (env[0]/".env").read_bytes()==config
    a.rollback(env[0],env[1],services_stopped=True)


def test_later_database_activity_blocks_recovery(env):
    apply(env)
    with sqlite3.connect(env[2]) as db:
        db.execute("CREATE TABLE later_activity(id INTEGER)")
        db.execute("INSERT INTO later_activity VALUES(1)")
    before=a.logical_hash(env[2])
    with pytest.raises(a.Blocked,match="DATABASE_CHANGED"):
        a.rollback(env[0],env[1],services_stopped=True)
    assert a.logical_hash(env[2])==before


def test_later_configuration_edit_blocks_recovery(env):
    apply(env)
    with (env[0]/".env").open("a") as stream:
        stream.write("LATER_OPERATOR_EDIT=1\n")
    with pytest.raises(a.Blocked,match="CONFIGURATION_CHANGED"):
        a.rollback(env[0],env[1],services_stopped=True)


def test_known_post_enrollment_interruption_can_recover(env):
    before=a.logical_hash(env[2])
    def crash(phase):
        raise RuntimeError("synthetic interruption")
    with pytest.raises(RuntimeError):
        apply(env,checkpoint=crash)
    a.rollback(env[0],env[1],services_stopped=True)
    assert a.logical_hash(env[2])==before


def test_unknown_partial_enrollment_requires_review(env):
    def partial(root,database,changes):
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE partial_enrollment(id INTEGER)")
        raise RuntimeError("synthetic interruption")
    with pytest.raises(RuntimeError):
        a.apply(env[0],env[1],services_stopped=True,callback=partial)
    with pytest.raises(a.Blocked,match="DATABASE_CHANGED"):
        a.rollback(env[0],env[1],services_stopped=True)


def test_running_process_blocks_before_transaction(env,monkeypatch):
    def running(root):
        raise a.Blocked("STILL_RUNNING")
    monkeypatch.setattr(a,"require_stopped",running)
    with pytest.raises(a.Blocked,match="STILL_RUNNING"):
        apply(env)
    assert not (env[1]/"transaction").exists()


def test_candidate_tampering_blocks_before_transaction(env):
    with (env[1]/"candidate.env").open("a") as stream:
        stream.write("CHANGED=1\n")
    with pytest.raises(a.Blocked,match="CONFIGURATION_CHANGED"):
        apply(env)
    assert not (env[1]/"transaction").exists()
'''

ast.parse(module)
ast.parse(tests)
folder.mkdir(mode=0o700)
(folder/"activate.py").write_text(module)
(folder/"test_activate.py").write_text(tests)
print("Created:", folder)
print("Syntax checked. Tests not executed. No activation performed.")
PY