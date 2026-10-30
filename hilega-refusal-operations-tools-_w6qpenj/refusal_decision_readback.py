"""Read-only authentication of persisted closed-dispatch decisions."""
from contextlib import closing
from datetime import datetime
import hmac
import json
from pathlib import Path
import re
import sqlite3

from market_lab.hilega_production_account_adapter_v1 import sign
from production_closed_decisions import FLAGS, sha

TABLE = "preparation_closed_dispatch_decisions"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def inspect(application, pin, *, decision_id=None):
    path = Path(application).absolute()
    need(path.is_file() and not path.is_symlink()
         and not any(p.is_symlink() for p in path.parents),
         "REGULAR_APPLICATION_DATABASE_REQUIRED")
    need(re.fullmatch(r"UPSTOX:[0-9a-f]{64}", pin["scope"]) is not None,
         "PINNED_UPSTOX_SCOPE_REQUIRED")
    if decision_id is not None:
        need(re.fullmatch(r"[0-9a-f]{64}", decision_id) is not None,
             "DECISION_ID_INVALID")

    with closing(sqlite3.connect(
        path.as_uri() + "?mode=ro", uri=True, timeout=10
    )) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE,),
        ).fetchone()
        if not exists:
            rows = []
        elif decision_id is None:
            rows = db.execute(
                "SELECT id,data FROM " + TABLE + " ORDER BY rowid LIMIT 1001"
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id,data FROM " + TABLE + " WHERE id=?",
                (decision_id,),
            ).fetchall()
        db.rollback()

    need(len(rows) <= 1000, "DECISION_READBACK_LIMIT_EXCEEDED")
    for key, raw in rows:
        value = json.loads(raw)
        signature = value.pop("signature", None)
        need(value["account_scope"] == pin["scope"],
             "DECISION_ACCOUNT_SCOPE_MISMATCH")
        need(isinstance(signature, str)
             and hmac.compare_digest(sign(value, pin), signature),
             "DECISION_SIGNATURE_INVALID")
        need(value["model"] == "HILEGA_APPLICATION_CLOSED_DISPATCH_DECISION_V1"
             and value["production_execution_enabled"] is False
             and value["reservation_release_permission"] is False,
             "DECISION_MODEL_OR_AUTHORITY_INVALID")
        need(isinstance(value["request_id"], str)
             and 0 < len(value["request_id"]) <= 200
             and re.fullmatch(r"[0-9a-f]{64}", value["source_fingerprint"]) is not None,
             "DECISION_REFERENCE_INVALID")
        need(key == sha([
            pin["scope"], value["request_id"], value["source_fingerprint"]
        ]), "DECISION_IDENTITY_MISMATCH")
        at = datetime.fromisoformat(value["assessed_at"])
        need(at.tzinfo is not None and at.utcoffset() is not None,
             "AWARE_DECISION_TIMESTAMP_REQUIRED")
        report = value["report"]
        need(sha(report) == value["report_fingerprint"],
             "DECISION_REPORT_FINGERPRINT_MISMATCH")
        need(report.get("model") == "HILEGA_CLOSED_ENTRY_DISPATCH_V1"
             and report.get("status") == "DISPATCH_REFUSED_LIVE_GATE_CLOSED"
             and all(report.get(flag) is False for flag in FLAGS),
             "DECISION_REPORT_AUTHORITY_INVALID")

    return dict(
        status=("AUTHENTICATED_REFUSAL_RECORDS_FOUND"
                if rows else "NO_MATCHING_REFUSAL_RECORD"),
        authenticated_record_count=len(rows),
        scope="HISTORICAL_REFUSAL_RECORDS_ONLY",
        current_dispatch_eligibility_verified=False,
        database_modified=False,
        automatic_write_retry=False,
        orders_sent=False,
        production_execution_enabled=False,
        reservation_release_permission=False,
        production_ready=False,
    )