from copy import deepcopy
import sqlite3
import pytest

from authorized_exit_fixture import issue_exit, claim_exit
from fixture_execution_authorization import sha

PIN = {"scope": "FIXTURE:AUTHORIZED-EXIT", "key": "55" * 32}
AT = "2026-10-30T10:00:00+05:30"


def inputs():
    event = dict(id="exit-event", role="EXIT", direction="BULLISH", event_at=AT)
    owned = dict(
        filled=20, status="CANCELLED",
        direction="BULLISH", instrument="NSE_FO|123", product="I",
    )
    wire = dict(
        method="POST", host="api-hft.upstox.com", path="/v3/order/place",
        body=dict(transaction_type="SELL", order_type="LIMIT",
                  quantity=20, instrument_token="NSE_FO|123",
                  product="I", price=101),
    )
    key = sha(["SYNTHETIC_STRATEGY_EXIT", "parent", event["id"]])
    return event, owned, wire, key


def grant_for(event, owned, wire, key):
    return issue_exit(
        PIN, request_id=key, parent_id="parent", event=event,
        wire=wire, ownership=owned, at=AT,
    )


def consume(db, grant, event, owned, wire, key, at=AT):
    return claim_exit(
        db, grant, PIN, parent_id="parent", event=event,
        ownership=owned, request_id=key, wire=wire,
        at=at, attempt_id="attempt",
    )


def test_partial_quantity_claim_is_single_use():
    event, owned, wire, key = inputs()
    grant = grant_for(event, owned, wire, key)
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        consume(db, grant, event, owned, wire, key)
        with pytest.raises(ValueError, match="ALREADY_CONSUMED"):
            consume(db, grant, event, owned, wire, key)


@pytest.mark.parametrize("quantity", [0, 19, 21, True])
def test_changed_sell_quantity_blocks(quantity):
    event, owned, wire, key = inputs()
    wire["body"]["quantity"] = quantity
    with pytest.raises(ValueError):
        grant_for(event, owned, wire, key)


@pytest.mark.parametrize("field", ["event", "ownership", "wire"])
def test_changed_context_blocks_claim(field):
    event, owned, wire, key = inputs()
    grant = grant_for(event, owned, wire, key)
    if field == "event":
        event["id"] = "different"
    elif field == "ownership":
        owned["filled"] = 19
    else:
        wire["body"]["price"] = 102
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError):
            consume(db, grant, event, owned, wire, key)


def test_expiry_blocks_claim():
    event, owned, wire, key = inputs()
    grant = grant_for(event, owned, wire, key)
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="EXPIRED"):
            consume(db, grant, event, owned, wire, key,
                    at="2026-10-30T10:00:10+05:30")


def test_rollback_does_not_consume_grant():
    event, owned, wire, key = inputs()
    grant = grant_for(event, owned, wire, key)
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        consume(db, grant, event, owned, wire, key)
        db.rollback()
        db.execute("BEGIN IMMEDIATE")
        consume(db, grant, event, owned, wire, key)


def test_open_partial_entry_blocks():
    event, owned, wire, key = inputs()
    owned["status"] = "PARTIAL"
    with pytest.raises(ValueError, match="TERMINAL"):
        grant_for(event, owned, wire, key)
