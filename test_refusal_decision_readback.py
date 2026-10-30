"""Readback tests; synthetic account pins and temporary databases only."""
import json
import sqlite3

import pytest

from refusal_decision_readback import inspect
from test_production_refusal_candidate import (
    prepared, verify_candidate, env, bound_env, invoke, rows, TABLE,
)
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_production_account_adapter_v1 import sign


def test_authenticated_readback_changes_no_bytes(prepared):
    e = prepared
    result = invoke(e)
    before = e["store"].path.read_bytes()
    report = inspect(
        e["store"].path, PIN, decision_id=result["decision_id"])
    assert report["authenticated_record_count"] == 1
    assert report["database_modified"] is False
    assert report["current_dispatch_eligibility_verified"] is False
    assert e["store"].path.read_bytes() == before


def test_absent_table_is_not_created(prepared):
    e = prepared
    before = e["store"].path.read_bytes()
    assert inspect(e["store"].path, PIN)["authenticated_record_count"] == 0
    assert e["store"].path.read_bytes() == before


def test_tampered_record_rejected(prepared):
    e = prepared
    invoke(e)
    key, raw = rows(e)[0]
    value = json.loads(raw)
    value["assessed_at"] = "2026-10-30T12:00:00+05:30"
    with e["store"].db() as db:
        db.execute("UPDATE " + TABLE + " SET data=? WHERE id=?",
                   (json.dumps(value), key))
    with pytest.raises(ValueError, match="^DECISION_SIGNATURE_INVALID$"):
        inspect(e["store"].path, PIN)


def test_wrong_account_rejected(prepared):
    e = prepared
    invoke(e)
    with pytest.raises(ValueError, match="^DECISION_ACCOUNT_SCOPE_MISMATCH$"):
        inspect(e["store"].path, dict(PIN, scope="UPSTOX:" + "a" * 64))


def test_lost_result_can_be_inspected_without_retry(prepared):
    e = prepared

    class LostResult(BaseException):
        pass

    with pytest.raises(LostResult):
        invoke(e)
        raise LostResult()
    before = rows(e)
    report = inspect(e["store"].path, PIN)
    assert report["authenticated_record_count"] == 1
    assert report["automatic_write_retry"] is False
    assert rows(e) == before


def test_resigned_inconsistent_report_rejected(prepared):
    e = prepared
    invoke(e)
    key, raw = rows(e)[0]
    value = json.loads(raw)
    value["report"]["review_reasons"] = ["SYNTHETIC_CHANGE"]
    value.pop("signature")
    value["signature"] = sign(value, PIN)
    with e["store"].db() as db:
        db.execute("UPDATE " + TABLE + " SET data=? WHERE id=?",
                   (json.dumps(value), key))
    with pytest.raises(ValueError, match="^DECISION_REPORT_FINGERPRINT_MISMATCH$"):
        inspect(e["store"].path, PIN)