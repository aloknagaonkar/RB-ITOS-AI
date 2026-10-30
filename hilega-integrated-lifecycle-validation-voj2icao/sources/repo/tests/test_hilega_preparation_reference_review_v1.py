import json
import os
import sqlite3
from contextlib import closing

import pytest

from test_hilega_application_preparation_v1 import env, process
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.evidence import Blocked
from market_lab.hilega_preparation_runtime_v1.reference_review import review


def run(env, pin=PIN):
    return review(
        env["store"].path, os.environ["HILEGA_PREPARATION_ADAPTER_DB"], pin,
    )


def dump(path):
    with closing(sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro", uri=True,
    )) as db:
        return list(db.iterdump())


def test_real_source_records_are_checked_without_writes_or_authority(env):
    process(env)
    before = dump(env["store"].path)
    calls = len(env["calls"])
    result = run(env)
    assert result["status"] == "UNSENT_PREPARATION_REFERENCES_CHECKED"
    assert result["reference_count"] == 1
    assert result["historical_assessment_only"] is True
    for key in (
        "application_hold_link_verified", "broker_order_ownership_verified",
        "strategy_ownership_verified", "real_funds_reservation_verified",
        "reservation_release_permission", "production_execution_enabled",
        "entry_permission", "production_ready", "broker_reads_performed",
    ):
        assert result[key] is False
    assert dump(env["store"].path) == before
    assert len(env["calls"]) == calls


def test_empty_application_is_not_a_verified_link(env):
    result = run(env)
    assert result["status"] == "NO_PREPARATION_RECORDS"
    assert result["reference_count"] == 0
    assert result["application_hold_link_verified"] is False


@pytest.mark.parametrize("case", [
    "missing_hold", "hold_amount", "real_cash_claim", "outbox_reference",
    "outbox_quantity", "executable_body", "permission", "evidence",
])
def test_changed_application_references_are_rejected(env, case):
    process(env)
    table = (
        "preparation_shadow_holds" if case in {
            "hold_amount", "real_cash_claim",
        } else "preparation_plans" if case == "permission"
        else "preparation_evidence" if case == "evidence"
        else "preparation_outbox"
    )
    with env["store"].db() as db:
        if case == "missing_hold":
            db.execute("DELETE FROM preparation_shadow_holds")
        else:
            raw = db.execute("SELECT data FROM " + table).fetchone()[0]
            row = json.loads(raw)
            if case == "hold_amount":
                row["held_cents"] -= 1
            elif case == "real_cash_claim":
                row["real_cash_reserved"] = True
            elif case == "outbox_reference":
                row["reservation_reference"] = "another-hold"
            elif case == "outbox_quantity":
                row["quantity"] += 65
            elif case == "executable_body":
                row["request_body"] = {"quantity": 65}
            elif case == "permission":
                row["entry_permission"] = True
            else:
                row["spot_initial"] += 1
            db.execute(
                "UPDATE " + table + " SET data=?", (json.dumps(row),),
            )
    before = dump(env["store"].path)
    with pytest.raises(Blocked):
        run(env)
    assert dump(env["store"].path) == before


def test_broker_activity_cannot_be_adopted_into_unsent_preparation(env):
    process(env)
    with sqlite3.connect(
        os.environ["HILEGA_PREPARATION_ADAPTER_DB"]
    ) as db:
        db.execute("INSERT INTO requests VALUES('unexpected-request')")
    with pytest.raises(Blocked, match="UNEXPECTED_ADAPTER_ACTIVITY"):
        run(env)


def test_wrong_account_scope_is_rejected(env):
    process(env)
    wrong_pin = {**PIN, "scope": "UPSTOX:" + "c" * 64}
    with pytest.raises(Blocked, match="ACCOUNT_SCOPE"):
        run(env, wrong_pin)
