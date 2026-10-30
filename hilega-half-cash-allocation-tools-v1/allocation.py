"""Half-cash sizing and staged local reservations. No broker locking or transport."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
from cash_checks import verify_capture
from signature_checks import aware, day, sign

POLICY=dict(model="HILEGA_HALF_CASH_ENTRY_POLICY_V1",
    allocation_numerator=1,allocation_denominator=2,
    daily_loss_limit_paise=None,daily_loss_limit_required=False,
    fixed_max_entry_cost_paise=None,
    include_fee_buffer_in_entry_cap=True,
    maximum_active_local_entries=1,
    initial_maximum_lots=1)
MODEL="HILEGA_LOCAL_HALF_CASH_RESERVATION_V1"


def need(ok,reason):
    if not ok:raise ValueError(reason)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),
                                    allow_nan=False).encode()).hexdigest()


def identifier(value):
    need(isinstance(value,str) and 0<len(value)<=200 and value.strip()==value
         and not any(ord(c)<32 for c in value),"IDENTIFIER_INVALID")
    return value


def positive(value,reason):
    need(type(value) is int and value>0,reason)
    return value


def sizing(capture,pin,*,as_of,instrument,limit_price_paise,lot_size,
           freeze_quantity,fee_buffer_paise,max_lots=1):
    identifier(instrument)
    price=positive(limit_price_paise,"POSITIVE_INTEGER_PRICE_PAISE_REQUIRED")
    lot=positive(lot_size,"POSITIVE_INTEGER_LOT_SIZE_REQUIRED")
    freeze=positive(freeze_quantity,"POSITIVE_INTEGER_FREEZE_QUANTITY_REQUIRED")
    buffer=positive(fee_buffer_paise,"EXPLICIT_POSITIVE_FEE_BUFFER_REQUIRED")
    maximum=positive(max_lots,"EXPLICIT_POSITIVE_MAX_LOTS_REQUIRED")
    need(maximum==POLICY["initial_maximum_lots"],"INITIAL_ONE_LOT_POLICY_REQUIRED")
    evidence=verify_capture(capture,pin,as_of=as_of)
    now=aware(as_of)
    need(0<=(now-aware(capture["started_at"])).total_seconds()<=30,
         "CASH_SWEEP_START_STALE_OR_FUTURE")
    reasons=list(evidence["reasons"])
    cap=evidence["half_cash_cap_cents"]
    affordable=max(0,cap-buffer)//(price*lot)
    lots=min(maximum,freeze//lot,affordable)
    if cap==0:reasons.append("NO_CASH_CAPACITY")
    if lots==0:reasons.append("ONE_WHOLE_LOT_NOT_AFFORDABLE_OR_FROZEN")
    quantity=lots*lot
    total=quantity*price+buffer if lots else None
    return dict(model=MODEL,policy=dict(POLICY),account_scope=pin["scope"],
        session_date=evidence["session_date"],snapshot_id=evidence["snapshot_id"],
        assessed_at=as_of,instrument=instrument,available_cash_paise=evidence["cash_cents"],
        half_cash_cap_paise=cap,limit_price_paise=price,lot_size=lot,
        freeze_quantity=freeze,fee_buffer_paise=buffer,fee_buffer_is_provisional=True,
        lots=lots,quantity=quantity,proposed_total_paise=total,
        within_half_cash_cap=not reasons,pricing_and_contract_approval_verified=False,
        reasons=sorted(set(reasons)),daily_loss_limit_required=False,
        broker_cash_locked=False,real_funds_reservation_verified=False,
        entry_permission=False,orders_sent=False,production_execution_enabled=False,
        production_ready=False)


def existing_file(path):
    path=Path(path).absolute()
    need(path.is_file() and not path.is_symlink(),"REGULAR_EXISTING_BOOK_REQUIRED")
    for parent in path.parents:need(not parent.is_symlink(),"SYMLINK_PARENT_FORBIDDEN")
    with path.open("rb") as stream:header=stream.read(20)
    need(header[:16]==b"SQLite format 3\x00" and header[18:20]==b"\x01\x01",
         "DELETE_JOURNAL_BOOK_REQUIRED")
    return path


class ReservationBook:
    """Separate reference-only ledger; no production deployment or release API."""
    def __init__(self,path,pin):
        self.path=existing_file(path);self.pin=pin
        with self.connection() as db:self.metadata(db)

    @classmethod
    def create(cls,path,pin):
        path=Path(path).absolute()
        for parent in path.parents:need(not parent.is_symlink(),"SYMLINK_PARENT_FORBIDDEN")
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600)
        os.close(fd)
        with closing(sqlite3.connect(path)) as db,db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("CREATE TABLE allocation_meta(id INTEGER PRIMARY KEY,data TEXT)")
            db.execute("INSERT INTO allocation_meta VALUES(1,?)",(json.dumps(dict(
                scope=pin["scope"],mode="LOCAL_REFERENCE_ONLY",policy=POLICY)),))
            db.execute("CREATE TABLE holds(id TEXT PRIMARY KEY,fingerprint TEXT,data TEXT)")
            db.execute("CREATE TABLE allocation_events(seq INTEGER PRIMARY KEY,data TEXT)")
        return cls(path,pin)

    def connection(self):
        return closing(sqlite3.connect(self.path.resolve().as_uri()+"?mode=rw",
                                       uri=True,timeout=15))

    def metadata(self,db):
        row=db.execute("SELECT data FROM allocation_meta WHERE id=1").fetchone()
        need(row is not None and json.loads(row[0])==dict(scope=self.pin["scope"],
            mode="LOCAL_REFERENCE_ONLY",policy=POLICY),"BOOK_SCOPE_OR_POLICY_MISMATCH")

    def read_hold(self,raw):
        value=json.loads(raw);payload=dict(value)
        signature=payload.pop("signature",None)
        need(isinstance(signature,str) and hmac.compare_digest(
            sign(payload,self.pin),signature),"LOCAL_HOLD_SIGNATURE_INVALID")
        stable={k:value[k] for k in ("plan_id","account_scope","session_date",
            "instrument","quantity","limit_price_paise","fee_buffer_paise","policy")}
        need(digest(stable)==value["intent_fingerprint"]
             and value["account_scope"]==self.pin["scope"] and value["policy"]==POLICY,
             "LOCAL_HOLD_INTENT_INVALID")
        amount=value["quantity"]*value["limit_price_paise"]+value["fee_buffer_paise"]
        need(type(value["held_paise"]) is int and value["held_paise"]>0
             and value["held_paise"]==value["amount_paise"]==amount
             and amount<=value["cash_cap_at_reservation_paise"],"LOCAL_HOLD_AMOUNT_INVALID")
        return value

    def reserve(self,plan_id,capture,*,clock,checkpoint=lambda stage:None,**proposal):
        identifier(plan_id)
        checked=sizing(capture,self.pin,as_of=clock().isoformat(),**proposal)
        need(checked["within_half_cash_cap"],"HALF_CASH_PROPOSAL_BLOCKED")
        stable=dict(plan_id=plan_id,account_scope=self.pin["scope"],
            session_date=checked["session_date"],instrument=checked["instrument"],
            quantity=checked["quantity"],limit_price_paise=checked["limit_price_paise"],
            fee_buffer_paise=checked["fee_buffer_paise"],policy=POLICY)
        fingerprint=digest(stable)
        with self.connection() as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                self.metadata(db)
                # Recheck signature, cash coherence and age after acquiring lock.
                checked=sizing(capture,self.pin,as_of=clock().isoformat(),**proposal)
                need(checked["within_half_cash_cap"],"HALF_CASH_PROPOSAL_BLOCKED")
                old=db.execute("SELECT fingerprint,data FROM holds WHERE id=?",(plan_id,)).fetchone()
                if old:
                    need(old[0]==fingerprint,"RESERVATION_PLAN_CONFLICT")
                    value=self.read_hold(old[1])
                    need(value["intent_fingerprint"]==fingerprint
                         and value["amount_paise"]==checked["proposed_total_paise"],
                         "PERSISTED_HOLD_CONFLICT")
                    db.rollback()
                    return dict(value,idempotent_replay=True)
                held=[self.read_hold(r[0]) for r in db.execute("SELECT data FROM holds")]
                need(not any(r["held_paise"]>0 for r in held),
                     "EXISTING_LOCAL_RESERVATION_REQUIRES_REVIEW")
                value=dict(stable,intent_fingerprint=fingerprint,
                    amount_paise=checked["proposed_total_paise"],
                    held_paise=checked["proposed_total_paise"],
                    cash_cap_at_reservation_paise=checked["half_cash_cap_paise"],
                    capture_fingerprint=digest(capture),created_at=checked["assessed_at"],
                    state="LOCAL_RESERVED_UNSUBMITTED",broker_cash_locked=False,
                    entry_permission=False,production_execution_enabled=False,
                    reservation_release_permission=False)
                value["signature"]=sign(value,self.pin)
                db.execute("INSERT INTO holds VALUES(?,?,?)",
                           (plan_id,fingerprint,json.dumps(value)))
                checkpoint("AFTER_HOLD_INSERT")
                db.execute("INSERT INTO allocation_events(data) VALUES(?)",
                    (json.dumps(dict(type="LOCAL_HALF_CASH_HOLD_CREATED",plan_id=plan_id)),))
                checkpoint("BEFORE_COMMIT")
                final=sizing(capture,self.pin,as_of=clock().isoformat(),**proposal)
                need(final["within_half_cash_cap"]
                     and final["proposed_total_paise"]==value["amount_paise"],
                     "CASH_CHANGED_OR_STALE_BEFORE_COMMIT")
                db.commit()
            except BaseException:
                db.rollback()
                raise
        return dict(value,idempotent_replay=False)

    def mark_unknown(self,plan_id):
        identifier(plan_id)
        with self.connection() as db:
            db.execute("PRAGMA synchronous=FULL");db.execute("BEGIN IMMEDIATE")
            try:
                self.metadata(db)
                row=db.execute("SELECT data FROM holds WHERE id=?",(plan_id,)).fetchone()
                need(row is not None,"LOCAL_HOLD_NOT_FOUND")
                value=self.read_hold(row[0])
                value["state"]="UNKNOWN_OUTCOME_HOLD_RETAINED"
                value.pop("signature")
                value["signature"]=sign(value,self.pin)
                db.execute("UPDATE holds SET data=? WHERE id=?",(json.dumps(value),plan_id))
                db.commit()
            except BaseException:
                db.rollback();raise
        return value
