"""Temporary code trees and SQLite fixtures only; no real process signals."""
import json
from pathlib import Path
import sqlite3

import pytest
import deploy as d


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("HILEGA_PRODUCTION_EXECUTION_ROUTE", "HILEGA_PRODUCTION_WORKSPACE_MODE"):
        monkeypatch.delenv(name, raising=False)
    root, release, stage = (tmp_path/n for n in ("root", "release", "stage"))
    root.mkdir()
    old = {"backend/existing.py": "original\n", "backend/already.py": "same\n"}
    payload = {
        "backend/existing.py": "replacement\n",
        "backend/already.py": "same\n",
        "backend/new.py": "new\n",
    }
    for name, value in old.items():
        write(root/name, value)
    for name, value in payload.items():
        write(release/"files"/name, value)
        write(stage/name, value)
    write(root/"helper.py", "helper\n")
    write(stage/"helper.py", "helper\n")
    files = {n: d.sha(release/"files"/n) for n in payload}
    before = {n: d.sha(root/n) if (root/n).exists() else None for n in payload}
    deps = {"helper.py": d.sha(root/"helper.py")}
    report = release/"validation"/"PRICING_PREVIEW_REGRESSION_V1.json"
    write(report, json.dumps(dict(
        model="HILEGA_PRICING_PREVIEW_REGRESSION_V1",
        status="PASS", returncode=0, files={**deps, **files},
        applied=False, production_execution_enabled=False,
    )))
    manifest = dict(
        model="HILEGA_PRICING_PREVIEW_RELEASE_V1",
        scope="CODE_ONLY_NON_EXECUTABLE_PRICING_PREVIEW",
        runtime_files=list(payload), test_files=[],
        files=files, expected_target_hashes=before,
        unchanged_dependencies=deps,
        validation={"regression_report_sha256": d.sha(report)},
        applied=False, route_activation_included=False,
        production_execution_enabled=False,
    )
    write(release/"manifest.json", json.dumps(manifest))
    lock = tmp_path/"release.json"
    lock.write_bytes((release/"manifest.json").read_bytes())
    monkeypatch.setattr(d, "RELEASE_LOCK", lock)
    monkeypatch.setattr(d, "PINNED_MANIFEST", d.sha(lock))
    monkeypatch.setattr(d, "verify_units", lambda units: None)
    db = root/"workspace.sqlite"
    with sqlite3.connect(db) as c:
        c.executescript(
            "CREATE TABLE control(id INTEGER PRIMARY KEY,data TEXT);"
            "CREATE TABLE sim_stop_state(id INTEGER PRIMARY KEY,generation INTEGER,handled INTEGER);"
            "INSERT INTO sim_stop_state VALUES(1,0,0);"
        )
        c.execute("INSERT INTO control VALUES(1,?)", (json.dumps({"mode":"PAUSED"}),))
        for name in ("intents", "sim_orders", "sim_fills", "sim_allocation_reservations"):
            c.execute("CREATE TABLE "+name+"(id TEXT)")
    return dict(root=root, release=release, stage=stage, report=report,
                db=db, lock=lock, manifest=manifest)


def check(e):
    return d.check(e["root"], e["release"], e["stage"], e["report"], e["db"])


def apply(e, **kwargs):
    return d.apply(e["root"], e["release"], e["stage"], e["report"],
                   e["db"], ["fixture.service"], services_stopped=True, **kwargs)


def rollback(e, backup):
    return d.rollback(e["root"], backup, e["db"], ["fixture.service"],
                      services_stopped=True)


def test_readonly_check_allows_preexisting_identical_modules(env):
    before = {str(p): p.read_bytes() for p in env["root"].rglob("*") if p.is_file()}
    result = check(env)
    assert result["replaced_files"] == 1 and result["new_files"] == 1
    assert result["apply_ready"] is False
    assert before == {str(p): p.read_bytes() for p in env["root"].rglob("*") if p.is_file()}


