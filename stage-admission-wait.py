import hashlib
import json
from pathlib import Path
import shutil

repo = Path.cwd().resolve()
base = Path.home() / "hilega-atomic-binding-stage-v1"
stage = Path.home() / "hilega-admission-wait-stage-v1"
package = repo / "hilega-atomic-binding-release-v1"

def need(value, reason):
    if not value:
        raise SystemExit("STOP: " + reason)

def sha(path):
    need(path.is_file() and not path.is_symlink(),
         "regular file required: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()

need(not stage.exists() and not stage.is_symlink(), "fresh stage required")
need(
    sha(package / "manifest.json")
    == "ea563125ccf1bb8dbb02c26679cb7b254702a185679c8260a78529e6d2bde436",
    "release manifest changed",
)
release = json.loads((package / "manifest.json").read_text())
for name in release["runtime_files"]:
    need(sha(repo / name) == release["files"][name],
         "deployed runtime changed: " + name)
    need(sha(base / name) == release["files"][name],
         "base runtime differs from deployed release: " + name)

manifest = json.loads((base / "ATOMIC_BINDING_STAGE.json").read_text())
for name, expected in manifest["files"].items():
    need(sha(base / name) == expected, "validated base stage changed: " + name)

source_rel = Path(
    "backend/market_lab/hilega_preparation_runtime_v1/source.py"
)
text = (repo / source_rel).read_text()
anchor = "            current=self.s._session()\n"
need(text.count(anchor) == 1, "admission insertion point changed")
text = text.replace(anchor, anchor + '''
            # PREPARATION_ONLY reconciliation is a local baseline, not broker proof.
            # Refresh only an expired, valid same-session baseline while the
            # original Resume remains authoritative. Every evidence gate below
            # still runs against the fresh signal and signed account snapshot.
            checked_at=self.s.now()
            previous=current.get("last_reconciled_at")
            if (current["mode"]=="ARMED" and current["version"]==c["version"]
                    and current.get("reconciled") is True and previous
                    and day(aware(previous))==day(checked_at)
                    and (checked_at-aware(previous)).total_seconds()>30):
                if not self.s._reconcile():
                    self._record_result_unlocked(
                        event,cursor,["PREPARATION_LOCAL_BASELINE_REFRESH_FAILED"])
                    return
                current=self.s._session()
''', 1)

test_rel = Path("tests/test_hilega_preparation_wait_admission_v1.py")
tests = r'''import json
from datetime import datetime, timedelta

import pytest

from test_hilega_atomic_disabled_binding_v1 import (
    bound_env, requests, binding_count,
)
from test_hilega_application_preparation_v1 import append, BULL, counts, command
from hilega_application_preparation_fixtures import T, ts, resign_cash


def advance(env, *, fresh_health=True):
    data = env["data"]
    def shifted(value):
        return (datetime.fromisoformat(value) + timedelta(minutes=5)).isoformat()

    for name in ("started_at", "completed_at"):
        data[name] = shifted(data[name])
        data["cash_capture"][name] = shifted(data["cash_capture"][name])
    for quote in data["quotes"].values():
        for name in ("timestamp", "last_trade_time"):
            if name in quote:
                quote[name] = shifted(quote[name])
    resign_cash(data)
    env["clock"][0] = T + timedelta(seconds=303)
    if fresh_health:
        with env["store"].db() as db:
            health = json.loads(db.execute(
                "SELECT data FROM sim_bridge_health WHERE id=1"
            ).fetchone()[0])
            health.update(heartbeat_at=ts(302), source_at=ts(300))
            db.execute(
                "UPDATE sim_bridge_health SET data=? WHERE id=1",
                (json.dumps(health),),
            )


def signal(env):
    append(env["path"], [BULL], at=ts(300))
    return env["source"].run_source_once(env["path"])


def assert_blocked(env):
    assert counts(env) == (0, 0, 0, 0, 0, 0)
    assert requests(env) == []
    assert binding_count(env) == 0
    assert env["store"].control()["mode"] == "PAUSED"


def test_fresh_signal_after_five_minute_wait_can_prepare(bound_env):
    env = bound_env
    advance(env)
    original = env["store"].control()
    assert (
        env["clock"][0] - datetime.fromisoformat(original["last_reconciled_at"])
    ).total_seconds() > 30
    signal(env)
    assert counts(env) == (1, 1, 1, 0, 0, 0)
    assert len(requests(env)) == binding_count(env) == 1
    control = env["store"].control()
    assert control["mode"] == "PAUSED"
    assert control["resumed_at"] == original["resumed_at"]
    assert control["last_reconciled_at"] == ts(303)
    assert requests(env)[0]["state"] == "PREPARED"
    assert requests(env)[0]["order_id"] is None
    assert requests(env)[0]["reservation_verified"] is False


def test_wait_does_not_bypass_zero_cash(bound_env):
    env = bound_env
    advance(env)
    data = env["data"]
    for funds in (
        data["cash_before_market"], data["cash_after_market"],
        data["cash_capture"]["funds_before"],
        data["cash_capture"]["funds_after"],
    ):
        funds["cash_available_to_trade"] = "0"
    resign_cash(data)
    signal(env)
    assert_blocked(env)


def test_wait_does_not_bypass_stale_source_health(bound_env):
    env = bound_env
    advance(env, fresh_health=False)
    signal(env)
    assert_blocked(env)


def test_wait_does_not_bypass_stale_quotes(bound_env):
    env = bound_env
    advance(env)
    for quote in env["data"]["quotes"].values():
        quote["timestamp"] = ts()
    resign_cash(env["data"])
    signal(env)
    assert_blocked(env)


@pytest.mark.parametrize("case", ["future", "missing", "unreconciled"])
def test_invalid_baseline_is_not_automatically_repaired(bound_env, case):
    env = bound_env
    advance(env)
    with env["store"].db() as db:
        control = json.loads(db.execute(
            "SELECT data FROM control WHERE id=1"
        ).fetchone()[0])
        if case == "future":
            control["last_reconciled_at"] = ts(400)
        elif case == "missing":
            control["last_reconciled_at"] = None
        else:
            control["reconciled"] = False
        db.execute(
            "UPDATE control SET data=? WHERE id=1", (json.dumps(control),),
        )
    signal(env)
    assert_blocked(env)


def test_operator_pause_during_wait_prevents_admission(bound_env):
    env = bound_env
    advance(env)
    command(env["s"], "pause")
    calls = len(env["calls"])
    signal(env)
    assert_blocked(env)
    assert len(env["calls"]) == calls
'''

compile(text, str(source_rel), "exec")
compile(tests, str(test_rel), "exec")

shutil.copytree(
    base, stage,
    ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".pytest_cache",
        "*REGRESSION-*.json", "isolated-workspace.sqlite*",
    ),
)
(stage / source_rel).write_text(text)
(stage / test_rel).write_text(tests)

manifest["model"] = "HILEGA_PREPARATION_WAIT_ADMISSION_STAGE_V1"
manifest["status"] = "STAGED_NOT_DEPLOYED"
manifest["tests"] = [str(test_rel), *manifest["tests"]]
tracked = set(manifest["files"]) | {str(source_rel), str(test_rel)}
manifest["files"] = {
    name: sha(stage / name) for name in sorted(tracked)
}
(stage / "ADMISSION_WAIT_STAGE.json").write_text(
    json.dumps(manifest, indent=2)
)
runner = (base / "run-tests.py").read_text().replace(
    "ATOMIC_BINDING_STAGE.json", "ADMISSION_WAIT_STAGE.json"
).replace(
    "ATOMIC_BINDING_REGRESSION-", "ADMISSION_WAIT_REGRESSION-"
)
compile(runner, "run-tests.py", "exec")
(stage / "run-tests.py").write_text(runner)

print(json.dumps({
    "status": "PREPARATION_WAIT_ADMISSION_STAGED",
    "stage": str(stage),
    "syntax_checked": True,
    "tests_executed": False,
    "applied": False,
    "production_execution_enabled": False,
}, indent=2))