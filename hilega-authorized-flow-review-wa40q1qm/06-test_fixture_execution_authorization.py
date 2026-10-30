from copy import deepcopy
import sqlite3

import pytest

from fixture_execution_authorization import issue, claim

PIN = {"scope": "FIXTURE:EXECUTION-AUTH", "key": "44" * 32}
AT = "2026-10-30T10:00:00+05:30"
WIRE = dict(
    method="POST", host="api-hft.upstox.com", path="/v3/order/place",
    body=dict(transaction_type="BUY", order_type="LIMIT",
              quantity=65, price=100),
)


@pytest.fixture
def db(tmp_path):
    connection = sqlite3.connect(tmp_path / "authorization.sqlite")
    connection.execute("BEGIN IMMEDIATE")
    yield connection
    connection.rollback()
    connection.close()


def grant():
    return issue(
        PIN, request_id="entry", wire=WIRE,
        budget_paise=660000, fee_buffer_paise=10000, at=AT)


def use(db, authorization, **changes):
    args = dict(request_id="entry", wire=WIRE, at=AT, attempt_id="attempt-1")
    args.update(changes)
    return claim(db, authorization, PIN, **args)


def test_valid_claim_is_single_use(db):
    authorization = grant()
    assert use(db, authorization)["production_execution_enabled"] is False
    with pytest.raises(ValueError, match="^AUTHORIZATION_ALREADY_CONSUMED$"):
        use(db, authorization)


def test_missing_authorization_blocks(db):
    with pytest.raises(ValueError, match="^AUTHORIZATION_REQUIRED$"):
        use(db, None)


def test_tampered_budget_blocks(db):
    authorization = grant()
    authorization["budget_paise"] += 1
    with pytest.raises(ValueError, match="^AUTHORIZATION_SIGNATURE_INVALID$"):
        use(db, authorization)


@pytest.mark.parametrize("case", ["request", "wire"])
def test_binding_mismatch_blocks(db, case):
    changes = {}
    if case == "request":
        changes["request_id"] = "another-entry"
    else:
        wire = deepcopy(WIRE)
        wire["body"]["quantity"] = 130
        changes["wire"] = wire
    with pytest.raises(ValueError, match="^AUTHORIZATION_BINDING_MISMATCH$"):
        use(db, grant(), **changes)


def test_exact_expiry_blocks(db):
    with pytest.raises(ValueError, match="^AUTHORIZATION_EXPIRED_OR_FUTURE$"):
        use(db, grant(), at="2026-10-30T10:00:10+05:30")


def test_rollback_does_not_spend_authorization(db):
    authorization = grant()
    use(db, authorization)
    db.rollback()
    db.execute("BEGIN IMMEDIATE")
    assert use(db, authorization)["fixture_authorization_claimed"] is True


def test_real_account_cannot_receive_fixture_authorization():
    with pytest.raises(ValueError, match="^FIXTURE_ACCOUNT_REQUIRED$"):
        issue(
            dict(PIN, scope="UPSTOX:" + "a" * 64),
            request_id="entry", wire=WIRE,
            budget_paise=660000, fee_buffer_paise=10000, at=AT)