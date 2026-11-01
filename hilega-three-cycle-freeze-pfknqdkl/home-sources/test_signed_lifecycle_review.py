from copy import deepcopy
from datetime import datetime, timedelta
import json

import pytest

from lifecycle_quantity_review import review_lifecycle
from test_authorized_exit_integration import (
    synthetic_scope, env, bound_env, module, prepared,
    lifecycle, fill_entry, invoke,
)
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import (
    read_sources,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import (
    MODEL, LIVE, sign,
)


def values(lifecycle):
    prepared, key, entry, contract, event, at = lifecycle
    e, mod, store = prepared
    source = read_sources(
        e["store"].path, e["adapter_store"].path, PIN["scope"])

    # Combine the application references with the separate fixture execution
    # records. This is an explicit test assembly, not a production reader.
    with store.tx() as db:
        source["requests"] = db.execute(
            "SELECT id,fingerprint,data FROM requests ORDER BY rowid"
        ).fetchall()
        source["attempts"] = db.execute(
            "SELECT id,request_id,operation,data FROM attempts ORDER BY rowid"
        ).fetchall()
        source["receipts"] = dict(db.execute(
            "SELECT id,data FROM receipts"
        ).fetchall())
    source["mode"] = "OFFLINE_FIXTURE"

    requests = {
        json.loads(raw)["order_id"]: json.loads(raw)
        for _, _, raw in source["requests"]
        if json.loads(raw).get("order_id")
    }
    orders, trades = [], []
    remaining = 0
    for original in mod.FixtureTransport(store).orders():
        row = deepcopy(original)
        request = requests[row["order_id"]]
        placed = datetime.fromisoformat(request["signal_at"])
        row["placed_at"] = placed.isoformat()
        row["pending"] = (
            row["quantity"] - row["filled"]
            if row["status"] in {"OPEN", "PARTIAL"} else 0
        )
        orders.append(row)
        if row["filled"]:
            trades.append(dict(
                order_id=row["order_id"],
                trade_id="trade-" + row["order_id"],
                instrument=row["instrument"], product=row["product"],
                side=row["side"], quantity=row["filled"],
                price="100" if row["side"] == "BUY" else "101",
                filled_at=(placed + timedelta(seconds=1)).isoformat(),
            ))
        remaining += (
            row["filled"] if row["side"] == "BUY" else -row["filled"]
        )

    generated = at + timedelta(seconds=3)
    completed = generated + timedelta(seconds=1)
    snapshot = dict(
        model=MODEL, evidence_mode=LIVE, account_scope=PIN["scope"],
        snapshot_id="signed-lifecycle-test",
        session_date=generated.astimezone(
            datetime.fromisoformat(event["event_at"]).tzinfo
        ).date().isoformat(),
        generated_at=generated.isoformat(),
        completed_at=completed.isoformat(),
        status="READ_ONLY_CAPTURED",
        account_identity_verified=True,
        profile_verified_before_and_after=True,
        account_position_rows_complete=True,
        source_atomic=False, position_fill_linkage_verified=False,
        live_pnl=None,
        production_execution_enabled=False, orders_sent=False,
        entry_permission=False, diagnostics={},
        orders=orders, trades=trades,
        positions=[dict(
            instrument=entry["draft"]["body"]["instrument_token"],
            product=entry["draft"]["body"]["product"],
            quantity=remaining,
        )],
    )
    snapshot["signature"] = sign(snapshot, PIN)
    return source, snapshot, key, (completed + timedelta(seconds=1)).isoformat()


def assess(data):
    source, snapshot, key, at = data
    return review_lifecycle(
        source, snapshot, PIN, entry_id=key, as_of=at)


def resign(data):
    snapshot = data[1]
    snapshot.pop("signature", None)
    snapshot["signature"] = sign(snapshot, PIN)


def test_signed_full_entry_reconciles_without_mutation(lifecycle):
    quantity = fill_entry(lifecycle)
    data = values(lifecycle)
    before = deepcopy(data)
    result = assess(data)
    assert result["reviewed_remaining_quantity"] == quantity
    assert result["strategy_ownership_verified"] is False
    assert result["exit_submission_permission"] is False
    assert result["reservation_release_permission"] is False
    assert data == before


def test_signed_cancelled_partial_entry(lifecycle):
    quantity = lifecycle[2]["draft"]["body"]["quantity"] - 1
    fill_entry(lifecycle, quantity, cancel=True)
    assert assess(values(lifecycle))["reviewed_remaining_quantity"] == quantity


def test_signed_partial_sell_reduces_remaining(lifecycle):
    quantity = fill_entry(lifecycle)
    invoke(lifecycle)
    _, mod, store = lifecycle[0]
    sell = next(
        o for o in mod.FixtureTransport(store).orders() if o["side"] == "SELL")
    mod.FixtureTransport(store).fill(sell["order_id"], 1)
    result = assess(values(lifecycle))
    assert result["reviewed_sell_fill_quantity"] == 1
    assert result["reviewed_remaining_quantity"] == quantity - 1
    assert result["working_sell_present"] is True


def test_signed_flat_requires_explicit_position_row(lifecycle):
    quantity = fill_entry(lifecycle)
    invoke(lifecycle)
    _, mod, store = lifecycle[0]
    transport = mod.FixtureTransport(store)
    sell = next(o for o in transport.orders() if o["side"] == "SELL")
    transport.fill(sell["order_id"], quantity)
    data = values(lifecycle)
    assert assess(data)["reviewed_remaining_quantity"] == 0
    data[1]["positions"] = []
    resign(data)
    with pytest.raises(ValueError, match="MISSING_POSITION_ROW"):
        assess(data)


def test_signature_tampering_blocks(lifecycle):
    fill_entry(lifecycle)
    data = values(lifecycle)
    data[1]["positions"][0]["quantity"] -= 1
    with pytest.raises(ValueError):
        assess(data)


def test_signed_duplicate_trade_blocks(lifecycle):
    fill_entry(lifecycle)
    data = values(lifecycle)
    data[1]["trades"].append(deepcopy(data[1]["trades"][0]))
    resign(data)
    with pytest.raises(ValueError, match="DUPLICATE_TRADE_ID"):
        assess(data)


def test_signed_position_mismatch_blocks(lifecycle):
    fill_entry(lifecycle)
    data = values(lifecycle)
    data[1]["positions"][0]["quantity"] -= 1
    resign(data)
    with pytest.raises(ValueError, match="REMAINING_POSITION_MISMATCH"):
        assess(data)


def test_open_partial_entry_blocks(lifecycle):
    quantity = lifecycle[2]["draft"]["body"]["quantity"] - 1
    fill_entry(lifecycle, quantity)
    with pytest.raises(ValueError, match="TERMINAL_FILLED_ENTRY_REQUIRED"):
        assess(values(lifecycle))


def test_unknown_entry_blocks(lifecycle):
    fill_entry(lifecycle)
    data = values(lifecycle)
    rid, fp, raw = data[0]["requests"][0]
    row = json.loads(raw)
    row["state"] = "CANCEL_OUTCOME_UNKNOWN"
    data[0]["requests"][0] = (rid, fp, json.dumps(row))
    with pytest.raises(ValueError, match="REQUEST_OUTCOME_UNRESOLVED"):
        assess(data)


def test_receipt_provenance_tampering_blocks(lifecycle):
    fill_entry(lifecycle)
    data = values(lifecycle)
    receipts = data[0]["receipts"]
    key = next(iter(receipts))
    row = json.loads(receipts[key])
    row["origin"] = "UNTRUSTED"
    receipts[key] = json.dumps(row)
    with pytest.raises(ValueError, match="RECEIPT_PROVENANCE_MISMATCH"):
        assess(data)
