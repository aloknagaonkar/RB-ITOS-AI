"""Staged durable exit references. No order body, transport or release authority.

Not connected to the running application. An exit reference is an intention,
never evidence that an exit was submitted, filled or that exposure is flat.
"""
from contextlib import closing
import json
import hmac
import os
from pathlib import Path
import sqlite3
from bridge import correlate, ident
from historical_receipt_checks import sha
from risk_evidence_audit import need, regular
from signature_checks import aware, day, sign

MODEL = "HILEGA_STAGED_EXIT_REFERENCE_V1"


def create_reference(source, snapshot, pin, *, entry_request_id,
                     exit_key, quantity, reason, as_of):
    """Build a non-executable exit intention from current verified references."""
    ident(entry_request_id); ident(exit_key); ident(reason)
    need(type(quantity) is int and quantity > 0, "EXIT_QUANTITY_INVALID")
    review = correlate(source, snapshot, pin, as_of=as_of)
    position = review["position_reference_review"]
    need(position["current_entry_buy_position_quantities_match"] is True,
         "CURRENT_ENTRY_POSITION_REFERENCE_REQUIRED")
    rows = {key:json.loads(raw) for key, fp, raw in source["requests"]}
    need(entry_request_id in rows and entry_request_id in source["bindings"],
         "BOUND_PARENT_ENTRY_REQUIRED")
    entry = rows[entry_request_id]
    order = next((o for o in snapshot["orders"]
                  if o["order_id"] == entry.get("order_id")), None)
    need(order is not None and order["side"] == "BUY",
         "CURRENT_PARENT_BUY_ORDER_REQUIRED")
    need(order["status"] in {"FILLED", "CANCELLED", "REJECTED"},
         "PARENT_ENTRY_MUST_BE_TERMINAL")
    need(0 < quantity <= order["filled"], "EXIT_EXCEEDS_PARENT_FILLED_QUANTITY")
    # Same-symbol aggregation cannot choose which entry an exit reduces.
    siblings = [o for o in snapshot["orders"] if
                (o["instrument"],o["product"]) ==
                (order["instrument"],order["product"]) and o["filled"] > 0]
    need(len(siblings) == 1, "MULTIPLE_ENTRIES_REQUIRE_EXPLICIT_ALLOCATION")
    stable = dict(model=MODEL, account_scope=pin["scope"],
        session_date=day(aware(as_of)), parent_request_id=entry_request_id,
        parent_request_fingerprint=source["bindings"][entry_request_id]["request_fingerprint"],
        parent_order_fingerprint=sha(order["order_id"]), exit_key=exit_key,
        instrument=order["instrument"], product=order["product"],
        side="SELL", quantity=quantity, reason=reason)
    reference = dict(stable, id=sha([pin["scope"],entry_request_id,exit_key]),
        intent_fingerprint=sha(stable), created_at=as_of,
        account_capture_fingerprint=sha(snapshot),
        status="UNSENT_EXIT_REFERENCE_REQUIRES_REVIEW",
        source_atomic=False, executable_request_created=False,
        strategy_ownership_verified=False, orders_sent=False,
        entry_permission=False, production_execution_enabled=False,
        reservation_release_permission=False, production_ready=False)
    reference["signature"] = sign(reference,pin)
    return reference


def validate_reference(reference,pin,*,as_of):
    # Verify local integrity and the fresh creation timestamp again at commit.
    payload=dict(reference);signature=payload.pop("signature",None)
    import hmac
    need(isinstance(signature,str) and hmac.compare_digest(
        sign(payload,pin),signature),"EXIT_REFERENCE_SIGNATURE_INVALID")
    need(reference["account_scope"]==pin["scope"] and reference["model"]==MODEL,
         "EXIT_REFERENCE_SCOPE_INVALID")
    stable={k:reference[k] for k in (
        "model","account_scope","session_date","parent_request_id",
        "parent_request_fingerprint","parent_order_fingerprint","exit_key",
        "instrument","product","side","quantity","reason")}
    need(sha(stable)==reference["intent_fingerprint"]
         and reference["id"]==sha([pin["scope"],
             reference["parent_request_id"],reference["exit_key"]]),
         "EXIT_REFERENCE_FINGERPRINT_INVALID")
    need(reference["side"]=="SELL" and type(reference["quantity"]) is int
         and reference["quantity"]>0,"EXIT_REFERENCE_QUANTITY_OR_SIDE_INVALID")
    need(all(reference[k] is False for k in (
        "orders_sent","production_execution_enabled","entry_permission",
        "reservation_release_permission","production_ready",
        "strategy_ownership_verified","executable_request_created")),
        "EXIT_REFERENCE_AUTHORITY_FORBIDDEN")
    age=(aware(as_of)-aware(reference["created_at"])).total_seconds()
    need(0<=age<=10 and day(aware(as_of))==reference["session_date"],
         "EXIT_REFERENCE_STALE_OR_FUTURE")


