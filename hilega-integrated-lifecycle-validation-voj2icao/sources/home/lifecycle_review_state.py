"""Fixture-only durable lifecycle reviews. No live ownership or permission."""
import hmac
import json

from lifecycle_signal_review import review_journal_lifecycle
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import (
    sign, aware,
)

CURRENT = "fixture_lifecycle_current"
HISTORY = "fixture_lifecycle_history"
MODEL = "HILEGA_FIXTURE_LIFECYCLE_REVIEW_STATE_V1"
FLAGS = (
    "strategy_ownership_verified", "entry_permission",
    "exit_submission_permission", "reservation_release_permission",
    "production_execution_enabled", "orders_sent", "production_ready",
)


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def authenticate(row, pin):
    value = dict(row)
    signature = value.pop("signature", None)
    need(isinstance(signature, str)
         and hmac.compare_digest(sign(value, pin), signature),
         "LIFECYCLE_STATE_SIGNATURE_INVALID")
    need(value["model"] == MODEL and value["account_scope"] == pin["scope"]
         and all(value.get(flag) is False for flag in FLAGS),
         "LIFECYCLE_STATE_SCOPE_OR_AUTHORITY_INVALID")
    return row


def read_current(db, pin):
    need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_SCOPE_REQUIRED")
    exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (CURRENT,),
    ).fetchone()
    if not exists:
        return None
    found = db.execute(
        "SELECT data FROM " + CURRENT + " WHERE id=1"
    ).fetchone()
    return authenticate(json.loads(found[0]), pin) if found else None


def record_review(
    db, pin, snapshot, *, read_source, entry_id, journal, exit_sequences,
    clock, checkpoint=lambda stage: None,
):
    """Caller commits/rolls back; source reader must return current evidence.

    This stores informational fixture evidence only. Its current row is not
    an execution clearance and reading it does not certify current freshness.
    """
    need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_SCOPE_REQUIRED")
    need(db.in_transaction, "CALLER_TRANSACTION_REQUIRED")
    source = read_source()
    need(source["mode"] == "OFFLINE_FIXTURE"
         and source["scope"] == pin["scope"], "FIXTURE_SOURCE_REQUIRED")
    sequences = list(exit_sequences)
    capture_id = snapshot.get("snapshot_id")
    need(isinstance(capture_id, str) and 0 < len(capture_id) <= 200
         and capture_id.strip() == capture_id
         and not any(ord(c) < 32 for c in capture_id),
         "CAPTURE_ID_INVALID")
    input_fp = sha(dict(
        source=source, snapshot=snapshot, entry_id=entry_id,
        exit_sequences=sequences,
    ))
    previous = read_current(db, pin)
    db.execute(
        "CREATE TABLE IF NOT EXISTS " + HISTORY +
        "(id TEXT PRIMARY KEY,input_fingerprint TEXT NOT NULL,data TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS " + CURRENT +
        "(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL)"
    )
    old = db.execute(
        "SELECT input_fingerprint,data FROM " + HISTORY + " WHERE id=?",
        (capture_id,),
    ).fetchone()
    if old:
        saved = authenticate(json.loads(old[1]), pin)
        need(old[0] == saved["input_fingerprint"] == input_fp,
             "CAPTURE_ID_OR_SOURCE_CONFLICT")
        need(previous is not None, "CURRENT_STATE_MISSING")
        return dict(
            status="HISTORICAL_REPLAY_CURRENT_STATE_RETURNED",
            idempotent_replay=True, current=previous,
            current_freshness_revalidated=False,
            production_execution_enabled=False,
        )

    if previous:
        need(aware(snapshot["generated_at"])
             > aware(previous["capture_generated_at"]),
             "OUT_OF_ORDER_OR_EQUAL_CAPTURE")

    result = review_journal_lifecycle(
        source, snapshot, pin, entry_id=entry_id,
        as_of=clock().isoformat(), journal=journal,
        exit_sequences=sequences,
    )
    row = dict(
        {flag: False for flag in FLAGS},
        model=MODEL, account_scope=pin["scope"],
        snapshot_id=capture_id,
        capture_generated_at=snapshot["generated_at"],
        capture_completed_at=snapshot["completed_at"],
        input_fingerprint=input_fp,
        source_fingerprint=sha(source),
        snapshot=snapshot, report=result,
        scope="INFORMATIONAL_FIXTURE_LIFECYCLE_REVIEW_ONLY",
    )
    row["signature"] = sign(row, pin)
    raw = encode(row)
    db.execute(
        "INSERT INTO " + HISTORY + " VALUES(?,?,?)",
        (capture_id, input_fp, raw),
    )
    checkpoint("AFTER_HISTORY_INSERT")
    db.execute(
        "INSERT OR REPLACE INTO " + CURRENT + " VALUES(1,?)", (raw,)
    )
    checkpoint("BEFORE_COMMIT_VALIDATION")
    fresh_source = read_source()
    need(sha(fresh_source) == sha(source),
         "SOURCE_CHANGED_BEFORE_COMMIT")
    final = review_journal_lifecycle(
        fresh_source, snapshot, pin, entry_id=entry_id,
        as_of=clock().isoformat(), journal=journal,
        exit_sequences=sequences,
    )
    # assessed_at may advance; all other reviewed evidence must stay identical.
    first = {k: v for k, v in result.items() if k != "assessed_at"}
    last = {k: v for k, v in final.items() if k != "assessed_at"}
    need(first == last, "REVIEW_CHANGED_BEFORE_COMMIT")
    return dict(
        status="LIFECYCLE_REVIEW_STAGED_CALLER_COMMIT_REQUIRED",
        idempotent_replay=False, current=row,
        production_execution_enabled=False,
    )
