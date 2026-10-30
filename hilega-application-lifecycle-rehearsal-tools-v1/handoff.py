"""Explicit synthetic-application -> separate fixture execution handoff.

Never rewrites a closed adapter's mode or imports fixture fills into the app.
"""
import hmac
import json
from adapter_reference.adapter import Store, Adapter, FixtureTransport
from bridge import authenticate_preparation_bundles
from historical_receipt_checks import sha
from risk_evidence_audit import assess, FLAGS, need
from signature_checks import sign


def prepare_fixture_execution(source,reservation,pin,fixture_store,*,as_of):
    need(pin["scope"].startswith("FIXTURE:"),"SYNTHETIC_FIXTURE_SCOPE_REQUIRED")
    need(type(fixture_store) is Store and fixture_store.mode=="OFFLINE_FIXTURE"
         and fixture_store.scope==pin["scope"],"SEPARATE_FIXTURE_STORE_REQUIRED")
    need(source["mode"]=="LIVE_CLOSED" and source["scope"]==pin["scope"]
         and source["control"].get("mode")=="PAUSED","CLOSED_SYNTHETIC_SOURCE_REQUIRED")
    audit=assess(source)
    need(len(source["requests"])==1 and len(source["bindings"])==1
         and not source["attempts"] and not source["receipts"],
         "SINGLE_UNSUBMITTED_APPLICATION_REQUEST_REQUIRED")
    need(authenticate_preparation_bundles(source,pin,as_of=as_of)==1,
         "AUTHENTICATED_SYNTHETIC_BUNDLE_REQUIRED")
    key,fingerprint,raw=source["requests"][0];request=json.loads(raw)
    need(key in source["bindings"] and request.get("order_id") is None
         and request.get("state")=="PREPARED","PREPARED_APPLICATION_REFERENCE_REQUIRED")
    need(all(source["counts"][k]==0 for k in (
        "intents","sim_orders","sim_fills","sim_allocation_reservations")),
        "APPLICATION_EXECUTION_STATE_MUST_REMAIN_EMPTY")
    payload=dict(reservation);signature=payload.pop("signature",None)
    need(isinstance(signature,str) and hmac.compare_digest(sign(payload,pin),signature),
         "APPLICATION_RESERVATION_SIGNATURE_INVALID")
    binding=source["bindings"][key]
    need(reservation.get("model")=="HILEGA_APPLICATION_LOCAL_CASH_RESERVATION_V1"
         and reservation.get("id")==key
         and reservation.get("account_scope")==pin["scope"]
         and reservation.get("state")=="RESERVED_DISABLED_REQUEST"
         and reservation.get("request_fingerprint")==fingerprint
         and reservation.get("plan_fingerprint")==sha(source["plans"][key])
         and reservation.get("shadow_hold_fingerprint")==sha(source["holds"][key])
         and reservation.get("outbox_fingerprint")==sha(source["outbox"][key]),
         "APPLICATION_RESERVATION_REFERENCE_MISMATCH")
    need(type(reservation["held_cents"]) is int and reservation["held_cents"]>0
         and reservation["held_cents"]==reservation["amount_cents"]==binding["held_cents"]
         and reservation["cash_cap_cents"]==binding["cash_cap_cents"],
         "APPLICATION_RESERVATION_AMOUNT_MISMATCH")
    need(all(reservation.get(k) is False for k in FLAGS)
         and reservation.get("broker_cash_locked") is False,
         "APPLICATION_RESERVATION_AUTHORITY_INVALID")
    policy=reservation["policy"]
    need(policy.get("allocation_numerator")==1 and policy.get("allocation_denominator")==2
         and policy.get("daily_loss_limit_required") is False
         and policy.get("daily_loss_limit_paise") is None
         and policy.get("fixed_max_entry_cost_paise") is None,"OPERATOR_ALLOCATION_POLICY_MISMATCH")
    adapter=Adapter(fixture_store,FixtureTransport(fixture_store))
    prepared=adapter.prepare(request["draft"],signal_id=request["signal_id"],
        signal_at=request["signal_at"],direction=request["direction"],
        reservation_reference=request["reservation_reference"],as_of=as_of)
    need(prepared["request_id"]==key,"FIXTURE_HANDOFF_REQUEST_CHANGED")
    return adapter,key
