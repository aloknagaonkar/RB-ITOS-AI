cd ~/RB-ITOS-AI
.venv/bin/python - <<'PY'
from contextlib import closing
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
import tempfile
import time

root = Path.cwd().resolve()
stage = root / "hilega-capture-archive-staging-v1"
producer = root / "hilega-ownership-producer-tools-v1"
maintenance = root / "hilega-ownership-record-maintenance-tools-v1"

OLD = "d144c596dee2411b7f2c0d4e8e6dae31442496c8b2e32859322ef09399d84563"
NEW = "7cc48fb3422bae9a86a2e2fa7d0d143ffbbfa7cabfab248c3b9ee8b14f084041"
OLD_MANIFEST = "f89c018edbacaa128b2a574087f8ead711301459c798567670229d3df15f89b5"
NEW_MANIFEST = "09ac943ec667024266520a6382cffa75d02d6f7939222e95a0894cd305ef4857"
RECORDS = "77c74722d7fdadbfc15053c660ed7df27090a847052ae9b5711a149ae390fe35"

writer = root / (
    "backend/market_lab/hilega_preparation_runtime_v1/ownership_state.py"
)
reference = producer / (
    "reference_runtime/market_lab/"
    "hilega_preparation_runtime_v1/ownership_state.py"
)
app = root / "data/research/hilega-production-workspace/sim.sqlite"
broker = root / "data/research/hilega-broker-adapter-closed/adapter.sqlite"

def need(ok, reason):
    if not ok:
        raise ValueError(reason)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def regular(path):
    need(path.is_file() and not path.is_symlink(), "REGULAR_FILE_REQUIRED")
    need(not any(p.is_symlink() for p in path.parents),
         "SYMLINK_PARENT_FORBIDDEN")
    return path

def sha(path):
    return digest(regular(path).read_bytes())

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, regular(path))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

m = module("capture_archive_maintenance", maintenance / "maintain.py")
m.self_check()
prod = module("capture_archive_producer", producer / "producer.py")

plan = json.loads(regular(stage / "DEPLOYMENT_PREFLIGHT.json").read_text())
regression = json.loads(
    regular(stage / "REGRESSION_VALIDATION.json").read_text()
)
need(
    plan.get("status") == "CAPTURE_ARCHIVE_DEPLOYMENT_PREFLIGHT_PASS"
    and plan.get("writer_before_sha256") == OLD
    and plan.get("writer_after_sha256") == NEW
    and plan.get("producer_manifest_before_sha256") == OLD_MANIFEST
    and plan.get("producer_manifest_after_sha256") == NEW_MANIFEST
    and plan.get("ownership_snapshot", {}).get("records_sha256") == RECORDS
    and plan.get("updated_producer_tests_exit_code") == 0
    and plan.get("applied") is False,
    "DEPLOYMENT_PREFLIGHT_INVALID",
)
need(
    regression.get("status") == "CAPTURE_ARCHIVE_REGRESSION_PASS"
    and regression.get("candidate_sha256") == NEW
    and regression.get("exit_codes") == {
        "ownership_components": 0,
        "producer": 0,
        "application_regressions": 0,
    },
    "REGRESSION_PROOF_INVALID",
)

# Producer manifest goes first, keeping its checks closed during replacement.
specs = [
    (producer / "manifest.json",
     stage / "producer-manifest.after.json",
     OLD_MANIFEST, NEW_MANIFEST),
    (reference, stage / "ownership_state.py", OLD, NEW),
    (writer, stage / "ownership_state.py", OLD, NEW),
]

def versions(expected):
    for target, source, before, after in specs:
        need(sha(target) == (before if expected == "old" else after),
             "INSTALLED_TARGET_CHANGED")
        need(sha(source) == after, "STAGED_TARGET_CHANGED")
    prod.package_check(root)

