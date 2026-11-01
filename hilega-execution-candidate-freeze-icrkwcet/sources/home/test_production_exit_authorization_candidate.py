from copy import deepcopy
from datetime import timedelta
import json
import sqlite3

import pytest

from production_exit_authorization_candidate import (
    issue_exit_candidate, claim_exit_candidate,
)
from test_live_closed_lifecycle_candidate import (
    synthetic_scope, env, bound_env, live_case,
)
from test_hilega_application_preparation_v1 import append
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_execution_port_v1.adapter import Adapter, HttpTransport
from market_lab.hilega_execution_port_v1.mapping import draft
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha

EXIT = "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"


@pytest.fixture
def exit_case(live_case):
    e, entry_id, snapshot, at = live_case
    source = read_sources(e["store"].path, e["adapter_store"].path, PIN["scope"])
    contract = deepcopy(source["plans"][entry_id]["evidence"]["contract"])
    for field in ("lot_size", "minimum_lot", "freeze_quantity"):
        contract[field] = int(contract[field])
    append(e["path"], [EXIT])
    record = verified_records(e["path"])[-1]
    event = accepted(record)[0]
    exit_id = sha(["PRODUCTION_EXIT_CANDIDATE", entry_id, event["id"]])
    request = draft(
        contract, request_id=exit_id, side="SELL", lots=1,
        as_of=event["event_at"], order_type="LIMIT",
        limit_price="101", normalized_tick_rupees="0.05",
    )
    def no_token():
        raise AssertionError("No credential access")
    adapter = Adapter(e["adapter_store"], HttpTransport(no_token))
    entry = e["adapter_store"].requests()[0]
    saved = adapter.prepare(
        request, signal_id=event["id"], signal_at=event["event_at"],
        direction=event["direction"],
        reservation_reference=entry["reservation_reference"],
        as_of=at.isoformat(),
    )
    source = read_sources(e["store"].path, e["adapter_store"].path, PIN["scope"])
    wire = adapter._wire(saved, "PLACE")
    authority = dict(
        authority_id="SYNTHETIC-EXIT-AUTHORITY",
        account_scope=PIN["scope"], key="77"*32,
    )
    kwargs = dict(
        entry_id=entry_id, request_id=exit_id, wire=wire,
        journal=e["path"], exit_sequence=record["sequence"],
    )
    grant = issue_exit_candidate(
        authority, PIN, source, snapshot, **kwargs, at=at.isoformat())
    return source, snapshot, authority, grant, kwargs, at


def consume(db, case, **changes):
    source, snapshot, authority, grant, kwargs, at = case
    options = dict(kwargs, attempt_id="synthetic-exit-attempt",
                   at=at.isoformat())
    options.update(changes)
    return claim_exit_candidate(
        db, grant, authority, PIN, source, snapshot, **options)


def test_ownership_bound_sell_claim(exit_case):
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        result = consume(db, exit_case)
        assert result["context_revalidated"] is True
        assert result["production_execution_enabled"] is False


def test_single_use_exit_claim(exit_case):
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        consume(db, exit_case)
        with pytest.raises(ValueError, match="ALREADY_CONSUMED"):
            consume(db, exit_case)


def test_exit_claim_rollback(exit_case):
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        consume(db, exit_case)
        db.rollback()
        db.execute("BEGIN IMMEDIATE")
        consume(db, exit_case)


def test_exit_expiry_blocks(exit_case):
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="EXPIRED"):
            consume(db, exit_case,
                    at=(exit_case[5]+timedelta(seconds=10)).isoformat())


def test_changed_sell_wire_blocks(exit_case):
    wire = deepcopy(exit_case[4]["wire"])
    wire["body"]["quantity"] += 1
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="BINDING_MISMATCH"):
            consume(db, exit_case, wire=wire)


def test_forged_ownership_capture_blocks(exit_case):
    exit_case[1]["signature"] = "0"*64
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError):
            consume(db, exit_case)


def test_wrong_entry_parent_blocks(exit_case):
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="BINDING_MISMATCH"):
            consume(db, exit_case, entry_id="unrelated-entry")