class ReferenceStore:
    """Separate staged ledger, created only with an explicit fresh path.

    It cannot open/adopt application, adapter, ownership or fixture databases.
    A single parent can have only one pending exit reference. There is no API
    to clear it or claim a fill; future acknowledged lifecycle work is required.
    """
    def __init__(self,path,pin):
        self.path=regular(path); self.pin=pin
        with self.path.open("rb") as stream:
            header=stream.read(20)
        need(header[:16]==b"SQLite format 3\x00" and header[18:20]==b"\x01\x01",
             "EXIT_REFERENCE_DELETE_JOURNAL_REQUIRED")
        with self.connection() as db:
            row=db.execute("SELECT data FROM exit_reference_meta WHERE id=1").fetchone()
            need(row is not None and json.loads(row[0]) ==
                 dict(model=MODEL,scope=pin["scope"],mode="STAGED_REFERENCE_ONLY"),
                 "EXIT_REFERENCE_STORE_SCOPE_OR_MODE_MISMATCH")

    @classmethod
    def create(cls,path,pin):
        path=Path(path).absolute()
        for parent in path.parents:
            need(not parent.is_symlink(),"SYMLINK_PARENT_FORBIDDEN")
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600)
        os.close(fd)
        with closing(sqlite3.connect(path)) as db,db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE exit_reference_meta(id INTEGER PRIMARY KEY,data TEXT)")
            db.execute("INSERT INTO exit_reference_meta VALUES(1,?)",(json.dumps(
                dict(model=MODEL,scope=pin["scope"],mode="STAGED_REFERENCE_ONLY")),))
            db.execute("CREATE TABLE exit_references(id TEXT PRIMARY KEY,parent TEXT UNIQUE,fingerprint TEXT,data TEXT)")
        return cls(path,pin)

    def connection(self):
        return closing(sqlite3.connect(
            self.path.resolve().as_uri()+"?mode=rw",uri=True,timeout=10))

    def record(self,reference,*,as_of):
        validate_reference(reference,self.pin,as_of=as_of)
        with self.connection() as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                meta=db.execute("SELECT data FROM exit_reference_meta WHERE id=1").fetchone()
                need(meta is not None and json.loads(meta[0]) ==
                     dict(model=MODEL,scope=self.pin["scope"],mode="STAGED_REFERENCE_ONLY"),
                     "EXIT_REFERENCE_STORE_SCOPE_OR_MODE_MISMATCH")
                old=db.execute("SELECT fingerprint,data FROM exit_references WHERE id=?",
                               (reference["id"],)).fetchone()
                if old:
                    need(old[0]==reference["intent_fingerprint"],
                         "EXIT_KEY_REUSED_WITH_CHANGED_INTENT")
                    saved=json.loads(old[1]);saved_payload=dict(saved)
                    saved_signature=saved_payload.pop("signature",None)
                    need(isinstance(saved_signature,str) and hmac.compare_digest(
                        sign(saved_payload,self.pin),saved_signature),
                        "PERSISTED_EXIT_REFERENCE_SIGNATURE_INVALID")
                    db.rollback()
                    return dict(json.loads(old[1]),idempotent_replay=True)
                need(not db.execute("SELECT 1 FROM exit_references WHERE parent=?",
                    (reference["parent_request_id"],)).fetchone(),
                    "PENDING_EXIT_REFERENCE_ALREADY_EXISTS")
                db.execute("INSERT INTO exit_references VALUES(?,?,?,?)",
                    (reference["id"],reference["parent_request_id"],
                     reference["intent_fingerprint"],json.dumps(reference)))
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return dict(reference,idempotent_replay=False)
