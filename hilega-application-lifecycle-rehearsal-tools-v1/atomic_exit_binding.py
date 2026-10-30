"""Fixture-only attached transaction for an unsent exit and disabled request.
Not installed into the application. No broker transport or production writes.
"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from adapter_reference.adapter import validated_request, encode
from exit_intent import MODEL, validate_reference
from historical_receipt_checks import sha
from risk_evidence_audit import regular, need


def rollback_database(path):
    path=regular(path)
    with path.open("rb") as stream:
        header=stream.read(20)
    need(header[:16]==b"SQLite format 3\x00" and header[18:20]==b"\x01\x01",
         "ROLLBACK_JOURNAL_REQUIRED")
    for suffix in ("-wal","-shm","-journal"):
        need(not Path(str(path)+suffix).exists(),"DATABASE_SIDECAR_REQUIRES_REVIEW")
    return path


def bind_fixture_exit(reference_path,adapter_path,pin,reference,draft,*,
                      direction,as_of,checkpoint=lambda stage:None):
    need(pin["scope"].startswith("FIXTURE:"),"FIXTURE_ACCOUNT_REQUIRED")
    validate_reference(reference,pin,as_of=as_of)
    need(reference["status"]=="UNSENT_EXIT_REFERENCE_REQUIRES_REVIEW",
         "UNSENT_EXIT_REFERENCE_REQUIRED")
    row,fp=validated_request(draft,signal_id=reference["id"],
        signal_at=reference["created_at"],direction=direction,
        reservation_reference=reference["parent_request_id"],as_of=as_of)
    body=row["draft"]["body"]
    need(row["request_id"]==reference["id"] and body["transaction_type"]=="SELL"
         and body["instrument_token"]==reference["instrument"]
         and body["product"]==reference["product"]
         and body["quantity"]==reference["quantity"],"EXIT_REQUEST_CONTRACT_MISMATCH")
    app,adapter=map(rollback_database,(reference_path,adapter_path))
    need(not app.samefile(adapter),"DISTINCT_DATABASES_REQUIRED")
    need(app.stat().st_dev==adapter.stat().st_dev,"SAME_FILESYSTEM_REQUIRED")
    with closing(sqlite3.connect(app.resolve().as_uri()+"?mode=rw",
                                uri=True,timeout=15)) as db:
        db.execute("ATTACH DATABASE ? AS broker",
                   (adapter.resolve().as_uri()+"?mode=rw",))
        for schema in ("main","broker"):
            need(db.execute("PRAGMA "+schema+".journal_mode").fetchone()[0]=="delete",
                 "DELETE_JOURNAL_REQUIRED")
            db.execute("PRAGMA "+schema+".synchronous=FULL")
            need(db.execute("PRAGMA "+schema+".synchronous").fetchone()[0]>=2,
                 "FULL_DURABILITY_REQUIRED")
        db.execute("BEGIN IMMEDIATE")
        try:
            meta=db.execute("SELECT data FROM main.exit_reference_meta WHERE id=1").fetchone()
            need(meta is not None and json.loads(meta[0])==dict(
                model=MODEL,scope=pin["scope"],mode="STAGED_REFERENCE_ONLY"),
                "EXIT_REFERENCE_STORE_SCOPE_OR_MODE_MISMATCH")
            meta=db.execute("SELECT data FROM broker.meta WHERE id=1").fetchone()
            need(meta is not None and json.loads(meta[0])==dict(
                scope=pin["scope"],mode="OFFLINE_FIXTURE"),"FIXTURE_ADAPTER_REQUIRED")
            parent=db.execute("SELECT fingerprint,data FROM broker.requests WHERE id=?",
                             (reference["parent_request_id"],)).fetchone()
            need(parent is not None and parent[0]==reference["parent_request_fingerprint"],
                 "PARENT_REQUEST_CHANGED_OR_MISSING")
            parentrow=json.loads(parent[1])
            need(parentrow["direction"]==direction
                 and parentrow["draft"]["body"]["transaction_type"]=="BUY"
                 and parentrow["draft"]["body"]["instrument_token"]==reference["instrument"]
                 and parentrow["draft"]["body"]["product"]==reference["product"],
                 "PARENT_ENTRY_CONTRACT_MISMATCH")
            stable={k:parentrow[k] for k in ("request_id","draft","signal_id",
                "signal_at","direction","reservation_reference")}
            need(sha(stable)==parent[0] and
                 sha(parentrow.get("order_id"))==reference["parent_order_fingerprint"],
                 "PARENT_ACK_REFERENCE_CHANGED")
            db.execute("CREATE TABLE IF NOT EXISTS exit_request_bindings("
                       "id TEXT PRIMARY KEY,data TEXT NOT NULL)")
            old=db.execute("SELECT data FROM exit_request_bindings WHERE id=?",
                           (reference["id"],)).fetchone()
            if old:
                binding=json.loads(old[0])
                need(binding["request_fingerprint"]==fp and
                     binding["intent_fingerprint"]==reference["intent_fingerprint"],
                     "ATOMIC_EXIT_BINDING_CONFLICT")
                saved=db.execute("SELECT data FROM exit_references WHERE id=?",
                                 (reference["id"],)).fetchone()
                request=db.execute("SELECT fingerprint,data FROM broker.requests WHERE id=?",
                                   (reference["id"],)).fetchone()
                need(saved is not None and request is not None
                     and sha(json.loads(saved[0]))==binding["reference_fingerprint"]
                     and request[0]==fp and json.loads(request[1])==row,
                     "ATOMIC_EXIT_BINDING_REFERENCES_CHANGED")
                db.rollback()
                return dict(status="ATOMIC_DISABLED_EXIT_REPLAY",idempotent_replay=True,
                            production_execution_enabled=False,orders_sent=False)
            need(not db.execute("SELECT 1 FROM exit_references WHERE parent=?",
                (reference["parent_request_id"],)).fetchone(),
                "PENDING_EXIT_REFERENCE_ALREADY_EXISTS")
            need(not db.execute("SELECT 1 FROM broker.requests WHERE id=?",
                (reference["id"],)).fetchone(),"EXIT_REQUEST_ALREADY_EXISTS")
            db.execute("INSERT INTO exit_references VALUES(?,?,?,?)",(
                reference["id"],reference["parent_request_id"],
                reference["intent_fingerprint"],encode(reference)))
            checkpoint("AFTER_EXIT_REFERENCE")
            db.execute("INSERT INTO broker.requests VALUES(?,?,?)",
                       (row["request_id"],fp,encode(row)))
            checkpoint("AFTER_ADAPTER_REQUEST")
            binding=dict(id=reference["id"],parent_request_id=reference["parent_request_id"],
                account_scope=pin["scope"],request_fingerprint=fp,
                intent_fingerprint=reference["intent_fingerprint"],
                reference_fingerprint=sha(reference),status="ATOMIC_DISABLED_EXIT_BOUND",
                executable_request_created=False,orders_sent=False,
                strategy_ownership_verified=False,production_execution_enabled=False,
                reservation_release_permission=False)
            db.execute("INSERT INTO exit_request_bindings VALUES(?,?)",
                       (reference["id"],encode(binding)))
            db.execute("INSERT INTO broker.events(data) VALUES(?)",(encode(dict(
                type="FIXTURE_EXIT_DISABLED_REQUEST_BOUND",
                request_id=reference["id"],parent_request_id=reference["parent_request_id"])),))
            checkpoint("BEFORE_COMMIT")
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return dict(status="ATOMIC_DISABLED_EXIT_FIXTURE_BOUND",idempotent_replay=False,
        fixture_only=True,runtime_integration=False,orders_sent=False,
        production_execution_enabled=False,reservation_release_permission=False,
        production_ready=False)
