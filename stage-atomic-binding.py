import ast
import copy
import hashlib
import json
from pathlib import Path
import shutil

repo = Path.cwd().resolve()
base = Path.home() / "hilega-auto-limit-stage-v1"
stage = Path.home() / "hilega-atomic-binding-stage-v1"
package = repo / "hilega-auto-limit-release-v1"

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
    == "13f052acf497ca10ac4b1f3a289f6ede36559b37e273a5143c5a15ebf6773665",
    "release manifest changed",
)
release = json.loads((package / "manifest.json").read_text())
for name in release["runtime_files"]:
    need(sha(repo / name) == release["files"][name],
         "deployed runtime changed: " + name)
    need(sha(base / name) == release["files"][name],
         "validated base stage changed: " + name)

adapter_rel = Path("backend/market_lab/hilega_execution_port_v1/adapter.py")
need(
    sha(repo / adapter_rel) == release["dependencies"][str(adapter_rel)],
    "adapter changed since validated release",
)
need(
    sha(base / adapter_rel) == sha(repo / adapter_rel),
    "base adapter differs from installed adapter",
)

# Share the existing request validation instead of duplicating it.
tree = ast.parse((repo / adapter_rel).read_text())
need(not any(
    isinstance(n, ast.FunctionDef) and n.name == "validated_request"
    for n in tree.body
), "request helper already exists")
classes = [
    n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Adapter"
]
need(len(classes) == 1, "Adapter class missing")
cls = classes[0]
methods = [
    n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "prepare"
]
need(len(methods) == 1, "prepare method missing")
method = methods[0]
positions = [
    i for i, n in enumerate(method.body) if isinstance(n, ast.With)
]
need(len(positions) == 1, "prepare transaction structure changed")
boundary = positions[0]
helper = copy.deepcopy(method)
helper.name = "validated_request"
helper.args.args = helper.args.args[1:]
helper.body = copy.deepcopy(method.body[:boundary]) + [
    ast.Return(value=ast.Tuple(
        elts=[ast.Name(id="row", ctx=ast.Load()),
              ast.Name(id="fp", ctx=ast.Load())],
        ctx=ast.Load(),
    ))
]
method.body[:boundary] = ast.parse('''
row, fp = validated_request(
    draft, signal_id=signal_id, signal_at=signal_at,
    direction=direction, reservation_reference=reservation_reference,
    as_of=as_of,
)
''').body
tree.body.insert(tree.body.index(cls), helper)
ast.fix_missing_locations(tree)
adapter_text = ast.unparse(tree) + "\n"

