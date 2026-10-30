"""Patch fixture exits and run consolidated synthetic lifecycle validation."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path.cwd().resolve()
HOME = Path.home()
source = HOME / "automatic_exit_fixture.py"
if source.is_symlink() or not source.is_file():
    raise SystemExit("STOP: regular fixture exit source required")
original = source.read_text()

changes = [
    (
        '''    need(entry["order_id"] is not None, "ACKNOWLEDGED_ENTRY_REQUIRED")''',
        '''    need(entry["order_id"] is not None, "ACKNOWLEDGED_ENTRY_REQUIRED")
    need(entry["state"] not in {
        "UNKNOWN", "CANCEL_OUTCOME_UNKNOWN", "CANCEL_IN_FLIGHT",
    }, "ENTRY_OUTCOME_UNRESOLVED")''',
    ),
    (
        '''    need(order["status"] == "FILLED"
         and order["filled"] == body["quantity"],
         "FULL_ENTRY_FILL_REQUIRED")''',
        '''    need(
        (order["status"] == "FILLED"
         and order["filled"] == body["quantity"])
        or (order["status"] == "CANCELLED"
            and type(order["filled"]) is int
            and 0 < order["filled"] <= body["quantity"]),
        "FULL_ENTRY_FILL_REQUIRED",
    )''',
    ),
    (
        '''    adapter.prepare(
        request, signal_id=exit_event["id"],''',
        '''    # Synthetic partial-fill quantity only. Live lot/quantity policy
    # must be independently validated before production submission.
    request["body"]["quantity"] = order["filled"]
    request["fingerprint"] = sha(request["body"])
    adapter.prepare(
        request, signal_id=exit_event["id"],''',
    ),
]
updated = original
for old, new in changes:
    if updated.count(old) != 1:
        raise SystemExit("STOP: fixture patch anchor changed: " + old[:90])
    updated = updated.replace(old, new)
compile(updated, str(source), "exec")

folder = Path(tempfile.mkdtemp(
    prefix="hilega-partial-exit-batch-", dir=ROOT))
backup = folder / "automatic_exit_fixture.before.py"
backup.write_text(original)
source.write_text(updated)

test = folder / "test_partial_exit_batch.py"
test.write_text(r'''
from datetime import datetime, timedelta
import json

import pytest

from automatic_exit_fixture import run_exit_fixture
from test_automatic_entry_fixture import (
    entry, synthetic_scope, env, bound_env,
    run as run_entry, application_bytes,
)
from test_hilega_application_preparation_v1 import append
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_execution_port_v1.adapter import Adapter, FixtureTransport
from market_lab.hilega_production_simulator_bridge_v1 import (
    EXITS, accepted, verified_records,
)


def setup_exit(entry, quantity, *, unknown_cancel=False):
    e, execution = entry
    run_entry(entry)
    parent, = execution.requests()
    transport = FixtureTransport(execution)
    transport.fill(parent["order_id"], quantity)
    transport.cancel_timeout = unknown_cancel
    Adapter(execution, transport).cancel(parent["request_id"])

    at = datetime.fromisoformat(parent["signal_at"]) + timedelta(minutes=5)
    name = next(n for n, direction in EXITS.items()
                if direction == parent["direction"])
    append(e["path"], [name], at=at.isoformat())
    event, = accepted(verified_records(e["path"])[-1])
    with e["store"].db() as db:
        plan = json.loads(db.execute(
            "SELECT data FROM preparation_plans"
        ).fetchone()[0])
    return parent, event, plan["evidence"]["contract"], at


def execute(entry, data, **changes):
    parent, event, contract, at = data
    return run_exit_fixture(
        entry[1], PIN, entry_id=parent["request_id"],
        exit_event=changes.get("event", event), contract=contract,
        as_of=at.isoformat(),
    )


@pytest.mark.parametrize("quantity", [20, 64])
def test_cancelled_partial_entry_exits_actual_filled_quantity(entry, quantity):
    data = setup_exit(entry, quantity)
    before = application_bytes(entry)
    result = execute(entry, data)
    execution = entry[1]
    sell = next(r for r in execution.requests()
                if r["request_id"] == result["exit_request_id"])
    assert sell["draft"]["body"]["quantity"] == quantity
    FixtureTransport(execution).fill(sell["order_id"], quantity)
    final = execute(entry, data)
    assert final["fixture_remaining_quantity"] == 0
    assert final["fixture_flat_reference"] is True
    assert final["reservation_release_permission"] is False
    assert application_bytes(entry) == before


def test_partial_exit_of_cancelled_entry_retains_exposure(entry):
    data = setup_exit(entry, 20)
    result = execute(entry, data)
    execution = entry[1]
    sell = next(r for r in execution.requests()
                if r["request_id"] == result["exit_request_id"])
    FixtureTransport(execution).fill(sell["order_id"], 5)
    final = execute(entry, data)
    assert final["fixture_remaining_quantity"] == 15
    assert final["fixture_flat_reference"] is False


def test_unknown_entry_cancel_prevents_sell(entry):
    data = setup_exit(entry, 20, unknown_cancel=True)
    with pytest.raises(ValueError, match="^ENTRY_OUTCOME_UNRESOLVED$"):
        execute(entry, data)
    assert all(
        r["draft"]["body"]["transaction_type"] == "BUY"
        for r in entry[1].requests()
    )


def test_second_exit_identity_cannot_overlap(entry):
    data = setup_exit(entry, 20)
    execute(entry, data)
    parent, event, contract, at = data
    with pytest.raises(ValueError, match="^OTHER_EXIT_REQUIRES_RECONCILIATION$"):
        execute(entry, data, event=dict(event, id=event["id"] + "-another-exit"))
    sells = [
        r for r in entry[1].requests()
        if r["draft"]["body"]["transaction_type"] == "SELL"
    ]
    assert len(sells) == 1
''')

names = [
    "test_automatic_entry_fixture.py",
    "test_automatic_exit_fixture.py",
    "test_automatic_exit_entry_quantity.py",
    "test_fixture_event_dispatcher.py",
    "test_fixture_journal_consumer.py",
    "test_fixture_consumer_integrity.py",
    "test_delayed_fixture_recovery.py",
    "test_fixture_recovery_boundaries.py",
]
environment = dict(os.environ)
environment["PYTHONPATH"] = os.pathsep.join(map(str, (
    HOME, ROOT / "backend", ROOT / "tests", ROOT,
)))
result = subprocess.run(
    [sys.executable, "-m", "pytest", "-q",
     *[str(HOME / name) for name in names], str(test)],
    cwd=ROOT, env=environment, check=False,
)
report = dict(
    status="PASS" if result.returncode == 0 else "FAILED_REVIEW_REQUIRED",
    assessed_at=datetime.now(timezone.utc).isoformat(),
    pytest_exit_code=result.returncode,
    scope="SYNTHETIC_TEMPORARY_DATABASES_ONLY",
    fixture_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    backup=str(backup),
    live_partial_quantity_policy_verified=False,
    runtime_deployed=False,
    orders_sent_to_upstox=False,
    production_execution_enabled=False,
    reservation_release_permission=False,
)
output = folder / "VALIDATION.json"
output.write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
print("Report:", output)
raise SystemExit(result.returncode)