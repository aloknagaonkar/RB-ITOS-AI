"""Application-owned local cash reference, atomic with disabled adapter requests.
No broker cash lock, execution clearance or release authority.
"""
import hmac
import json
from .risk_evidence_audit import FLAGS, need
from .signature_checks import sign

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

