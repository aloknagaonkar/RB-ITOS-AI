import hashlib
import json
from pathlib import Path

repo = Path.cwd().resolve()
source = repo / "apply-auto-limit-maintenance.py"
target = repo / "apply-local-binding-activation.py"
backup = repo / "backups/hilega-binding-activation-5vaxo1ah"
plan_pin = "44bef25e2036ffa0aa104f5f5d2f74a7d93b14245efc1d998eb7728faaa5b05d"

def need(value, reason):
    if not value:
        raise SystemExit("STOP: " + reason)

need(source.is_file() and not source.is_symlink(),
     "previous maintenance wrapper missing")
need(not target.exists() and not target.is_symlink(),
     "activation wrapper already exists")
raw = source.read_bytes()
blob = hashlib.sha1(
    b"blob " + str(len(raw)).encode() + b"\0" + raw
).hexdigest()
need(blob == "cb6226838fc9823e047b2cc72e3a31ec5ed93cf4",
     "previous wrapper differs from reviewed version")

plan_path = backup / "activation-plan.json"
need(plan_path.is_file() and not plan_path.is_symlink(),
     "regular activation plan required")
need(hashlib.sha256(plan_path.read_bytes()).hexdigest() == plan_pin,
     "activation plan changed")

text = raw.decode()
replacements = [
    (
        "backups/hilega-auto-limit-maintenance-_mzrnlv9",
        "backups/hilega-binding-activation-5vaxo1ah",
    ),
    ('plan_path = backup / "plan.json"',
     'plan_path = backup / "activation-plan.json"'),
    (
        "hilega-auto-limit-deployment/deploy.py",
        "hilega-local-binding-activation/activate.py",
    ),
    (
        "5d352e4ec40848793a8497f301a6c06ea20642052859fd941a256bbf3387d227",
        plan_pin,
    ),
    (
        'tool = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(tool)',
        'tool = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(tool)\n'
        'tool.managed = tool.legacy.managed',
    ),
    (
        'tool_hash = sha(tool_path)',
        'tool_hash = sha(tool_path)\nconfiguration_applied = False',
    ),
    (
        'need(sha(repo / ".env") == plan["env_sha256"], "ENVIRONMENT_CHANGED")',
        'expected_env = plan["candidate_env_sha256"] if configuration_applied '
        'else plan["original_env_sha256"]\n'
        '    need(sha(repo / ".env") == expected_env, "ENVIRONMENT_CHANGED")',
    ),
    (
        "AUTO_LIMIT_CODE_CHECKS_PASS",
        "LOCAL_BINDING_ACTIVATION_CHECKS_PASS",
    ),
    (
        "AUTO_LIMIT_ALREADY_APPLIED",
        "LOCAL_BINDING_CONFIGURATION_APPLIED",
    ),
    (
        "AUTO_LIMIT_CODE_DEPLOYED_PAUSED_VERIFIED",
        "LOCAL_BINDING_ENABLED_PAUSED_VERIFIED",
    ),
    (
        'applied = tool.apply()',
        'applied = tool.apply()\n    configuration_applied = True',
    ),
    (
        '"CODE_APPLIED_SERVICES_STOPPED"',
        '"CONFIGURATION_APPLIED_SERVICES_STOPPED"',
    ),
    (
        'state["code_transaction"] = applied["transaction"]',
        'state["configuration_backup"] = applied["backup"]',
    ),
    (
        'code_transaction=state["code_transaction"],',
        'configuration_backup=state["configuration_backup"],',
    ),
    (
        'item["argv"], cwd=repo, env=item["env"],',
        'item["argv"], cwd=repo,\n'
        '                env={**item["env"], '
        '"HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED": "1"},',
    ),
    (
        'automatic_candidate_code_deployed=True,',
        'atomic_binding_enabled=True,',
    ),
    (
        'configuration_changed=False,',
        'configuration_changed=True,',
    ),
]
for old, new in replacements:
    need(text.count(old) == 1,
         "wrapper replacement point changed: " + old[:70])
    text = text.replace(old, new, 1)

anchor = 'startup = json.loads((backup / "startup-private.json").read_text())'
need(text.count(anchor) == 1, "startup insertion point changed")
text = text.replace(anchor, anchor + '''
need(all(
    item["env"].get("HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED", "0") == "0"
    for item in startup.values()
), "ORIGINAL_STARTUP_BINDING_MODE_MUST_BE_OFF")
''', 1)

anchor = '    state["phase"] = "LOCAL_BINDING_ENABLED_PAUSED_VERIFIED"'
need(text.count(anchor) == 1, "post-verification insertion point changed")
text = text.replace(anchor, '''
    for child in children.values():
        values = dict(
            item.split(b"=", 1)
            for item in Path(
                f"/proc/{child.pid}/environ"
            ).read_bytes().split(b"\\0")
            if b"=" in item
        )
        need(
            values.get(b"HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED") == b"1",
            "RESTARTED_PROCESS_BINDING_FLAG_NOT_ENABLED",
        )
    need(
        dotenv_values(repo / ".env").get(
            "HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED"
        ) == "1",
        "CONFIGURED_BINDING_FLAG_NOT_ENABLED",
    )
''' + anchor, 1)

compile(text, str(target), "exec")
with target.open("x") as stream:
    stream.write(text)

print(json.dumps({
    "status": "LOCAL_BINDING_ACTIVATION_WRAPPER_CREATED",
    "path": str(target),
    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    "syntax_checked": True,
    "executed": False,
    "running_configuration_changed": False,
    "processes_signalled": False,
    "production_execution_enabled": False,
}, indent=2))