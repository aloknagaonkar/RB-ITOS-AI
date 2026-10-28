import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

os.umask(0o077)
repo = Path.cwd().resolve()
folder = repo / "hilega-atomic-binding-deployment"
package = repo / "hilega-atomic-binding-release-v1"
pinned = "ea563125ccf1bb8dbb02c26679cb7b254702a185679c8260a78529e6d2bde436"
old_folder = repo / "hilega-auto-limit-deployment"

def need(value, reason):
    if not value:
        raise SystemExit("STOP: " + reason)

def sha(path):
    need(path.is_file() and not path.is_symlink(),
         "regular file required: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()

need(not folder.exists() and not folder.is_symlink(),
     "deployment directory already exists")
need(sha(package / "manifest.json") == pinned, "release manifest changed")
release = json.loads((package / "manifest.json").read_text())
need(
    release["model"] == "HILEGA_ATOMIC_DISABLED_BINDING_RELEASE_V1"
    and release["binding_activation_included"] is False
    and release["production_execution_enabled"] is False,
    "unexpected release identity",
)
for name, expected in release["files"].items():
    need(sha(package / "files" / name) == expected, "packaged file changed")
for name, expected in release["target_baseline"].items():
    path = repo / name
    if expected is None:
        need(not path.exists() and not path.is_symlink(),
             "previously absent target exists: " + name)
    else:
        need(sha(path) == expected, "target changed: " + name)
for name, expected in release["dependencies"].items():
    need(sha(repo / name) == expected, "dependency changed: " + name)

spec = importlib.util.spec_from_file_location(
    "previous_code_deployment", old_folder / "deploy.py",
)
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
need(previous.check()["status"] == "AUTO_LIMIT_ALREADY_APPLIED",
     "previous deployed release is not verified")

result = subprocess.run(
    [sys.executable, "check-preparation-paused.py"],
    cwd=repo, capture_output=True, text=True,
    env={**os.environ, "PYTHONPATH": "backend:."},
)
need(result.returncode == 0, "run check-preparation-paused.py and share its output")
status = json.loads(result.stdout)
need(
    status["process_identities_match"] is True
    and status["controller_mode"] == "PAUSED"
    and status["execution_route"] == "PREPARATION_ONLY"
    and not any(status["activity_counts"].values())
    and status["journal_prefix_matches"] is True
    and status["journal_tail_remaining_records"] == 0,
    "paused application state requires review",
)

from dotenv import dotenv_values
need(
    dotenv_values(repo / ".env").get(
        "HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED", "0"
    ) == "0",
    "binding mode must remain off",
)
env_hash = sha(repo / ".env")
rows = previous.managed.inspect(repo)["active_processes"]
need(len(rows) == 3 and {row["role"] for row in rows} == {
    "api", "worker", "production-source-worker",
}, "expected exactly three application processes")
old_startup = json.loads((
    repo / "backups/hilega-auto-limit-maintenance-_mzrnlv9/startup-private.json"
).read_text())

def ticks(proc):
    return int(proc.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19])

startup = {}
for row in rows:
    role = row["role"]
    proc = Path("/proc") / str(row["pid"])
    need(ticks(proc) == row["start_ticks"], "process identity changed")
    args = [
        item.decode()
        for item in proc.joinpath("cmdline").read_bytes().split(b"\0") if item
    ]
    need(args == old_startup[role]["argv"]
         and proc.joinpath("cwd").resolve() == repo,
         "launcher or process directory changed")
    environment = dict(
        item.decode().split("=", 1)
        for item in proc.joinpath("environ").read_bytes().split(b"\0")
        if b"=" in item
    )
    need(environment.get("HILEGA_PRODUCTION_EXECUTION_ROUTE") == "PREPARATION_ONLY"
         and environment.get("HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED", "0") == "0",
         "unexpected process configuration")
    logs = []
    for number in (1, 2):
        path = proc.joinpath("fd", str(number)).readlink()
        need(path.is_absolute()
             and path.resolve().is_relative_to((repo / "data/logs").resolve()),
             "unexpected log destination")
        previous.guard.target(repo, str(path.relative_to(repo)))
        sha(path)
        logs.append(str(path))
    need(ticks(proc) == row["start_ticks"], "process changed during capture")
    startup[role] = dict(
        argv=args, env=environment, logs=logs,
        pid=row["pid"], start_ticks=row["start_ticks"],
    )