def install_files(directory, entries, backup):
    originals = {}
    replacements = {}
    for target, source, before, after in entries:
        need(target.is_relative_to(directory), "TARGET_OUTSIDE_ROOT")
        need(sha(target) == before, "TARGET_BASELINE_CHANGED")
        raw = regular(source).read_bytes()
        need(digest(raw) == after, "STAGED_TARGET_CHANGED")
        if target.suffix == ".py":
            compile(raw, str(target), "exec")
        else:
            json.loads(raw)
        originals[target] = (
            target.read_bytes(), target.stat().st_mode & 0o777
        )
        replacements[target] = raw

    for target, (raw, mode) in originals.items():
        saved = backup / "files" / target.relative_to(directory)
        saved.parent.mkdir(parents=True, exist_ok=True)
        m.atomic_write(saved, raw, mode)
        need(sha(saved) == digest(raw), "FILE_BACKUP_VERIFY_FAILED")

    changed = []
    try:
        for target, source, before, after in entries:
            m.atomic_write(
                target, replacements[target], originals[target][1]
            )
            changed.append(target)
            need(sha(target) == after, "INSTALLED_WRITE_VERIFY_FAILED")
    except BaseException:
        for target in reversed(changed):
            raw, mode = originals[target]
            m.atomic_write(target, raw, mode)
        raise

# Exercise installation, drift refusal and partial-write rollback.
with tempfile.TemporaryDirectory(prefix="archive-installer-test-") as temp:
    base = Path(temp)
    for case in ("success", "drift", "failure"):
        area = base / case
        area.mkdir()
        entries = []
        for name in ("manifest.json", "reference.py", "writer.py"):
            target = area / name
            source = area / ("new-" + name)
            old = b'{"version":1}\n' if name.endswith(".json") else b"VALUE=1\n"
            new = b'{"version":2}\n' if name.endswith(".json") else b"VALUE=2\n"
            target.write_bytes(old)
            source.write_bytes(new)
            entries.append((target, source, digest(old), digest(new)))
        backup = area / "backup"
        backup.mkdir()

        if case == "success":
            install_files(area, entries, backup)
            need(all(sha(t) == after for t, s, before, after in entries),
                 "INSTALL_SELF_TEST_FAILED")
        elif case == "drift":
            entries[-1][0].write_bytes(b"DRIFT\n")
            try:
                install_files(area, entries, backup)
            except ValueError:
                pass
            else:
                raise ValueError("DRIFT_SELF_TEST_FAILED")
            need(sha(entries[0][0]) == entries[0][2],
                 "DRIFT_CHANGED_EARLIER_TARGET")
        else:
            original_atomic = m.atomic_write
            injected = [False]
            def fail_once(path, raw, mode=0o600):
                if path == entries[1][0] and raw == b"VALUE=2\n" \
                        and not injected[0]:
                    injected[0] = True
                    raise OSError("INJECTED_WRITE_FAILURE")
                return original_atomic(path, raw, mode)
            m.atomic_write = fail_once
            try:
                try:
                    install_files(area, entries, backup)
                except OSError:
                    pass
                else:
                    raise ValueError("ROLLBACK_SELF_TEST_FAILED")
            finally:
                m.atomic_write = original_atomic
            need(all(sha(t) == before for t, s, before, after in entries),
                 "ROLLBACK_DID_NOT_RESTORE_FILES")

print('{"status":"FILE_INSTALL_SELF_TESTS_PASS","tests":3}', flush=True)

sys.path.insert(0, str(root / "backend"))
from market_lab.hilega_production_account_adapter_v1 import read_pin
from market_lab.hilega_preparation_runtime_v1 import ownership_state as state

pin_file = Path.home() / "hilega-private/upstox-account-pin.json"
pin = read_pin(pin_file)

def no_producer():
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            args = [
                x.decode(errors="replace")
                for x in (proc / "cmdline").read_bytes().split(b"\0") if x
            ]
            if any(Path(arg).name == "producer.py" for arg in args):
                cwd = (proc / "cwd").resolve()
                if cwd == root or any(str(root) in arg for arg in args):
                    raise ValueError("PRODUCER_PROCESS_ACTIVE")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue

