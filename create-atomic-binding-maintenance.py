import hashlib
import json
from pathlib import Path

repo = Path.cwd().resolve()
source = repo / "apply-auto-limit-maintenance.py"
target = repo / "apply-atomic-binding-maintenance.py"
backup = repo / "backups/hilega-atomic-binding-maintenance-dr3gn23_"
plan_pin = "a4545ade1cfacc761267eb2a0e464cef11c520fbc77f7a5b854b2b11ecb67c72"

def need(value, reason):
    if not value:
        raise SystemExit("STOP: " + reason)

need(source.is_file() and not source.is_symlink(),
     "previous maintenance wrapper missing")
need(not target.exists() and not target.is_symlink(),
     "new wrapper already exists")

raw = source.read_bytes()
blob = hashlib.sha1(
    b"blob " + str(len(raw)).encode() + b"\0" + raw
).hexdigest()
need(blob == "cb6226838fc9823e047b2cc72e3a31ec5ed93cf4",
     "previous maintenance wrapper differs from reviewed version")

plan_path = backup / "plan.json"
need(plan_path.is_file() and not plan_path.is_symlink(),
     "regular maintenance plan required")
need(hashlib.sha256(plan_path.read_bytes()).hexdigest() == plan_pin,
     "maintenance plan changed")

text = raw.decode()
replacements = [
    (
        "backups/hilega-auto-limit-maintenance-_mzrnlv9",
        "backups/hilega-atomic-binding-maintenance-dr3gn23_",
    ),
    (
        "hilega-auto-limit-deployment/deploy.py",
        "hilega-atomic-binding-deployment/deploy.py",
    ),
    (
        "5d352e4ec40848793a8497f301a6c06ea20642052859fd941a256bbf3387d227",
        plan_pin,
    ),
]
for old, new in replacements:
    need(text.count(old) == 1, "maintenance replacement point changed")
    text = text.replace(old, new, 1)

text = text.replace("AUTO_LIMIT", "ATOMIC_BINDING")

anchor = 'startup = json.loads((backup / "startup-private.json").read_text())'
need(text.count(anchor) == 1, "startup check insertion point changed")
text = text.replace(anchor, anchor + '''
need(all(
    item["env"].get("HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED", "0") == "0"
    for item in startup.values()
), "BINDING_STARTUP_MODE_MUST_REMAIN_OFF")
''', 1)

anchor = '    state["phase"] = "ATOMIC_BINDING_CODE_DEPLOYED_PAUSED_VERIFIED"'
need(text.count(anchor) == 1, "verification insertion point changed")
text = text.replace(anchor, '''
    # Verify the restarted processes' actual startup environments.
    for child in children.values():
        values = dict(
            item.split(b"=", 1)
            for item in Path(
                f"/proc/{child.pid}/environ"
            ).read_bytes().split(b"\\0")
            if b"=" in item
        )
        need(
            values.get(
                b"HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED", b"0"
            ) == b"0",
            "RESTARTED_PROCESS_BINDING_MODE_NOT_OFF",
        )
    need(
        dotenv_values(repo / ".env").get(
            "HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED", "0"
        ) == "0",
        "FILE_BINDING_MODE_NOT_OFF",
    )
''' + anchor, 1)

anchor = "        automatic_candidate_code_deployed=True,"
need(text.count(anchor) == 1, "result field changed")
text = text.replace(
    anchor,
    "        atomic_binding_code_deployed=True,\n"
    "        atomic_binding_enabled=False,",
    1,
)

compile(text, str(target), "exec")
with target.open("x") as stream:
    stream.write(text)

print(json.dumps({
    "status": "ATOMIC_BINDING_MAINTENANCE_WRAPPER_CREATED",
    "path": str(target),
    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    "syntax_checked": True,
    "executed": False,
    "processes_signalled": False,
    "applied": False,
    "binding_activation_included": False,
}, indent=2))