need(sha(repo / ".env") == env_hash, "environment changed")
need(previous.managed.inspect(repo)["active_processes"] == rows,
     "process inventory changed")

backup = Path(tempfile.mkdtemp(
    prefix="hilega-atomic-binding-maintenance-", dir=repo / "backups",
))
with (backup / "startup-private.json").open("x") as stream:
    json.dump(startup, stream, indent=2)
shutil.copyfile(repo / ".env", backup / "original.env")

metadata = [
    "data/runtime/api.json",
    "data/runtime/worker.json",
    "data/runtime/hilega-preparation-source.json",
    "backups/hilega-preparation-activation-cvtlkibq/maintenance.json",
]
for name in metadata:
    original = repo / name
    expected = sha(original)
    target = backup / "original-metadata" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(original, target)
    need(sha(target) == expected, "metadata backup mismatch")

plan = dict(
    model="HILEGA_ATOMIC_BINDING_MAINTENANCE_PLAN_V1",
    status="MAINTENANCE_PREPARED_NOT_APPLIED",
    root=str(repo), package=str(package), backup=str(backup),
    database=str(repo / "data/research/hilega-production-workspace/sim.sqlite"),
    manifest_sha256=pinned, env_sha256=env_hash,
    startup_sha256=sha(backup / "startup-private.json"),
    processes=rows, metadata_paths=metadata,
    stopped_database_backup_required=True,
    automatic_database_restore_allowed=False,
    guard_files={
        name: sha(repo / name) for name in (
            "check-preparation-paused.py",
            "hilega-production-application-deployment/deploy.py",
            "hilega-production-application-deployment/managed_processes.py",
            "scripts/hilega_production_simulator_bridge.py",
        )
    },
    binding_activation_included=False,
    applied=False, production_execution_enabled=False,
)
plan_path = backup / "plan.json"
plan_path.write_text(json.dumps(plan, indent=2))

# Adapt the tested code-only deployment tool to the new pinned release.
tool_text = (old_folder / "deploy.py").read_text()
for old, new in (
    (
        "13f052acf497ca10ac4b1f3a289f6ede36559b37e273a5143c5a15ebf6773665",
        pinned,
    ),
    (
        "5d352e4ec40848793a8497f301a6c06ea20642052859fd941a256bbf3387d227",
        sha(plan_path),
    ),
    (
        "backups/hilega-auto-limit-maintenance-_mzrnlv9/plan.json",
        str(plan_path.relative_to(repo)),
    ),
):
    need(tool_text.count(old) == 1, "deployment constant changed")
    tool_text = tool_text.replace(old, new, 1)

tool_text = tool_text.replace(
    "hilega-auto-limit-release-v1", "hilega-atomic-binding-release-v1"
).replace("AUTO_LIMIT", "ATOMIC_BINDING")
tree = ast.parse(tool_text)

payload_nodes = [
    node for node in tree.body
    if isinstance(node, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id == "PAYLOAD" for t in node.targets)
]
need(len(payload_nodes) == 1, "payload declaration changed")
payload_nodes[0].value = ast.Set(
    elts=[ast.Constant(name) for name in sorted(release["files"])]
)

functions = {
    node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
}
context = functions["context"]
config_positions = [
    i for i, node in enumerate(context.body)
    if isinstance(node, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id == "config" for t in node.targets)
]
need(len(config_positions) == 1, "configuration check structure changed")
context.body[config_positions[0] + 1:config_positions[0] + 1] = ast.parse('''
need(config.get("HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED", "0") == "0",
     "BINDING_MODE_MUST_REMAIN_OFF")
''').body

release_positions = [
    i for i, node in enumerate(context.body)
    if isinstance(node, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id == "release" for t in node.targets)
]
need(len(release_positions) == 1, "release check structure changed")
context.body[release_positions[0] + 1:release_positions[0] + 1] = ast.parse('''
need(release.get("model") == "HILEGA_ATOMIC_DISABLED_BINDING_RELEASE_V1"
     and release.get("scope") == "ATOMIC_PREPARATION_HOLD_TO_DISABLED_ADAPTER_REQUEST"
     and release.get("binding_activation_included") is False
     and release.get("production_execution_enabled") is False,
     "ATOMIC_RELEASE_IDENTITY_INVALID")
''').body