binding_rel = Path(
    "backend/market_lab/hilega_preparation_runtime_v1/atomic_binding.py"
)
binding_text = r'''"""Atomic disabled request/hold references; no execution or release authority."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re

from .evidence import FLAGS, digest, need, readonly
from .limit_candidate import build_candidate, fresh_plan
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE
from market_lab.hilega_execution_port_v1.adapter import (
    validated_request, encode,
)


def enabled():
    value = os.getenv("HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED", "0")
    need(value in {"0", "1"}, "ATOMIC_BINDING_MODE_INVALID")
    return value == "1"


class AdapterReader:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, parameters=()):
        need(sql.lstrip().startswith("SELECT"), "ADAPTER_READER_SELECT_ONLY")
        translated, count = re.subn(
            r"\bFROM\s+(meta|requests|attempts|receipts)\b",
            lambda match: "FROM broker." + match.group(1),
            sql,
        )
        need(count == 1, "ADAPTER_READER_QUERY_UNSUPPORTED")
        return self.db.execute(translated, parameters)


@contextmanager
def source_transaction(store, adapter_path):
    if not enabled():
        with readonly(adapter_path) as adapter, store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            yield adapter, db
        return

    path = Path(adapter_path)
    need(path.is_file() and not path.is_symlink(),
         "REGULAR_EXISTING_ADAPTER_REQUIRED")
    need(store.path.is_file() and not store.path.is_symlink(),
         "REGULAR_APPLICATION_DATABASE_REQUIRED")
    need(not path.samefile(store.path), "DISTINCT_DATABASES_REQUIRED")
    need(path.stat().st_dev == store.path.stat().st_dev,
         "SAME_FILESYSTEM_REQUIRED")

    with store.db() as db:
        need(not db.in_transaction, "UNEXPECTED_EXISTING_TRANSACTION")
        need(db.execute("PRAGMA main.journal_mode").fetchone()[0] == "delete",
             "APPLICATION_DELETE_JOURNAL_REQUIRED")
        db.execute("ATTACH DATABASE ? AS broker", (str(path.resolve()),))
        need(db.execute("PRAGMA broker.journal_mode").fetchone()[0] == "delete",
             "ADAPTER_DELETE_JOURNAL_REQUIRED")
        for schema in ("main", "broker"):
            db.execute("PRAGMA " + schema + ".synchronous=FULL")
            need(db.execute(
                "PRAGMA " + schema + ".synchronous"
            ).fetchone()[0] >= 2, "FULL_DURABILITY_REQUIRED")
        db.execute("BEGIN IMMEDIATE")
        yield AdapterReader(db), db
        # Store.db commits or rolls back the entire attached transaction.


def bind_disabled_request(db, plan, hold, outbox, bundle, pin, *, now):
    if not enabled():
        return False
    need(
        json.loads(db.execute(
            "SELECT data FROM broker.meta WHERE id=1"
        ).fetchone()[0]) == {"scope": pin["scope"], "mode": "LIVE_CLOSED"},
        "BOUND_ADAPTER_SCOPE_MISMATCH",
    )
    candidate = outbox["disabled_request_candidate"]
    expected = build_candidate(
        plan, hold, outbox, bundle, pin, now=now,
        session_date=plan["signal_at"][:10],
        fee_buffer_cents=candidate["fee_buffer_cents"], profile=PROFILE,
    )
    need(candidate == expected, "DISABLED_CANDIDATE_CHANGED")
    current = fresh_plan(bundle, pin, plan["direction"], now, PROFILE)

    total = 0
    for key, raw in db.execute(
        "SELECT id,data FROM preparation_shadow_holds"
    ):
        existing = json.loads(raw)
        owner = db.execute(
            "SELECT data FROM preparation_plans WHERE id=?", (key,),
        ).fetchone()
        need(owner is not None
             and json.loads(owner[0])["account_scope"] == pin["scope"],
             "UNKNOWN_HOLD_OWNER")
        amount = existing["held_cents"]
        need(type(amount) is int and amount > 0, "INVALID_HELD_AMOUNT")
        total += amount
    need(
        total <= current["half_cash_cap_cents"]
        and candidate["budget_cents"] <= hold["held_cents"],
        "TOTAL_HOLDS_EXCEED_CASH_CAP",
    )

    row, fingerprint = validated_request(
        candidate["draft"],
        signal_id=plan["id"], signal_at=plan["signal_at"],
        direction=plan["direction"],
        reservation_reference=hold["id"], as_of=now.isoformat(),
    )
    need(row["request_id"] == plan["id"] == hold["id"] == outbox["id"],
         "REQUEST_HOLD_ID_MISMATCH")
    need(row["draft"]["body"]["transaction_type"] == "BUY"
         and row["draft"]["body"]["quantity"] == plan["quantity"]
         and row["draft"]["body"]["instrument_token"] == plan["instrument"],
         "REQUEST_HOLD_CONTRACT_MISMATCH")
    need(not db.execute("SELECT 1 FROM broker.requests LIMIT 1").fetchone()
         and not db.execute("SELECT 1 FROM broker.attempts LIMIT 1").fetchone()
         and not db.execute("SELECT 1 FROM broker.receipts LIMIT 1").fetchone(),
         "EXISTING_ADAPTER_ACTIVITY_REQUIRES_REVIEW")

    db.execute(
        "CREATE TABLE IF NOT EXISTS preparation_request_bindings("
        "id TEXT PRIMARY KEY,data TEXT NOT NULL)"
    )
    db.execute(
        "INSERT INTO broker.requests VALUES(?,?,?)",
        (row["request_id"], fingerprint, encode(row)),
    )
    db.execute(
        "INSERT INTO broker.events(data) VALUES(?)",
        (encode(dict(
            type="REQUEST_PREPARED", request_id=row["request_id"],
            body_fingerprint=row["draft"]["fingerprint"],
            origin="APPLICATION_ATOMIC_DISABLED_BINDING",
        )),),
    )
    binding = dict(
        FLAGS,
        model="HILEGA_ATOMIC_DISABLED_REQUEST_BINDING_V1",
        id=plan["id"], account_scope=pin["scope"],
        request_fingerprint=fingerprint,
        plan_fingerprint=digest(plan),
        hold_fingerprint=digest(hold),
        outbox_fingerprint=digest(outbox),
        held_cents=hold["held_cents"],
        cash_cap_cents=current["half_cash_cap_cents"],
        bundle_fingerprint=digest(bundle),
        local_budget_reference_bound=True,
        broker_cash_locked=False,
        status="PREPARED_DISABLED_HOLD_RETAINED",
    )
    db.execute(
        "INSERT INTO preparation_request_bindings VALUES(?,?)",
        (plan["id"], encode(binding)),
    )
    return True
'''