def test_apply_and_rollback_preserve_db_and_preexisting_modules(env):
    db = env["db"].read_bytes()
    result = apply(env)
    assert check(env)["status"] == "ALREADY_DEPLOYED"
    assert env["db"].read_bytes() == db
    assert not (env["root"]/".env").exists()
    rollback(env, result["backup"])
    rollback(env, result["backup"])
    assert (env["root"]/"backend/existing.py").read_text() == "original\n"
    assert (env["root"]/"backend/already.py").read_text() == "same\n"
    assert not (env["root"]/"backend/new.py").exists()
    assert env["db"].read_bytes() == db


@pytest.mark.parametrize("which", ["payload", "stage", "report", "dependency", "target", "lock"])
def test_changed_inputs_block_before_backup(env, which):
    paths = dict(
        payload=env["release"]/"files/backend/existing.py",
        stage=env["stage"]/"backend/existing.py",
        report=env["report"], dependency=env["root"]/"helper.py",
        target=env["root"]/"backend/existing.py", lock=env["lock"],
    )
    p = paths[which]
    p.write_bytes(p.read_bytes()+b"\n")
    with pytest.raises(d.Blocked):
        apply(env)
    assert not (env["root"]/"backups").exists()


def test_partial_install_requires_recorded_recovery(env):
    (env["root"]/"backend/existing.py").write_text("replacement\n")
    with pytest.raises(d.Blocked, match="PARTIAL_OR_MIXED"):
        check(env)


def test_interrupted_apply_has_recoverable_journal(env):
    def crash(name):
        raise RuntimeError("synthetic interruption")
    with pytest.raises(RuntimeError):
        apply(env, checkpoint=crash)
    backup = next((env["root"]/"backups").iterdir())
    assert d.read_json(backup/"deployment.json")["phase"] == "INTERRUPTED_REQUIRES_ROLLBACK"
    rollback(env, backup)
    assert (env["root"]/"backend/existing.py").read_text() == "original\n"


def test_rollback_refuses_later_user_edits(env):
    result = apply(env)
    path = env["root"]/"backend/existing.py"
    path.write_text("later user edit\n")
    with pytest.raises(d.Blocked, match="POST_DEPLOYMENT_EDIT"):
        rollback(env, result["backup"])
    assert path.read_text() == "later user edit\n"
    assert (env["root"]/"backend/new.py").exists()


def test_rollback_refuses_corrupt_backup(env):
    result = apply(env)
    path = Path(result["backup"])/"original/backend/existing.py"
    path.write_text("corrupted\n")
    with pytest.raises(d.Blocked, match="BACKUP_CONTENT"):
        rollback(env, result["backup"])


def test_armed_workspace_blocks_apply(env):
    with sqlite3.connect(env["db"]) as c:
        c.execute("UPDATE control SET data=?", (json.dumps({"mode":"ARMED"}),))
    with pytest.raises(d.Blocked, match="WORKSPACE_MUST_BE_PAUSED"):
        apply(env)


def test_pid_guards_run_before_every_write(env, monkeypatch):
    import managed_processes
    calls = []
    monkeypatch.setattr(managed_processes, "require_stopped", lambda root: calls.append(root))
    d.apply(env["root"], env["release"], env["stage"], env["report"],
            env["db"], [], services_stopped=True, process_mode="pid-managed")
    assert len(calls) == 1+len(env["manifest"]["files"])


def test_running_process_blocks_before_backup(env, monkeypatch):
    import managed_processes
    def running(root):
        raise managed_processes.ManagedBlocked("STILL_RUNNING")
    monkeypatch.setattr(managed_processes, "require_stopped", running)
    with pytest.raises(d.Blocked, match="STILL_RUNNING"):
        d.apply(env["root"], env["release"], env["stage"], env["report"],
                env["db"], [], services_stopped=True, process_mode="pid-managed")
    assert not (env["root"]/"backups").exists()
