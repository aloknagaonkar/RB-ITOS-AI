from copy import deepcopy
from datetime import timedelta
import json
import sqlite3
from unittest.mock import Mock, patch

import pytest

from production_entry_authorization_candidate import (
    issue_candidate, claim_candidate, TABLE,
)
from test_production_authorizer_hook import candidate
from test_live_closed_lifecycle_candidate import (
    synthetic_scope, env, bound_env, live_case,
)
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign


@pytest.fixture
def context(live_case):
    e, key, snapshot, at = live_case
    # Remove only the synthetic acknowledgement inserted by live_case.
    # This restores its temporary adapter to the prepared-entry state.
    with e["adapter_store"].tx() as db:
        db.execute("DELETE FROM receipts")
        db.execute("DELETE FROM attempts")
        row = json.loads(db.execute(
            "SELECT data FROM requests WHERE id=?", (key,)
        ).fetchone()[0])
        row.update(order_id=None, state="PREPARED")
        db.execute("UPDATE requests SET data=? WHERE id=?",
                   (json.dumps(row), key))
    source = read_sources(
        e["store"].path, e["adapter_store"].path, PIN["scope"])
    snapshot = deepcopy(snapshot)
    snapshot.update(orders=[], trades=[], positions=[])
    snapshot.pop("signature", None)
    snapshot["signature"] = sign(snapshot, PIN)
    wire = dict(
        method="POST", host="api-hft.upstox.com",
        path="/v3/order/place", body=row["draft"]["body"],
    )
    authority = dict(
        authority_id="SYNTHETIC-SEPARATE-AUTHORITY",
        account_scope=PIN["scope"], key="77"*32,
    )
    grant = issue_candidate(
        authority, PIN, source, snapshot,
        request_id=key, wire=wire, at=at.isoformat(),
    )
    return e, key, at, source, snapshot, wire, authority, grant


def consume(db, c, **changes):
    e, key, at, source, snapshot, wire, authority, grant = c
    options = dict(
        request_id=key, wire=wire, attempt_id="synthetic-attempt",
        at=at.isoformat(),
    )
    options.update(changes)
    return claim_candidate(
        db, grant, authority, PIN, source, snapshot, **options)


def test_signed_claim_single_use(context):
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        result = consume(db, context)
        assert result["context_revalidated"] is True
        with pytest.raises(ValueError, match="ALREADY_CONSUMED"):
            consume(db, context)


def test_claim_rollback_unspends_grant(context):
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        consume(db, context)
        db.rollback()
        db.execute("BEGIN IMMEDIATE")
        consume(db, context)


def test_expired_grant_blocks(context):
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="EXPIRED"):
            consume(db, context,
                    at=(context[2] + timedelta(seconds=10)).isoformat())


def test_changed_wire_blocks(context):
    wire = deepcopy(context[5])
    wire["body"]["price"] += 1
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="REQUEST_OR_WIRE_MISMATCH"):
            consume(db, context, wire=wire)


def test_capture_key_cannot_be_authority_key(context):
    authority = dict(context[6], key=PIN["key"])
    with pytest.raises(ValueError, match="INDEPENDENT_AUTHORITY_KEY"):
        issue_candidate(
            authority, PIN, context[3], context[4],
            request_id=context[1], wire=context[5],
            at=context[2].isoformat(),
        )


def test_forged_account_capture_blocks(context):
    context[4]["signature"] = "0"*64
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError):
            consume(db, context)


def test_changed_preparation_blocks(context):
    context[3]["stop_state"] = [1, 0]
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="FRESH_ENTRY_REFERENCE"):
            consume(db, context)


def test_signed_contract_connects_to_staged_attempt(context, candidate):
    e, key, at, source, snapshot, wire, authority, grant = context
    store = candidate.Store(
        e["adapter_store"].path, PIN["scope"], "LIVE_CLOSED")
    token = Mock(side_effect=AssertionError("No credentials"))
    transport = candidate.HttpTransport(token)
    adapter = candidate.Adapter(store, transport)

    def authorize(db, attempt):
        return claim_candidate(
            db, grant, authority, PIN, deepcopy(source), deepcopy(snapshot),
            request_id=attempt["request_id"], wire=attempt["wire"],
            attempt_id=attempt["attempt_id"], at=at.isoformat(),
        )

    adapter.production_attempt_authorizer = authorize

    def receipt(aid, sent_wire):
        return dict(
            attempt_id=aid, wire_fingerprint=candidate.sha(sent_wire),
            origin="LOCAL_HTTP_TRANSPORT", http_status=200,
            body=dict(status="success", data=dict(
                order_ids=["SYNTHETIC-AUTHORIZED-BUY"])),
        )

    # Both interceptions are confined to this synthetic test.
    with patch.object(transport, "check", return_value=None), patch.object(
        transport, "send", side_effect=receipt,
    ) as send:
        adapter.submit(key)
    with store.tx() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM " + TABLE).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
    send.assert_called_once()
    token.assert_not_called()