source_rel = binding_rel.with_name("source.py")
source_text = (repo / source_rel).read_text()
changes = [
    (
        "from .limit_candidate import build_candidate, fresh_plan\n",
        "from .limit_candidate import build_candidate, fresh_plan\n"
        "from .atomic_binding import source_transaction, bind_disabled_request\n",
    ),
    (
        "            with readonly(adapter_path) as adapter,self.s.store.db() as db:\n"
        "                db.execute('BEGIN IMMEDIATE')",
        "            with source_transaction(self.s.store,adapter_path) as (adapter,db):",
    ),
    (
        "                db.execute('INSERT INTO preparation_outbox VALUES(?,?)',"
        "(event['id'],encode(outbox)))",
        "                db.execute('INSERT INTO preparation_outbox VALUES(?,?)',"
        "(event['id'],encode(outbox)))\n"
        "                if bind_disabled_request(db,bound,hold,outbox,bundle,pin,"
        "now=self.s.now()):\n"
        "                    self.checkpoint('AFTER_ADAPTER_REQUEST_INSERT')",
    ),
]
for old, new in changes:
    need(source_text.count(old) == 1, "source insertion point changed")
    source_text = source_text.replace(old, new, 1)

new_test_rel = Path("tests/test_hilega_atomic_disabled_binding_v1.py")
test_text = r'''import json
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
'''

written = {
    adapter_rel: adapter_text,
    binding_rel: binding_text,
    source_rel: source_text,
    new_test_rel: test_text,
}
for path, text in written.items():
    compile(text, str(path), "exec")

ignore = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".pytest_cache",
    "AUTO_LIMIT_REGRESSION-*.json", "isolated-workspace.sqlite*",
)
shutil.copytree(base, stage, ignore=ignore)
for path, text in written.items():
    (stage / path).write_text(text)

manifest = json.loads((base / "AUTO_LIMIT_STAGE.json").read_text())
manifest["model"] = "HILEGA_ATOMIC_DISABLED_BINDING_STAGE_V1"
manifest["status"] = "STAGED_NOT_DEPLOYED"
manifest["production_execution_enabled"] = False
manifest["tests"] = list(dict.fromkeys([
    str(new_test_rel), *manifest["tests"],
    "tests/test_hilega_consolidated_port_v1.py",
    "tests/test_hilega_multicycle_port_v1.py",
]))
tracked = set(manifest["files"]) | set(map(str, written)) | set(manifest["tests"])
manifest["files"] = {
    name: sha(stage / name) for name in sorted(tracked)
}
(stage / "ATOMIC_BINDING_STAGE.json").write_text(
    json.dumps(manifest, indent=2)
)
runner = (base / "run-tests.py").read_text()
runner = runner.replace(
    "AUTO_LIMIT_STAGE.json", "ATOMIC_BINDING_STAGE.json"
).replace("AUTO_LIMIT_REGRESSION-", "ATOMIC_BINDING_REGRESSION-")
compile(runner, "run-tests.py", "exec")
(stage / "run-tests.py").write_text(runner)

print(json.dumps({
    "status": "ATOMIC_DISABLED_BINDING_STAGED",
    "stage": str(stage),
    "syntax_checked": True,
    "tests_executed": False,
    "applied": False,
    "production_execution_enabled": False,
}, indent=2))