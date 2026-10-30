"""Pure historical checks extracted from the reviewed repository sources.
No Store construction, transport use or ownership grant.
"""
import hashlib,json,re
class Blocked(ValueError):pass
def need(condition,reason):
    if not condition:raise Blocked(reason)
def sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def order_id(v):
    if not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9-]{1,100}',v):raise Blocked('ORDER_ID_INVALID')
    return v

def place_ack(raw):
    if not isinstance(raw,dict) or raw.get('status')!='success':return dict(status='UNKNOWN_REQUIRES_RECONCILIATION',retry_allowed=False,fill_confirmed=False)
    data=raw.get('data');ids=data.get('order_ids') if isinstance(data,dict) else None
    if not isinstance(ids,list) or len(ids)!=1:return dict(status='AMBIGUOUS_OR_SPLIT_ACK_REVIEW',retry_allowed=False,fill_confirmed=False)
    try:oid=order_id(ids[0])
    except Blocked:return dict(status='INVALID_ACK_REVIEW',retry_allowed=False,fill_confirmed=False)
    return dict(status='ACKNOWLEDGED_NOT_FILLED',order_id=oid,retry_allowed=False,fill_confirmed=False)

def _check(mode, requests, attempts, receipts):
    request_ids = {row[0] for row in requests}
    attempt_ids = {row[0] for row in attempts}
    need(
        all(row[1] in request_ids for row in attempts)
        and set(receipts) <= attempt_ids,
        "ORPHAN_ATTEMPT_OR_RECEIPT",
    )

    links, seen, unbound = [], set(), 0
    for request_id, fingerprint, raw in requests:
        request = json.loads(raw)
        need(request["request_id"] == request_id, "REQUEST_ID_MISMATCH")
        if request.get("order_id") is None:
            # Even a persisted receipt cannot silently adopt an order here.
            # Existing adapter recovery must perform the binding.
            unbound += 1
            continue

        plan = {
            key: request[key] for key in (
                "request_id", "draft", "signal_id", "signal_at",
                "direction", "reservation_reference",
            )
        }
        need(sha(plan) == fingerprint, "REQUEST_FINGERPRINT_MISMATCH")
        draft = request["draft"]
        body = draft["body"]
        need(sha(body) == draft["fingerprint"], "BODY_FINGERPRINT_MISMATCH")
        need(draft["request_id"] == request_id, "DRAFT_REQUEST_ID_MISMATCH")
        need(
            (draft["documented_method"], draft["documented_host"],
             draft["documented_path"]) ==
            ("POST", "api-hft.upstox.com", "/v3/order/place"),
            "PLACE_ENDPOINT_MISMATCH",
        )
        need(
            all(draft[key] is False for key in (
                "submission_enabled", "entry_permission", "orders_sent",
            )),
            "DISABLED_DRAFT_REQUIRED",
        )

        places = [
            row for row in attempts
            if row[1] == request_id and row[2] == "PLACE"
        ]
        need(len(places) == 1, "EXACTLY_ONE_PLACE_ATTEMPT_REQUIRED")
        attempt_id, _, _, raw_attempt = places[0]
        attempt = json.loads(raw_attempt)
        need(
            attempt["attempt_id"] == attempt_id
            and attempt["request_id"] == request_id
            and attempt["operation"] == "PLACE",
            "ATTEMPT_IDENTITY_MISMATCH",
        )
        expected_wire = dict(
            method="POST", host="api-hft.upstox.com",
            path="/v3/order/place", body=body,
        )
        need(attempt["wire"] == expected_wire, "ATTEMPT_WIRE_MISMATCH")
        need(attempt_id in receipts, "DURABLE_PLACE_RECEIPT_REQUIRED")
        receipt = json.loads(receipts[attempt_id])
        expected_origin = (
            "EXPLICIT_FIXTURE_TRANSPORT"
            if mode == "OFFLINE_FIXTURE" else "LOCAL_HTTP_TRANSPORT"
        )
        need(
            receipt["origin"] == expected_origin
            and receipt["attempt_id"] == attempt_id
            and receipt["wire_fingerprint"] == sha(expected_wire),
            "RECEIPT_PROVENANCE_MISMATCH",
        )
        need(
            type(receipt["http_status"]) is int
            and receipt["http_status"] == 200,
            "SUCCESSFUL_PLACE_RECEIPT_REQUIRED",
        )
        acknowledgement = place_ack(receipt["body"])
        need(
            acknowledgement["status"] == "ACKNOWLEDGED_NOT_FILLED"
            and acknowledgement["order_id"] == request["order_id"],
            "ACK_ORDER_BINDING_MISMATCH",
        )
        need(request["order_id"] not in seen, "ORDER_ID_BOUND_TWICE")
        seen.add(request["order_id"])
        links.append(dict(
            request_id=request_id, order_id=request["order_id"],
            signal_id=request["signal_id"],
            reservation_reference=request["reservation_reference"],
            body_fingerprint=draft["fingerprint"],
            instrument=body["instrument_token"], product=body["product"],
            side=body["transaction_type"], quantity=body["quantity"],
        ))

    status = (
        "UNBOUND_REQUESTS_REQUIRE_RECONCILIATION" if unbound else
        "DURABLE_ACKNOWLEDGEMENT_REFERENCES_CHECKED" if links else
        "NO_BOUND_ACKNOWLEDGEMENTS"
    )
    return dict(
        model="HILEGA_DURABLE_RECEIPT_REVIEW_V1",
        status=status, adapter_mode=mode,
        bindings=links, unbound_request_count=unbound,
        historical_references_only=True,
        current_fills_assessed=False,
        application_hold_link_verified=False,
        strategy_ownership_verified=False,
        real_funds_reservation_verified=False,
        reservation_release_permission=False,
        entry_permission=False, production_execution_enabled=False,
        production_ready=False, orders_sent=False,
    )
