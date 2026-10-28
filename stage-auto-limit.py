import ast
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys

repo = Path.cwd().resolve()
stage = (
    Path(sys.argv[1]).expanduser().resolve()
    if len(sys.argv) > 1
    else Path.home() / "hilega-auto-limit-stage-v1"
)
if stage.exists() or stage.is_symlink():
    raise SystemExit("STOP: fresh stage directory required")

source_rel = Path("backend/market_lab/hilega_preparation_runtime_v1/source.py")
limit_rel = source_rel.with_name("limit_candidate.py")
test_rel = Path("tests/test_hilega_limit_candidate_v1.py")
new_test_rel = Path("tests/test_hilega_auto_limit_wiring_v1.py")

raw = (repo / source_rel).read_bytes()
blob = hashlib.sha1(
    b"blob " + str(len(raw)).encode() + b"\0" + raw
).hexdigest()
if blob != "91e34719c092b266aa7c1f0cd150ee3118f30389":
    raise SystemExit("STOP: source differs from reviewed baseline")

tree = ast.parse((repo / limit_rel).read_text())
if any(
    isinstance(node, ast.FunctionDef) and node.name == "build_candidate"
    for node in tree.body
):
    raise SystemExit("STOP: candidate helper already exists")

functions = [
    node for node in tree.body
    if isinstance(node, ast.FunctionDef) and node.name == "stage"
]
if len(functions) != 1:
    raise SystemExit("STOP: expected one stage function")
function = functions[0]

transactions = [
    node for node in ast.walk(function)
    if isinstance(node, ast.With) and any(
        isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Name)
        and item.context_expr.func.id == "readonly"
        for item in node.items
    )
]
if len(transactions) != 1:
    raise SystemExit("STOP: expected one candidate transaction")
transaction = transactions[0]

def assigned(node, name):
    return isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == name
        for target in node.targets
    )

starts = [
    i for i, node in enumerate(transaction.body)
    if assigned(node, "now")
]
ends = [
    i for i, node in enumerate(transaction.body)
    if assigned(node, "candidate")
]
if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
    raise SystemExit("STOP: candidate construction boundaries changed")
first, last = starts[0], ends[0]

class SessionDate(ast.NodeTransformer):
    def visit_Subscript(self, node):
        if (
            isinstance(node.value, ast.Name)
            and node.value.id == "control"
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "session_date"
        ):
            return ast.copy_location(
                ast.Name(id="session_date", ctx=ast.Load()), node,
            )
        return self.generic_visit(node)

body = [
    SessionDate().visit(copy.deepcopy(node))
    for node in transaction.body[first + 1:last + 1]
]

helper = ast.parse('''
def build_candidate(plan, hold, out, bundle, pin, *, now,
                    session_date, fee_buffer_cents, profile):
    need(type(fee_buffer_cents) is int and fee_buffer_cents > 0,
         "EXPLICIT_POSITIVE_FEE_BUFFER_REQUIRED")
    plan_id = plan["id"]
    need(plan_id == hold["id"] == out["id"] == out["reservation_reference"],
         "CANDIDATE_REFERENCE_MISMATCH")
    need(plan["account_scope"] == pin["scope"],
         "CANDIDATE_ACCOUNT_SCOPE_MISMATCH")
    need(all(row.get(flag) is False
             for row in (plan, hold, out) for flag in FLAGS),
         "CANDIDATE_PERMISSION_FLAGS_CHANGED")
    need(hold["real_cash_reserved"] is False
         and hold["evidence_mode"] == "REAL_CASH_OBSERVED_SHADOW_ONLY",
         "SHADOW_HOLD_REQUIRED")
    need(out["request_body"] is None
         and out["status"] == "NON_EXECUTABLE_PRICING_POLICY_PENDING",
         "NON_EXECUTABLE_OUTBOX_REQUIRED")
    return None
''').body[0]
helper.body = helper.body[:-1] + body + [
    ast.Return(value=ast.Name(id="candidate", ctx=ast.Load()))
]

replacement = ast.parse('''
now = service.now()
candidate = build_candidate(
    plan, hold, out, bundle, pin, now=now,
    session_date=control["session_date"],
    fee_buffer_cents=fee_buffer_cents, profile=profile,
)
request_at = aware(candidate["draft"]["created_at"])
old = out.get("disabled_request_candidate")
''').body
transaction.body[first:last + 1] = replacement
tree.body.insert(tree.body.index(function), helper)
ast.fix_missing_locations(tree)
limit_text = ast.unparse(tree) + "\n"

