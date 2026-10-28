import hashlib
from pathlib import Path

repo = Path.cwd().resolve()
source = repo / "create-atomic-binding-deployment.py"
target = repo / "create-admission-wait-deployment.py"

def need(value, reason):
    if not value:
        raise SystemExit("STOP: " + reason)

need(source.is_file() and not source.is_symlink(),
     "reviewed deployment builder missing")
need(not target.exists() and not target.is_symlink(),
     "admission deployment builder already exists")

raw = source.read_bytes()
blob = hashlib.sha1(
    b"blob " + str(len(raw)).encode() + b"\0" + raw
).hexdigest()
need(blob == "425a304245737364157886931584cf4340b22ce7",
     "deployment builder differs from reviewed version")

text = raw.decode()

# Reuse the established code-only deployment/recovery implementation.
replacements = [
    (
        "hilega-atomic-binding-deployment",
        "hilega-admission-wait-deployment",
    ),
    (
        "hilega-atomic-binding-release-v1",
        "hilega-admission-wait-release-v1",
    ),
    (
        "ea563125ccf1bb8dbb02c26679cb7b254702a185679c8260a78529e6d2bde436",
        "781000c45ab1a6a19f92c2d36a4ea4c5ebda0233cf61f8901fb76add8767783e",
    ),
    (
        "HILEGA_ATOMIC_DISABLED_BINDING_RELEASE_V1",
        "HILEGA_PREPARATION_WAIT_ADMISSION_RELEASE_V1",
    ),
    (
        "ATOMIC_PREPARATION_HOLD_TO_DISABLED_ADAPTER_REQUEST",
        "PREPARATION_LOCAL_BASELINE_REFRESH_ONLY",
    ),
    (
        "binding_activation_included",
        "configuration_change_included",
    ),
    (
        "hilega-atomic-binding-maintenance-",
        "hilega-admission-wait-maintenance-",
    ),
    (
        "HILEGA_ATOMIC_BINDING_MAINTENANCE_PLAN_V1",
        "HILEGA_ADMISSION_WAIT_MAINTENANCE_PLAN_V1",
    ),
    (
        '"AUTO_LIMIT", "ATOMIC_BINDING"',
        '"AUTO_LIMIT", "ADMISSION_WAIT"',
    ),
    (
        "ATOMIC_BINDING_DEPLOYMENT_TOOL_CREATED",
        "ADMISSION_WAIT_DEPLOYMENT_TOOL_CREATED",
    ),
    (
        "ATOMIC_RELEASE_IDENTITY_INVALID",
        "ADMISSION_RELEASE_IDENTITY_INVALID",
    ),
    (
        "BINDING_MODE_MUST_REMAIN_OFF",
        "BINDING_MODE_MUST_REMAIN_ON",
    ),
    (
        "binding mode must remain off",
        "binding mode must remain on",
    ),
    (
        "test_enabled_binding_mode_blocks_code_maintenance",
        "test_disabled_binding_mode_blocks_code_maintenance",
    ),
]
for old, new in replacements:
    need(old in text, "expected builder component missing: " + old)
    text = text.replace(old, new)

# The prior code-deployment checker requires mode OFF. Use the verified
# activation checker for this preparation's current enabled baseline.
old = '"previous_code_deployment", old_folder / "deploy.py",'
new = (
    '"previous_binding_activation", '
    'repo / "hilega-local-binding-activation/activate.py",'
)
need(text.count(old) == 1, "preflight loader changed")
text = text.replace(old, new, 1)

old = "spec.loader.exec_module(previous)"
need(text.count(old) == 1, "preflight helper insertion point changed")
text = text.replace(
    old,
    old + "\nprevious.managed = previous.legacy.managed",
    1,
)
old = 'previous.check()["status"] == "AUTO_LIMIT_ALREADY_APPLIED"'
need(text.count(old) == 1, "previous-state check changed")
text = text.replace(
    old,
    'previous.check()["status"] == "LOCAL_BINDING_CONFIGURATION_APPLIED"',
    1,
)

old = (
    '"HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED", "0"\n'
    '    ) == "0",'
)
need(text.count(old) == 1, "file binding-mode check changed")
text = text.replace(old, old.replace(') == "0"', ') == "1"'), 1)

for prefix in ("environment", "config"):
    old = (
        prefix
        + '.get("HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED", "0") == "0"'
    )
    need(text.count(old) == 1, "binding-mode guard changed: " + prefix)
    text = text.replace(old, old.replace('== "0"', '== "1"'), 1)

# Keep a meaningful negative test: mode OFF must now be rejected.
old = '"HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED=1\\n"'
need(text.count(old) == 1, "negative binding-mode test changed")
text = text.replace(
    old, '"HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED=0\\n"', 1,
)

# Existing deployment fixtures must represent the enabled baseline.
anchor = "ast.fix_missing_locations(test_tree)"
need(text.count(anchor) == 1, "test-fixture insertion point changed")
insertion = '''
fixture_envs = [
    node for node in ast.walk(test_tree)
    if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Attribute)
    and node.func.attr == "write_text"
    and node.args and isinstance(node.args[0], ast.Constant)
    and isinstance(node.args[0].value, str)
    and "HILEGA_PRODUCTION_WORKSPACE_MODE=SIMULATION_ONLY" in node.args[0].value
]
need(len(fixture_envs) == 1, "expected one baseline environment fixture")
fixture_envs[0].args[0].value += (
    "HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED=1\\n"
)
'''
text = text.replace(anchor, insertion + "\n" + anchor, 1)

compile(text, str(target), "exec")
with target.open("x") as stream:
    stream.write(text)

print("Created:", target, flush=True)
# Execute the reviewed adaptation: preparation only, no process signalling.
exec(compile(text, str(target), "exec"), {
    "__name__": "__main__",
    "__file__": str(target),
})