def database_guard():
    regular(app)
    regular(broker)
    need(read_pin(pin_file) == pin, "ACCOUNT_PIN_CHANGED")
    with closing(sqlite3.connect(
        app.as_uri() + "?mode=ro", uri=True, timeout=10
    )) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("ATTACH DATABASE ? AS broker",
                   (broker.as_uri() + "?mode=ro",))
        need(db.execute("PRAGMA main.journal_mode").fetchone()[0] == "delete",
             "APPLICATION_DELETE_JOURNAL_REQUIRED")
        need(db.execute("PRAGMA broker.journal_mode").fetchone()[0] == "delete",
             "ADAPTER_DELETE_JOURNAL_REQUIRED")
        db.execute("BEGIN")
        try:
            source = state.read_connection(db, pin["scope"])
            need(source["control"].get("production_execution_enabled") is False,
                 "CLOSED_CONTROLLER_REQUIRED")
            stop = source["stop_state"]
            need(
                isinstance(stop, list) and len(stop) == 2
                and all(type(v) is int and v >= 0 for v in stop)
                and stop[0] == stop[1],
                "PENDING_OR_UNKNOWN_STOP",
            )
            for table in (
                "intents", "sim_orders", "sim_fills",
                "sim_allocation_reservations", "preparation_plans",
                "preparation_shadow_holds", "preparation_outbox",
            ):
                need(source["counts"][table] == 0,
                     "APPLICATION_ACTIVITY_REQUIRES_REVIEW")
            need(
                not source["cash_reservations"]
                and not source["bindings"]
                and not source["requests"]
                and not source["attempts"]
                and not source["receipts"],
                "RESERVATION_OR_ADAPTER_ACTIVITY",
            )
            names = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            need("preparation_account_captures" not in names,
                 "ARCHIVE_ALREADY_EXISTS_REVIEW")
            for table in (
                "staged_intents", "staged_reservations",
                "staged_adapter_requests",
            ):
                if table in names:
                    need(db.execute("SELECT COUNT(*) FROM " + table)
                         .fetchone()[0] == 0, "STAGED_ACTIVITY_REQUIRES_REVIEW")

            rows = {
                state.CURRENT: db.execute(
                    "SELECT id,data FROM " + state.CURRENT + " ORDER BY id"
                ).fetchall(),
                state.HISTORY: db.execute(
                    "SELECT id,fingerprint,source_fingerprint,data FROM "
                    + state.HISTORY + " ORDER BY id"
                ).fetchall(),
                state.AUDIT: db.execute(
                    "SELECT seq,data FROM " + state.AUDIT + " ORDER BY seq"
                ).fetchall(),
            }
            for table in (state.CURRENT, state.HISTORY):
                for entry in rows[table]:
                    value = json.loads(entry[-1])
                    state.validate_state(value, pin, "LIVE_CLOSED")
                    need(
                        value["status"] == "BLOCKED"
                        and value["reviewed_entry_quantity"] is None
                        and value.get("raw_account_capture_persisted") is False,
                        "OWNERSHIP_STATE_REQUIRES_REVIEW",
                    )
            for entry in rows[state.AUDIT]:
                value = json.loads(entry[-1])
                need(value.get("status") == "BLOCKED"
                     and value.get("orders_sent") is False,
                     "OWNERSHIP_AUDIT_REQUIRES_REVIEW")
            raw = json.dumps(
                rows, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
            need(digest(raw) == RECORDS, "OWNERSHIP_RECORDS_CHANGED")
            return {name: len(values) for name, values in rows.items()}
        finally:
            db.rollback()

def running_check():
    inventory = m.inventory_module(root)
    rows = inventory.inspect(root)["active_processes"]
    m.validate_running(m.unit_states(), rows)
    return rows

def backup_database(source_path, target):
    fd = os.open(
        target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    os.close(fd)
    with closing(sqlite3.connect(
        source_path.as_uri() + "?mode=ro", uri=True, timeout=10
    )) as src, closing(sqlite3.connect(target)) as dst:
        src.execute("PRAGMA query_only=ON")
        src.backup(dst)

versions("old")
no_producer()
previous_processes = running_check()
m.paused_check(root)
m.api_health()
counts = database_guard()

backups = root / "backups"
need(backups.is_dir() and not backups.is_symlink(), "BACKUP_DIRECTORY_REQUIRED")
os.umask(0o077)
backup = Path(tempfile.mkdtemp(
    prefix="hilega-capture-archive-maintenance-", dir=backups
))
record = backup / "transaction.json"
transaction = {
    "phase": "PREPARED",
    "backup": str(backup),
    "previous_processes": previous_processes,
    "ownership_records_sha256": RECORDS,
    "ownership_counts": counts,
    "installer_self_tests_passed": 3,
    "production_execution_enabled": False,
    "database_migration_performed": False,
    "targets": [
        {
            "path": str(target.relative_to(root)),
            "before_sha256": before,
            "after_sha256": after,
        }
        for target, source, before, after in specs
    ],
}

def save_phase(phase):
    transaction["phase"] = phase
    m.write_json(record, transaction)
    print(json.dumps({"phase": phase, "backup": str(backup)}), flush=True)

save_phase("PREPARED")
try:
    save_phase("STOPPING")
    m.call(["systemctl", "--user", "stop", *m.UNITS.values()])
    inventory = m.inventory_module(root)
    m.validate_stopped(m.unit_states(), inventory.processes(root))
    no_producer()
    versions("old")
    database_guard()

    backup_database(app, backup / "application-before.sqlite")
    backup_database(broker, backup / "adapter-before.sqlite")
    save_phase("DATABASES_BACKED_UP")

    with closing(sqlite3.connect(
        app.as_uri() + "?mode=rw", uri=True, timeout=10
    )) as lock:
        lock.execute("ATTACH DATABASE ? AS broker",
                     (broker.as_uri() + "?mode=ro",))
        lock.execute("BEGIN IMMEDIATE")
        try:
            lock.execute("SELECT data FROM broker.meta WHERE id=1").fetchone()
            no_producer()
            database_guard()
            save_phase("APPLYING_FILES")
            install_files(root, specs, backup)
            versions("new")
        finally:
            lock.rollback()

    save_phase("FILES_APPLIED_SERVICES_STOPPED")
    database_guard()
    save_phase("STARTING")
    for unit in m.UNITS.values():
        transaction["starting_unit"] = unit
        m.write_json(record, transaction)
        m.call(["systemctl", "--user", "start", unit])

    deadline = time.monotonic() + 45
    last_error = "STARTUP_VERIFICATION_PENDING"
    while time.monotonic() < deadline:
        try:
            rows = running_check()
            m.refresh_identities(root, rows, backup)
            versions("new")
            no_producer()
            m.paused_check(root)
            m.api_health()
            database_guard()
            break
        except Exception as exc:
            text = str(exc)
            last_error = (
                text if re.fullmatch(r"[A-Z][A-Z0-9_]{0,179}", text)
                else type(exc).__name__
            )
            time.sleep(1)
    else:
        raise ValueError(last_error)

    transaction.update(
        processes=rows,
        ownership_records_preserved=True,
        producer_manifest_updated=True,
        producer_reference_updated=True,
        archive_table_created=False,
        controller_mode="PAUSED",
        execution_route="PREPARATION_ONLY",
        reservation_release_permission=False,
        entry_allocation_fraction="0.50",
        daily_loss_limit_required=False,
    )
    transaction.pop("starting_unit", None)
    save_phase("DEPLOYED_PAUSED_VERIFIED")
    print(json.dumps(dict(
        transaction,
        status="CAPTURE_ARCHIVE_DEPLOYED_PAUSED_VERIFIED",
    ), indent=2))

except BaseException as exc:
    transaction["failure_after_phase"] = transaction["phase"]
    transaction["phase"] = "STOPPED_FOR_REVIEW"
    try:
        m.call(["systemctl", "--user", "stop", *m.UNITS.values()])
        inventory = m.inventory_module(root)
        m.validate_stopped(m.unit_states(), inventory.processes(root))
        transaction["services_stopped_verified"] = True
    except Exception:
        transaction["services_stopped_verified"] = False
    text = str(exc)
    transaction["reason"] = (
        text if re.fullmatch(r"[A-Z][A-Z0-9_]{0,179}", text)
        else type(exc).__name__
    )
    m.write_json(record, transaction)
    print(json.dumps(dict(
        transaction, status="STOPPED_FOR_REVIEW",
        automatic_retry=False,
    ), indent=2))
    raise SystemExit(1)
PY