source_text = raw.decode()
changes = [
    (
        "from .pricing_preview import preview as pricing_preview\n",
        "from .pricing_preview import preview as pricing_preview\n"
        "from .limit_candidate import build_candidate, fresh_plan\n",
    ),
    (
        "                old_bundle=db.execute(",
        '''                outbox["disabled_request_candidate"]=build_candidate(
                    bound,hold,outbox,bundle,pin,now=self.s.now(),
                    session_date=latest["session_date"],
                    fee_buffer_cents=10_000,profile=PROFILE)
                old_bundle=db.execute(''',
    ),
    (
        "                self._cursor(db,cursor);self.checkpoint('BEFORE_COMMIT')",
        '''                self._cursor(db,cursor);self.checkpoint('BEFORE_COMMIT')
                final_now=self.s.now()
                final=fresh_plan(bundle,pin,event["direction"],final_now,PROFILE)
                need(all(final[k]==plan[k] for k in (
                    "bundle_fingerprint","cash_capture_fingerprint",
                    "contract_fingerprint","quote_fingerprint",
                    "instrument","quantity","proposed_cost_cents")),
                    "CANDIDATE_EVIDENCE_CHANGED_BEFORE_COMMIT")
                request_at=aware(outbox["disabled_request_candidate"]["draft"]["created_at"])
                need(0<=(final_now-request_at).total_seconds()<=10,
                     "CANDIDATE_STALE_BEFORE_COMMIT")''',
    ),
]
for old, new in changes:
    if source_text.count(old) != 1:
        raise SystemExit("STOP: source insertion point changed")
    source_text = source_text.replace(old, new, 1)

test_text = (repo / test_rel).read_text()
old = 'assert first["idempotent_replay"] is False'
if test_text.count(old) != 1:
    raise SystemExit("STOP: expected duplicate test assertion missing")
test_text = test_text.replace(
    old,
    'assert first["idempotent_replay"] is True  # Source created it atomically.',
    1,
)

new_tests = r'''import json
from datetime import timedelta

import pytest

from test_hilega_application_preparation_v1 import env, process, counts
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1 import source as source_module
from market_lab.hilega_preparation_runtime_v1.evidence import Blocked
from market_lab.hilega_preparation_runtime_v1.limit_candidate import stage
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE
from market_lab.hilega_production_foundation.core import Store, SimBroker, Service
from market_lab.hilega_preparation_runtime_v1.source import Source


def outbox(env):
    with env["store"].db() as db:
        return json.loads(db.execute(
            "SELECT data FROM preparation_outbox"
        ).fetchone()[0])


def test_confirmed_signal_automatically_persists_disabled_candidate(env):
    process(env)
    assert counts(env) == (1, 1, 1, 0, 0, 0)
    row = outbox(env)
    candidate = row["disabled_request_candidate"]
    assert candidate["preparation_id"] == row["id"]
    assert candidate["reservation_reference"] == row["reservation_reference"]
    assert candidate["draft"]["body"]["order_type"] == "LIMIT"
    assert candidate["draft"]["body"]["quantity"] == 65
    assert candidate["draft"]["body"]["price"] == 100
    assert candidate["draft"]["submission_enabled"] is False
    assert candidate["policy_approved_for_production"] is False
    assert candidate["real_funds_reservation_verified"] is False
    assert candidate["production_execution_enabled"] is False
    assert row["request_body"] is None
    assert env["store"].control()["mode"] == "PAUSED"


@pytest.mark.parametrize("point", ["AFTER_PLAN_INSERT", "BEFORE_COMMIT"])
def test_interruption_rolls_back_plan_hold_outbox_and_candidate(env, point):
    class Interrupted(BaseException):
        pass

    def interrupt(at):
        if at == point:
            raise Interrupted()

    env["source"].checkpoint = interrupt
    with pytest.raises(Interrupted):
        process(env)
    assert counts(env) == (0, 0, 0, 0, 0, 0)
    with env["store"].db() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM preparation_evidence"
        ).fetchone()[0] == 0


def test_candidate_failure_rolls_back_and_pauses(env, monkeypatch):
    def fail(*args, **kwargs):
        raise Blocked("INJECTED_CANDIDATE_FAILURE")

    monkeypatch.setattr(source_module, "build_candidate", fail)
    with pytest.raises(Blocked, match="INJECTED_CANDIDATE_FAILURE"):
        process(env)
    assert counts(env) == (0, 0, 0, 0, 0, 0)
    assert env["store"].control()["mode"] == "PAUSED"
    calls = len(env["calls"])
    env["source"].run_source_once(env["path"])
    assert len(env["calls"]) == calls
    assert counts(env) == (0, 0, 0, 0, 0, 0)


def test_quote_expiry_at_final_commit_rolls_back_and_pauses(env):
    def delay(at):
        if at == "BEFORE_COMMIT":
            env["clock"][0] += timedelta(seconds=11)

    env["source"].checkpoint = delay
    with pytest.raises(Blocked):
        process(env)
    assert counts(env) == (0, 0, 0, 0, 0, 0)
    assert env["store"].control()["mode"] == "PAUSED"


def test_lost_commit_response_restart_preserves_exact_candidate(env):
    class LostResponse(BaseException):
        pass

    def lose(at):
        if at == "AFTER_COMMIT":
            raise LostResponse()

    env["source"].checkpoint = lose
    with pytest.raises(LostResponse):
        process(env)
    original = outbox(env)

    def no_provider():
        pytest.fail("Committed signal must not collect evidence again")

    store = Store(env["store"].path)
    service = Service(store, SimBroker(store), lambda: env["clock"][0])
    restarted = Source(
        service, run_id="synthetic-lease", provider=no_provider,
    )
    restarted.run_source_once(env["path"])
    assert outbox(env) == original
    assert counts(env) == (1, 1, 1, 0, 0, 0)
    assert store.control()["mode"] == "PAUSED"


def test_manual_stager_remains_compatible_with_original_unsent_rows(env):
    process(env)
    row = outbox(env)
    row.pop("disabled_request_candidate")
    with env["store"].db() as db:
        db.execute("UPDATE preparation_outbox SET data=?", (json.dumps(row),))
    result = stage(
        env["s"], row["id"], PIN,
        fee_buffer_cents=10000, profile=PROFILE,
    )
    assert result["idempotent_replay"] is False
    assert result["draft"]["submission_enabled"] is False
    assert counts(env) == (1, 1, 1, 0, 0, 0)
'''

