"""Application-owned local cash reference, atomic with disabled adapter requests.
No broker cash lock, execution clearance or release authority.
"""
import hmac
import json
from .evidence import FLAGS, digest, need, aware, day
from market_lab.hilega_production_account_adapter_v1 import sign

POLICY=dict(model="HILEGA_HALF_CASH_ENTRY_POLICY_V1",
    allocation_numerator=1,allocation_denominator=2,
    daily_loss_limit_paise=None,daily_loss_limit_required=False,
    fixed_max_entry_cost_paise=None,maximum_active_local_entries=1)
TABLE="preparation_cash_reservations"


def verify_row(row,pin):
    payload=dict(row);signature=payload.pop("signature",None)
    need(isinstance(signature,str) and hmac.compare_digest(sign(payload,pin),signature),
         "LOCAL_CASH_RESERVATION_SIGNATURE_INVALID")
    need(row["model"]=="HILEGA_APPLICATION_LOCAL_CASH_RESERVATION_V1"
         and row["account_scope"]==pin["scope"] and row["policy"]==POLICY,
         "LOCAL_CASH_RESERVATION_SCOPE_OR_POLICY_CHANGED")
    need(type(row["amount_cents"]) is int and row["amount_cents"]>0
         and type(row["held_cents"]) is int and type(row["cash_cap_cents"]) is int
         and row["held_cents"]==row["amount_cents"]
         and row["amount_cents"]<=row["cash_cap_cents"],
         "LOCAL_CASH_RESERVATION_AMOUNT_INVALID")
    need(row["state"] in {"RESERVED_DISABLED_REQUEST","UNKNOWN_HOLD_RETAINED"},
         "LOCAL_CASH_RESERVATION_STATE_INVALID")
    need(all(row.get(k) is False for k in FLAGS)
         and row.get("broker_cash_locked") is False,
         "LOCAL_CASH_RESERVATION_AUTHORITY_CHANGED")
    return row


def reserve_local(db,plan,hold,outbox,pin,current,request_fingerprint,*,now):
    """Caller owns the attached application/adapter BEGIN IMMEDIATE transaction.

    Signed cash/bundle, fresh contract/quote, controller and request validation
    run in bind_disabled_request before this function. Source rechecks freshness
    again before committing the same attached transaction.
    """
    need(db.in_transaction,"ACTIVE_APPLICATION_TRANSACTION_REQUIRED")
    key=plan["id"]
    need(key==hold["id"]==outbox["id"]==outbox["reservation_reference"],
         "LOCAL_CASH_REFERENCE_ID_MISMATCH")
    need(plan["account_scope"]==pin["scope"],"LOCAL_CASH_ACCOUNT_MISMATCH")
    need(all(v.get(flag) is False for v in (plan,hold,outbox) for flag in FLAGS),
         "LOCAL_CASH_INPUT_AUTHORITY_CHANGED")
    candidate=outbox["disabled_request_candidate"]
    premium,buffer,budget=(candidate[k] for k in (
        "premium_cents","fee_buffer_cents","budget_cents"))
    need(all(type(v) is int and v>0 for v in (premium,buffer,budget))
         and premium+buffer==budget,"LOCAL_CASH_CANDIDATE_COST_INVALID")
    amount=hold["held_cents"];cap=current["half_cash_cap_cents"]
    need(type(amount) is int and type(cap) is int and 0<budget<=amount<=cap,
         "LOCAL_CASH_HALF_CAP_EXCEEDED")
    need(hold.get("real_cash_reserved") is False
         and hold.get("evidence_mode")=="REAL_CASH_OBSERVED_SHADOW_ONLY",
         "LOCAL_CASH_SHADOW_REFERENCE_REQUIRED")
    need(day(now)==day(aware(plan["signal_at"])),"LOCAL_CASH_SESSION_CHANGED")
    db.execute("CREATE TABLE IF NOT EXISTS preparation_cash_policy("
               "id INTEGER PRIMARY KEY,data TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS "+TABLE+"("
               "id TEXT PRIMARY KEY,data TEXT NOT NULL)")
    meta=db.execute("SELECT data FROM preparation_cash_policy WHERE id=1").fetchone()
    expected=dict(scope=pin["scope"],mode="APPLICATION_LOCAL_REFERENCE_ONLY",policy=POLICY)
    need(meta is None or json.loads(meta[0])==expected,
         "LOCAL_CASH_POLICY_CHANGED")
    if meta is None:
        db.execute("INSERT INTO preparation_cash_policy VALUES(1,?)",(json.dumps(expected),))
    existing=[]
    for owner,raw in db.execute("SELECT id,data FROM "+TABLE):
        row=verify_row(json.loads(raw),pin)
        need(owner==row["id"],"LOCAL_CASH_RESERVATION_ID_CHANGED")
        existing.append(row)
    need(not existing,"EXISTING_LOCAL_CASH_RESERVATION_REQUIRES_REVIEW")
    row=dict(FLAGS,model="HILEGA_APPLICATION_LOCAL_CASH_RESERVATION_V1",
        id=key,account_scope=pin["scope"],session_date=day(now),
        state="RESERVED_DISABLED_REQUEST",policy=POLICY,
        amount_cents=amount,held_cents=amount,cash_cap_cents=cap,
        premium_cents=premium,fee_buffer_cents=buffer,
        fee_buffer_approved_for_production=False,
        request_fingerprint=request_fingerprint,
        plan_fingerprint=digest(plan),shadow_hold_fingerprint=digest(hold),
        outbox_fingerprint=digest(outbox),created_at=now.isoformat(),
        local_reference_reserved=True,broker_cash_locked=False)
    row["signature"]=sign(row,pin)
    db.execute("INSERT INTO "+TABLE+" VALUES(?,?)",(key,json.dumps(row)))
    return row
