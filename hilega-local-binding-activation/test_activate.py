import hashlib
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
