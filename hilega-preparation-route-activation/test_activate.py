"""Temporary configuration/SQLite only; source enrollment is an injected stub."""
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
