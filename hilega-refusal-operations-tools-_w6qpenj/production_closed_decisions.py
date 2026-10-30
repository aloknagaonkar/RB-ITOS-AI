import re
"""Pinned-account signed refusal records. No transport or release authority."""
from datetime import datetime
import hashlib
import hmac
import json

from market_lab.hilega_production_account_adapter_v1 import sign

FLAGS = (
    "database_modified", "transport_attempt_created", "broker_reads_performed",
    "entry_permission", "exit_submission_permission", "orders_sent",
    "production_execution_enabled", "reservation_release_permission",
    "production_ready",
)


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def record(db, pin, *, request_id, source_fingerprint, report, assessed_at):
    need(re.fullmatch(r"UPSTOX:[0-9a-f]{64}", pin["scope"]) is not None,
         "PINNED_UPSTOX_SCOPE_REQUIRED")
    need(db.in_transaction, "CALLER_TRANSACTION_REQUIRED")
    need(isinstance(request_id, str) and 0 < len(request_id) <= 200,
         "REQUEST_ID_REQUIRED")
    need(isinstance(source_fingerprint, str)
         and len(source_fingerprint) == 64
         and all(c in "0123456789abcdef" for c in source_fingerprint),
         "SOURCE_FINGERPRINT_REQUIRED")
    at = datetime.fromisoformat(assessed_at)
    need(at.tzinfo is not None and at.utcoffset() is not None,
         "AWARE_ASSESSMENT_REQUIRED")
    need(report.get("model") == "HILEGA_CLOSED_ENTRY_DISPATCH_V1"
         and report.get("status") == "DISPATCH_REFUSED_LIVE_GATE_CLOSED",
         "CLOSED_DISPATCH_REPORT_REQUIRED")
    need(all(report.get(k) is False for k in FLAGS),
         "CLOSED_REPORT_FLAGS_REQUIRED")

    key = sha([pin["scope"], request_id, source_fingerprint])
    payload = dict(
        model="HILEGA_APPLICATION_CLOSED_DISPATCH_DECISION_V1",
        account_scope=pin["scope"], request_id=request_id,
        source_fingerprint=source_fingerprint,
        report_fingerprint=sha(report), report=report,
        assessed_at=at.isoformat(),
        production_execution_enabled=False,
        reservation_release_permission=False,
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS preparation_closed_dispatch_decisions("
        "id TEXT PRIMARY KEY,data TEXT NOT NULL)")
    existing = db.execute(
        "SELECT data FROM preparation_closed_dispatch_decisions WHERE id=?", (key,)
    ).fetchone()
    if existing:
        row = json.loads(existing[0])
        signature = row.pop("signature", None)
        need(isinstance(signature, str)
             and hmac.compare_digest(sign(row, pin), signature),
             "PERSISTED_DECISION_SIGNATURE_INVALID")
        # Reassessment time alone does not duplicate the decision.
        comparison = dict(payload, assessed_at=row["assessed_at"])
        need(row == comparison, "DECISION_REPLAY_CONFLICT")
        return dict(decision_id=key, idempotent_replay=True)

    payload["signature"] = sign(payload, pin)
    db.execute(
        "INSERT INTO preparation_closed_dispatch_decisions VALUES(?,?)",
        (key, canonical(payload)),
    )
    return dict(decision_id=key, idempotent_replay=False)