written = {
    source_rel: source_text,
    limit_rel: limit_text,
    test_rel: test_text,
    new_test_rel: new_tests,
}
for path, content in written.items():
    compile(content, str(path), "exec")

dependencies = json.loads(
    (repo / source_rel.with_name("dependencies.json")).read_text()
)
ignore = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".pytest_cache", ".env", ".env.*",
)
stage.mkdir()
shutil.copytree(
    repo / "backend/market_lab", stage / "backend/market_lab", ignore=ignore,
)
shutil.copytree(repo / "tests", stage / "tests", ignore=ignore)
for directory in sorted({
    Path(path).parts[0] for path in dependencies
    if Path(path).parts[0] != "backend"
}):
    shutil.copytree(repo / directory, stage / directory, ignore=ignore)

for path, content in written.items():
    (stage / path).write_text(content)

suite = [
    str(new_test_rel),
    str(test_rel),
    "tests/test_hilega_application_preparation_v1.py",
    "tests/test_hilega_preparation_admission_v1.py",
    "tests/test_hilega_preparation_pricing_wiring_v1.py",
    "tests/test_hilega_preparation_reference_review_v1.py",
    "tests/test_hilega_preparation_pricing_preview_v1.py",
    "tests/test_hilega_nifty_option_price_grid_v1.py",
    "tests/test_hilega_consolidated_adapter_v1.py",
]
tracked = {
    *map(str, written),
    *suite,
    *dependencies,
    str(source_rel.with_name("dependencies.json")),
    "tests/hilega_application_preparation_fixtures.py",
}
manifest = dict(
    model="HILEGA_AUTO_LIMIT_CANDIDATE_STAGE_V1",
    status="STAGED_NOT_DEPLOYED",
    runtime_repository_modified=False,
    production_execution_enabled=False,
    tests=suite,
    files={
        name: hashlib.sha256((stage / name).read_bytes()).hexdigest()
        for name in sorted(tracked)
    },
)
(stage / "AUTO_LIMIT_STAGE.json").write_text(json.dumps(manifest, indent=2))

runner = r'''import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

root = Path(__file__).resolve().parent
manifest = json.loads((root / "AUTO_LIMIT_STAGE.json").read_text())

def verify():
    for name, expected in manifest["files"].items():
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise SystemExit("STOP: regular staged file required: " + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit("STOP: staged file changed: " + name)

verify()
env = {
    key: value for key, value in os.environ.items()
    if not key.startswith(("HILEGA_", "UPSTOX_"))
    and key not in {"DATABASE_URL", "SQLALCHEMY_DATABASE_URI", "SQLITE_BRIDGE_URL"}
}
env.update(
    PYTHONPATH="backend:.",
    HILEGA_PRODUCTION_WORKSPACE_MODE="SIMULATION_ONLY",
    HILEGA_PRODUCTION_EXECUTION_ROUTE="SIMULATOR",
    HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED="0",
    HILEGA_PRODUCTION_SIM_DB=str(root / "isolated-workspace.sqlite"),
)
result = subprocess.run(
    [sys.executable, "-m", "pytest", "-q", *manifest["tests"]],
    cwd=root, env=env,
)
verify()
report = root / (
    "AUTO_LIMIT_REGRESSION-"
    + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
)
value = dict(
    status="PASS" if result.returncode == 0 else "FAIL",
    pytest_exit_code=result.returncode,
    stage=str(root),
    applied=False,
    services_restarted=False,
    production_execution_enabled=False,
)
with report.open("x") as stream:
    json.dump(value, stream, indent=2)
print(json.dumps({**value, "report": str(report)}, indent=2))
raise SystemExit(result.returncode)
'''
compile(runner, "run-tests.py", "exec")
(stage / "run-tests.py").write_text(runner)

print("STAGED:", stage)
print("Syntax checked. Tests not executed.")
print("Running application unchanged. No activation performed.")