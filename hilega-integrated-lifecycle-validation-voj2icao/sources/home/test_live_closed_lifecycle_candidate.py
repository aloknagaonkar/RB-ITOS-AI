from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import sqlite3
from unittest.mock import patch

import pytest

from application_lifecycle_review import record_application_review
from application_lifecycle_state import read_current, HISTORY
from test_automatic_entry_fixture import synthetic_scope, env, bound_env
from test_hilega_application_preparation_v1 import process
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import (
    MODEL, LIVE, sign,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha


@pytest.fixture
def live_case(synthetic_scope, monkeypatch, request):
    # A synthetic pin, not the operator's real account identity.
    from market_lab.hilega_production_account_adapter_v1 import account_scope
    monkeypatch.setitem(
        PIN, "scope", account_scope(PIN["key"], "SYNTHETIC_PROVIDER_TEST"))
    e = request.getfixturevalue("bound_env")
    process(e)
    rows = e["adapter_store"].requests()
    assert len(rows) == 1
    row = rows[0]
    key = row["request_id"]
    body = row["draft"]["body"]
    order_id = "SYNTHETIC-LIVE-BRANCH-ORDER"
    attempt_id = "synthetic-live-branch-attempt"
    wire = dict(
        method="POST", host="api-hft.upstox.com",
        path="/v3/order/place", body=body,
    )
    attempt = dict(
        attempt_id=attempt_id, request_id=key, operation="PLACE",
        wire=wire, state="ACKNOWLEDGED_NOT_FILLED", retry_allowed=False,
    )
    receipt = dict(
        attempt_id=attempt_id, wire_fingerprint=sha(wire),
        http_status=200, origin="LOCAL_HTTP_TRANSPORT",
        body=dict(status="success", data=dict(order_ids=[order_id])),
    )
    # Explicit synthetic fixture construction. No adapter submit or HTTP call.
    with e["adapter_store"].tx() as db:
        row.update(order_id=order_id, state="ACKNOWLEDGED_NOT_FILLED")
        db.execute("UPDATE requests SET data=? WHERE id=?",
                   (json.dumps(row), key))
        db.execute("INSERT INTO attempts VALUES(?,?,?,?)",
                   (attempt_id, key, "PLACE", json.dumps(attempt)))
        db.execute("INSERT INTO receipts VALUES(?,?)",
                   (attempt_id, json.dumps(receipt)))

    at = e["clock"][0]
    quantity = body["quantity"]
    generated = at + timedelta(seconds=3)
    completed = generated + timedelta(seconds=1)
    snapshot = dict(
        model=MODEL, evidence_mode=LIVE, account_scope=PIN["scope"],
        snapshot_id="synthetic-live-branch-capture",
        session_date=generated.date().isoformat(),
        generated_at=generated.isoformat(),
        completed_at=completed.isoformat(),
        status="READ_ONLY_CAPTURED",
        account_identity_verified=True,
        profile_verified_before_and_after=True,
        account_position_rows_complete=True,
        source_atomic=False, position_fill_linkage_verified=False,
        live_pnl=None, production_execution_enabled=False,
        orders_sent=False, entry_permission=False, diagnostics={},
        orders=[dict(
            order_id=order_id, instrument=body["instrument_token"],
            product=body["product"], side="BUY",
            quantity=quantity, filled=quantity, pending=0,
            status="FILLED", placed_at=at.isoformat(),
        )],
        trades=[dict(
            order_id=order_id, trade_id="synthetic-live-branch-trade",
            instrument=body["instrument_token"], product=body["product"],
            side="BUY", quantity=quantity, price=str(body["price"]),
            filled_at=(at + timedelta(seconds=1)).isoformat(),
        )],
        positions=[dict(
            instrument=body["instrument_token"],
            product=body["product"], quantity=quantity,
        )],
    )
    snapshot["signature"] = sign(snapshot, PIN)
    return e, key, snapshot, completed + timedelta(seconds=1)


def run(case, *, pin=None, clock=None, checkpoint=lambda stage: None):
    e, key, snapshot, at = case
    return record_application_review(
        e["store"].path, e["adapter_store"].path,
        snapshot, pin or PIN, entry_id=key,
        journal=e["path"], exit_sequences=[],
        clock=clock or (lambda: at),
        mode="LIVE_CLOSED", checkpoint=checkpoint,
    )


def test_live_closed_branch_commits_only_reference_state(live_case):
    e, key, snapshot, at = live_case
    before = e["adapter_store"].path.read_bytes()
    with patch(
        "market_lab.hilega_execution_port_v1.adapter.build_opener",
        side_effect=AssertionError("No broker access permitted"),
    ):
        result = run(live_case)
    assert result["status"] == "APPLICATION_LIFECYCLE_REVIEW_COMMITTED"
    assert result["current"]["report"]["reviewed_remaining_quantity"] > 0
    assert result["current"]["strategy_ownership_verified"] is False
    assert result["production_execution_enabled"] is False
    assert e["adapter_store"].path.read_bytes() == before
    assert e["store"].control()["mode"] == "PAUSED"


def test_wrong_account_cannot_create_state(live_case):
    wrong = dict(PIN, scope="UPSTOX:" + "b" * 64)
    with pytest.raises(ValueError):
        run(live_case, pin=wrong)
    e = live_case[0]
    with sqlite3.connect(e["store"].path) as db:
        assert read_current(db, PIN) is None


def test_concurrent_live_closed_reviewers_record_once(live_case):
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, live_case) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert sorted(r["idempotent_replay"] for r in results) == [False, True]
    with sqlite3.connect(live_case[0]["store"].path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM " + HISTORY).fetchone()[0] == 1


def test_lost_committed_result_replays_without_duplicate(live_case):
    def lost_response():
        run(live_case)
        raise RuntimeError("SYNTHETIC_LOST_COMMITTED_RESULT")
    with pytest.raises(RuntimeError, match="LOST_COMMITTED_RESULT"):
        lost_response()
    replay = run(live_case)
    assert replay["idempotent_replay"] is True
    assert replay["database_modified"] is False
    with sqlite3.connect(live_case[0]["store"].path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM " + HISTORY).fetchone()[0] == 1


def test_live_closed_interruption_rolls_back(live_case):
    def interrupt(stage):
        if stage == "BEFORE_COMMIT_VALIDATION":
            raise RuntimeError("SYNTHETIC_LIVE_BRANCH_INTERRUPTION")
    with pytest.raises(RuntimeError, match="LIVE_BRANCH_INTERRUPTION"):
        run(live_case, checkpoint=interrupt)
    with sqlite3.connect(live_case[0]["store"].path) as db:
        assert read_current(db, PIN) is None


def test_live_closed_expiry_rolls_back(live_case):
    at = live_case[3]
    times = iter([at, at + timedelta(minutes=5)])
    with pytest.raises(ValueError):
        run(live_case, clock=lambda: next(times))
    with sqlite3.connect(live_case[0]["store"].path) as db:
        assert read_current(db, PIN) is None