class BindingTableGuard(ast.NodeTransformer):
    def visit_Return(self, node):
        return ast.parse('''
exists = db.execute(
    "SELECT 1 FROM sqlite_master WHERE type='table' "
    "AND name='preparation_request_bindings'"
).fetchone()
if exists:
    need(db.execute(
        "SELECT COUNT(*) FROM preparation_request_bindings"
    ).fetchone()[0] == 0, "EXISTING_BINDING_REQUIRES_REVIEW")
''').body + [node]

BindingTableGuard().visit(functions["workspace"])
ast.fix_missing_locations(tree)
tool_text = ast.unparse(tree) + "\n"

test_text = (old_folder / "test_deploy.py").read_text().replace(
    "hilega-auto-limit-release-v1", "hilega-atomic-binding-release-v1"
).replace("AUTO_LIMIT", "ATOMIC_BINDING")
test_tree = ast.parse(test_text)
release_assignments = [
    node for node in ast.walk(test_tree)
    if isinstance(node, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id == "release" for t in node.targets)
]
need(len(release_assignments) == 1, "test release fixture changed")
call = release_assignments[0].value
need(isinstance(call, ast.Call), "test release fixture is not a constructor")
for name, value in {
    "model": "HILEGA_ATOMIC_DISABLED_BINDING_RELEASE_V1",
    "scope": "ATOMIC_PREPARATION_HOLD_TO_DISABLED_ADAPTER_REQUEST",
    "binding_activation_included": False,
    "production_execution_enabled": False,
}.items():
    call.keywords.append(ast.keyword(arg=name, value=ast.Constant(value)))
ast.fix_missing_locations(test_tree)
test_text = ast.unparse(test_tree) + "\n"
test_text += r'''

def test_enabled_binding_mode_blocks_code_maintenance(setup, monkeypatch):
    root = setup[0]
    path = root / ".env"
    path.write_text(path.read_text()
                    + "HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED=1\n")
    plan_path = root / tool.PLAN_REL
    plan = json.loads(plan_path.read_text())
    plan["env_sha256"] = sha(path)
    put(plan_path, plan)
    monkeypatch.setattr(tool, "PIN_PLAN", sha(plan_path))
    with pytest.raises(tool.Blocked, match="BINDING_MODE_MUST_REMAIN_OFF"):
        tool.apply()


@pytest.mark.parametrize("action", ["apply", "rollback"])
def test_existing_binding_blocks_maintenance(setup, action):
    if action == "rollback":
        tool.apply()
    with sqlite3.connect(setup[3]) as db:
        db.execute("CREATE TABLE preparation_request_bindings(id TEXT)")
        db.execute("INSERT INTO preparation_request_bindings VALUES('existing')")
    before = {name: tool.current(name) for name in tool.PAYLOAD}
    with pytest.raises(tool.Blocked, match="EXISTING_BINDING_REQUIRES_REVIEW"):
        getattr(tool, action)()
    assert {name: tool.current(name) for name in tool.PAYLOAD} == before


def test_empty_binding_table_is_preserved(setup):
    with sqlite3.connect(setup[3]) as db:
        db.execute("CREATE TABLE preparation_request_bindings(id TEXT)")
    original = setup[3].read_bytes()
    tool.apply()
    tool.rollback()
    assert setup[3].read_bytes() == original
'''

for name, text in (("deploy.py", tool_text), ("test_deploy.py", test_text)):
    compile(text, name, "exec")
folder.mkdir()
(folder / "deploy.py").write_text(tool_text)
(folder / "test_deploy.py").write_text(test_text)

print(json.dumps({
    "status": "ATOMIC_BINDING_DEPLOYMENT_TOOL_CREATED",
    "tool": str(folder),
    "backup": str(backup),
    "plan_sha256": sha(plan_path),
    "processes": rows,
    "syntax_checked": True,
    "tests_executed": False,
    "binding_activation_included": False,
    "processes_signalled": False,
    "applied": False,
    "production_execution_enabled": False,
}, indent=2))