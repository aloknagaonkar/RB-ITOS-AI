"""Fixture-only durable exit acknowledgement references, never fill authority."""
from contextlib import closing
import json
import sqlite3
from atomic_exit_binding import rollback_database
from exit_intent import MODEL, validate_reference
from historical_receipt_checks import _check, sha
from risk_evidence_audit import need
from signature_checks import aware, day


def bind_fixture_ack(reference_path,adapter_path,pin,exit_id,*,as_of,
                     checkpoint=lambda stage:None):
    need(pin["scope"].startswith("FIXTURE:"),"FIXTURE_ACCOUNT_REQUIRED")
    app,adapter=map(rollback_database,(reference_path,adapter_path))
    need(not app.samefile(adapter),"DISTINCT_DATABASES_REQUIRED")
    need(app.stat().st_dev==adapter.stat().st_dev,"SAME_FILESYSTEM_REQUIRED")
    with closing(sqlite3.connect(app.resolve().as_uri()+"?mode=rw",
                                uri=True,timeout=15)) as db:
        db.execute("ATTACH DATABASE ? AS broker",(adapter.resolve().as_uri()+"?mode=rw",))
        for schema in ("main","broker"):
            need(db.execute("PRAGMA "+schema+".journal_mode").fetchone()[0]=="delete",
                 "DELETE_JOURNAL_REQUIRED")
            db.execute("PRAGMA "+schema+".synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        try:
            meta=db.execute("SELECT data FROM exit_reference_meta WHERE id=1").fetchone()
            need(meta is not None and json.loads(meta[0])==dict(
                model=MODEL,scope=pin["scope"],mode="STAGED_REFERENCE_ONLY"),
                "EXIT_REFERENCE_STORE_SCOPE_OR_MODE_MISMATCH")
            meta=db.execute("SELECT data FROM broker.meta WHERE id=1").fetchone()
            need(meta is not None and json.loads(meta[0])==dict(
                scope=pin["scope"],mode="OFFLINE_FIXTURE"),"FIXTURE_ADAPTER_REQUIRED")
            found=db.execute("SELECT data FROM exit_request_bindings WHERE id=?",(exit_id,)).fetchone()
            need(found is not None,"ATOMIC_EXIT_BINDING_REQUIRED")
            binding=json.loads(found[0])
            found=db.execute("SELECT data FROM exit_references WHERE id=?",(exit_id,)).fetchone()
            need(found is not None,"EXIT_REFERENCE_REQUIRED")
            reference=json.loads(found[0])
            # Historical integrity check, not current-entry freshness clearance.
            validate_reference(reference,pin,as_of=reference["created_at"])
            need(aware(reference["created_at"])<=aware(as_of)
                 and day(aware(as_of))==reference["session_date"],
                 "ACK_BINDING_SESSION_OR_TIME_INVALID")
            need(reference["id"]==binding["id"]==exit_id
                 and binding["parent_request_id"]==reference["parent_request_id"]
                 and binding["account_scope"]==pin["scope"]
                 and binding["intent_fingerprint"]==reference["intent_fingerprint"]
                 and binding["reference_fingerprint"]==sha(reference)
                 and binding["status"]=="ATOMIC_DISABLED_EXIT_BOUND",
                 "ATOMIC_EXIT_REFERENCE_CHANGED")
            need(all(binding.get(k) is False for k in (
                "executable_request_created","orders_sent","strategy_ownership_verified",
                "production_execution_enabled","reservation_release_permission")),
                "EXIT_BINDING_AUTHORITY_FORBIDDEN")
            requests=db.execute("SELECT id,fingerprint,data FROM broker.requests ORDER BY rowid").fetchmany(10001)
            attempts=db.execute("SELECT id,request_id,operation,data FROM broker.attempts").fetchmany(10001)
            receiptrows=db.execute("SELECT id,data FROM broker.receipts").fetchmany(10001)
            need(max(len(requests),len(attempts),len(receiptrows))<=10000,
                 "SOURCE_RECORD_LIMIT_EXCEEDED")
            receipts=dict(receiptrows)
            need(len(receipts)==len(receiptrows),"DUPLICATE_RECEIPT_ID")
            reviewed=_check("OFFLINE_FIXTURE",requests,attempts,receipts)
            parent=next((r for r in requests if r[0]==reference["parent_request_id"]),None)
            need(parent is not None and parent[1]==reference["parent_request_fingerprint"]
                 and sha(json.loads(parent[2]).get("order_id"))==
                     reference["parent_order_fingerprint"],
                 "PARENT_ACK_REFERENCE_CHANGED")
            links=[v for v in reviewed["bindings"] if v["request_id"]==exit_id]
            need(len(links)==1,"EXIT_ACKNOWLEDGEMENT_UNRESOLVED_NO_RETRY")
            link=links[0]
            request=next((r for r in requests if r[0]==exit_id),None)
            need(request is not None and request[1]==binding["request_fingerprint"],
                 "EXIT_REQUEST_FINGERPRINT_CHANGED")
            need(link["signal_id"]==exit_id
                 and link["reservation_reference"]==reference["parent_request_id"]
                 and link["side"]=="SELL" and link["quantity"]==reference["quantity"]
                 and link["instrument"]==reference["instrument"]
                 and link["product"]==reference["product"],"EXIT_ACK_CONTRACT_MISMATCH")
            place=next(r for r in attempts if r[1]==exit_id and r[2]=="PLACE")
            value=dict(id=exit_id,parent_request_id=reference["parent_request_id"],
                order_id=link["order_id"],attempt_id=place[0],
                request_fingerprint=request[1],
                atomic_binding_fingerprint=sha(binding),
                receipt_fingerprint=sha(json.loads(receipts[place[0]])),
                recorded_at=as_of,status="ACKNOWLEDGED_NOT_FILLED_REFERENCE_ONLY",
                fill_confirmed=False,flat_confirmed=False,retry_allowed=False,
                strategy_ownership_verified=False,orders_sent=False,
                production_execution_enabled=False,
                reservation_release_permission=False,production_ready=False)
            stable={k:v for k,v in value.items() if k!="recorded_at"}
            fingerprint=sha(stable)
            db.execute("CREATE TABLE IF NOT EXISTS exit_acknowledgements("
                "id TEXT PRIMARY KEY,order_id TEXT UNIQUE,fingerprint TEXT,data TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS exit_ack_events("
                "seq INTEGER PRIMARY KEY AUTOINCREMENT,data TEXT)")
            old=db.execute("SELECT fingerprint,data FROM exit_acknowledgements WHERE id=?",
                           (exit_id,)).fetchone()
            if old:
                saved=json.loads(old[1])
                need(old[0]==fingerprint and sha({k:v for k,v in saved.items()
                    if k!="recorded_at"})==fingerprint,"EXIT_ACK_REFERENCE_CONFLICT")
                db.rollback()
                return dict(status="EXIT_ACK_REFERENCE_REPLAY",idempotent_replay=True,
                    fill_confirmed=False,flat_confirmed=False,retry_allowed=False,
                    production_execution_enabled=False,reservation_release_permission=False)
            db.execute("INSERT INTO exit_acknowledgements VALUES(?,?,?,?)",
                       (exit_id,link["order_id"],fingerprint,json.dumps(value)))
            checkpoint("AFTER_ACK_INSERT")
            db.execute("INSERT INTO exit_ack_events(data) VALUES(?)",
                       (json.dumps(dict(type="FIXTURE_EXIT_ACK_REFERENCE_BOUND",
                        exit_id=exit_id,at=as_of)),))
            checkpoint("BEFORE_COMMIT")
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return dict(status="EXIT_ACK_REFERENCE_FIXTURE_BOUND",idempotent_replay=False,
        fixture_only=True,fill_confirmed=False,flat_confirmed=False,
        retry_allowed=False,runtime_integration=False,
        production_execution_enabled=False,reservation_release_permission=False,
        production_ready=False)
