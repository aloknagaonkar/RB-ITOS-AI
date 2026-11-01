import json
import os
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_hilega_application_preparation_v1 import env, process, counts, append, BULL
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_execution_port_v1.adapter import Store, Adapter, HttpTransport
from market_lab.hilega_preparation_runtime_v1.source import Source
from market_lab.hilega_preparation_runtime_v1.evidence import Blocked
from market_lab.hilega_production_foundation.core import (
    Store as ApplicationStore, SimBroker, Service,
)


@pytest.fixture
def bound_env(env, monkeypatch):
    path = Path(os.environ["HILEGA_PREPARATION_ADAPTER_DB"])
    path.unlink()  # Only the minimal temporary fixture DB, before processing.
    env["adapter_store"] = Store(path, PIN["scope"], "LIVE_CLOSED")
    monkeypatch.setenv("HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED", "1")
    return env


def requests(env):
    return env["adapter_store"].requests()


def binding_count(env):
    with env["store"].db() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='preparation_request_bindings'"
        ).fetchone()
        return db.execute(
            "SELECT COUNT(*) FROM preparation_request_bindings"
        ).fetchone()[0] if exists else 0


def test_signal_atomically_binds_hold_and_disabled_request(bound_env):
    env = bound_env
    process(env)
    assert counts(env) == (1, 1, 1, 0, 0, 0)
    assert binding_count(env) == 1
    row, = requests(env)
    with env["store"].db() as db:
        hold = json.loads(db.execute(
            "SELECT data FROM preparation_shadow_holds"
        ).fetchone()[0])
        binding = json.loads(db.execute(
            "SELECT data FROM preparation_request_bindings"
        ).fetchone()[0])
    assert row["request_id"] == row["reservation_reference"] == hold["id"]
    assert row["state"] == "PREPARED" and row["order_id"] is None
    assert row["reservation_verified"] is False
    assert hold["held_cents"] == binding["held_cents"] == 660000
    assert binding["held_cents"] <= binding["cash_cap_cents"]
    assert binding["local_budget_reference_bound"] is True
    assert binding["real_funds_reservation_verified"] is False
    assert binding["reservation_release_permission"] is False
    assert env["store"].control()["mode"] == "PAUSED"
    adapter = Adapter(
        env["adapter_store"],
        HttpTransport(lambda: pytest.fail("Token must not be accessed")),
    )
    assert adapter.submit(row["request_id"])["status"] == (
        "PRODUCTION_MUTATIONS_CLOSED_IN_CODE"
    )
    assert adapter.status()["attempts"] == []


@pytest.mark.parametrize("point", [
    "AFTER_PLAN_INSERT", "AFTER_ADAPTER_REQUEST_INSERT", "BEFORE_COMMIT",
])
def test_interruption_rolls_back_both_databases(bound_env, point):
    env = bound_env
    class Interrupted(BaseException):
        pass
    def stop(at):
        if at == point:
            raise Interrupted()
    env["source"].checkpoint = stop
    with pytest.raises(Interrupted):
        process(env)
    assert counts(env) == (0, 0, 0, 0, 0, 0)
    assert requests(env) == []
    assert binding_count(env) == 0
    with env["adapter_store"].tx() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_lost_commit_response_restart_does_not_duplicate(bound_env):
    env = bound_env
    class Lost(BaseException):
        pass
    def stop(at):
        if at == "AFTER_COMMIT":
            raise Lost()
    env["source"].checkpoint = stop
    with pytest.raises(Lost):
        process(env)
    original = requests(env)
    store = ApplicationStore(env["store"].path)
    service = Service(store, SimBroker(store), lambda: env["clock"][0])
    def no_provider():
        pytest.fail("Committed signal must not collect evidence again")
    restarted = Source(service, run_id="synthetic-lease", provider=no_provider)
    restarted.run_source_once(env["path"])
    assert requests(env) == original
    assert binding_count(env) == 1
    assert counts(env) == (1, 1, 1, 0, 0, 0)
    assert store.control()["mode"] == "PAUSED"


def test_two_sources_create_one_request_and_hold(bound_env):
    env = bound_env
    append(env["path"], [BULL])
    second = Source(
        env["s"], run_id="synthetic-lease", provider=env["provider"],
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(
            lambda source: source.run_source_once(env["path"]),
            [env["source"], second],
        ))
    assert len(requests(env)) == binding_count(env) == 1
    assert counts(env) == (1, 1, 1, 0, 0, 0)


@pytest.mark.parametrize("which", ["application", "adapter"])
def test_wal_is_rejected_without_changing_journal_mode(bound_env, which):
    env = bound_env
    path = (
        env["store"].path if which == "application"
        else env["adapter_store"].path
    )
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    with pytest.raises(Blocked, match="DELETE_JOURNAL_REQUIRED"):
        process(env)
    assert counts(env) == (0, 0, 0, 0, 0, 0)
    assert requests(env) == []
    assert env["store"].control()["mode"] == "PAUSED"
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
