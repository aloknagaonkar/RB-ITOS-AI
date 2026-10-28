import hashlib
import json
from pathlib import Path

repo = Path.cwd().resolve()
source = repo / "apply-auto-limit-maintenance.py"
target = repo / "apply-admission-wait-maintenance.py"
backup = repo / "backups/hilega-admission-wait-maintenance-5zpodt29"
plan_pin = "be2b037252ec707691e1e335c6792f5079daf2340b425483f413c596ffeee562"

def need(value, reason):
    if not value:
        raise SystemExit("STOP: " + reason)

need(source.is_file() and not source.is_symlink(),
     "reviewed maintenance wrapper missing")
need(not target.exists() and not target.is_symlink(),
     "admission maintenance wrapper already exists")

raw = source.read_bytes()
blob = hashlib.sha1(
    b"blob " + str(len(raw)).encode() + b"\0" + raw
).hexdigest()
need(blob == "cb6226838fc9823e047b2cc72e3a31ec5ed93cf4",
     "previous wrapper differs from reviewed version")

plan_path = backup / "plan.json"
need(plan_path.is_file() and not plan_path.is_symlink(),
     "regular maintenance plan required")
need(hashlib.sha256(plan_path.read_bytes()).hexdigest() == plan_pin,
     "maintenance plan changed")

text = raw.decode()
for old, new in [
    (
        "backups/hilega-auto-limit-maintenance-_mzrnlv9",
        "backups/hilega-admission-wait-maintenance-5zpodt29",
    ),
    (
        "hilega-auto-limit-deployment/deploy.py",
        "hilega-admission-wait-deployment/deploy.py",
    ),
    (
        "5d352e4ec40848793a8497f301a6c06ea20642052859fd941a256bbf3387d227",
        plan_pin,
    ),
]:
    need(text.count(old) == 1, "maintenance replacement point changed")
    text = text.replace(old, new, 1)

text = text.replace("AUTO_LIMIT", "ADMISSION_WAIT")

anchor = 'startup = json.loads((backup / "startup-private.json").read_text())'
need(text.count(anchor) == 1, "startup insertion point changed")
text = text.replace(anchor, anchor + '''
need(all(
    item["env"].get("HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED") == "1"
    for item in startup.values()
), "SAVED_STARTUP_BINDING_MODE_MUST_REMAIN_ON")
''', 1)

anchor = '    state["phase"] = "ADMISSION_WAIT_CODE_DEPLOYED_PAUSED_VERIFIED"'
need(text.count(anchor) == 1, "verification insertion point changed")
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
            "RESTARTED_PROCESS_BINDING_MODE_NOT_ON",
        )
    need(
        dotenv_values(repo / ".env").get(
            "HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED"
        ) == "1",
        "FILE_BINDING_MODE_NOT_ON",
    )
''' + anchor, 1)

anchor = "        automatic_candidate_code_deployed=True,"
need(text.count(anchor) == 1, "result insertion point changed")
text = text.replace(
    anchor,
    "        admission_wait_code_deployed=True,\n"
    "        atomic_binding_enabled=True,",
    1,
)

compile(text, str(target), "exec")
with target.open("x") as stream:
    stream.write(text)

print(json.dumps({
    "status": "ADMISSION_WAIT_MAINTENANCE_WRAPPER_CREATED",
    "path": str(target),
    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    "syntax_checked": True,
    "executed": False,
    "processes_signalled": False,
    "applied": False,
    "configuration_change_included": False,
}, indent=2))