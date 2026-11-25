"""Read-only application binding -> acknowledgement -> signed fill references.
No ownership adoption, financial authentication, persistence or execution authority.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sys
from .risk_evidence_audit import assess, read_sources, regular, need, FLAGS
from .historical_receipt_checks import _check, sha
from .signature_checks import verify, aware, day, sign


def authenticate_preparation_bundles(source, pin, *, as_of):
    """Authenticate historical outer envelopes only, never their current freshness.

    Called after assess() checks each local binding and all its digest links.
    Nested cash signatures, contract/quote correctness and pricing approval are
    separate checks and are not established by this function.
    """
    need(source["scope"] == pin["scope"], "PREPARATION_PIN_SCOPE_MISMATCH")
    fingerprints = {b["bundle_fingerprint"] for b in source["bindings"].values()}
    for fingerprint in sorted(fingerprints):
        raw = source["evidence"].get(fingerprint)
        need(raw is not None, "PREPARATION_BUNDLE_MISSING")
        bundle = json.loads(raw)
        need(isinstance(bundle, dict), "PREPARATION_BUNDLE_OBJECT_REQUIRED")
        need(sha(bundle) == fingerprint, "PREPARATION_BUNDLE_DIGEST_MISMATCH")
        payload = dict(bundle)
        signature = payload.pop("signature", None)
        need(isinstance(signature, str)
             and hmac.compare_digest(sign(payload, pin), signature),
             "PREPARATION_BUNDLE_SIGNATURE_INVALID")
        need(bundle.get("model") == "HILEGA_SIGNED_PREPARATION_EVIDENCE_V1"
             and bundle.get("evidence_mode") == "LIVE_READ_ONLY_ACCOUNT_PINNED",
             "SIGNED_LIVE_PREPARATION_BUNDLE_REQUIRED")
        need(bundle.get("account_scope") == pin["scope"],
             "PREPARATION_BUNDLE_ACCOUNT_MISMATCH")
        need(all(bundle.get(k) is False for k in FLAGS),
             "PREPARATION_BUNDLE_READ_ONLY_FLAGS_REQUIRED")
        start, end = aware(bundle["started_at"]), aware(bundle["completed_at"])
        need(start <= end <= aware(as_of) and (end-start).total_seconds() <= 30
             and day(start) == day(end) == bundle.get("session_date"),
             "PREPARATION_BUNDLE_CAPTURE_WINDOW_INVALID")
        need(bundle.get("profile_verified_before_and_after") is True,
             "PREPARATION_BUNDLE_PROFILE_UNVERIFIED")
    return len(fingerprints)


def ident(value):
    need(isinstance(value, str) and 0 < len(value) <= 200
         and value.strip() == value and not any(ord(c) < 32 for c in value),
         "IDENTIFIER_INVALID")
    return value


def position_references(orders, positions, matched, *, missing,
                        unbound, without_binding, prior):
    """Compare current entry BUY fill totals to explicit signed position rows.

    Missing is not flat. Entry references cannot attribute SELL exits, prior
    sessions, external activity, or lifecycle ownership. No ownership is written.
    """
    reasons = set()
    expected = {}
    for oid in matched:
        row = orders[oid]
        if row["side"] != "BUY":
            reasons.add("SELL_EXIT_OWNERSHIP_NOT_SUPPORTED")
            continue
        key = row["instrument"], row["product"]
        expected[key] = expected.get(key, 0) + row["filled"]
    if not matched:
        reasons.add("NO_CURRENT_BOUND_ORDER_POSITION_BASELINE")
    if missing:
        reasons.add("MISSING_BOUND_ORDER_PREVENTS_POSITION_RECONCILIATION")
    if unbound:
        reasons.add("UNACKNOWLEDGED_REQUEST_PREVENTS_POSITION_RECONCILIATION")
    if without_binding:
        reasons.add("UNBOUND_ACK_PREVENTS_POSITION_RECONCILIATION")
    if prior:
        reasons.add("PRIOR_SESSION_ACK_REQUIRES_LIFECYCLE_RECONCILIATION")
    if set(orders) - matched:
        reasons.add("UNLINKED_ACCOUNT_ORDER_PREVENTS_POSITION_RECONCILIATION")
    missing_rows = set(expected) - set(positions)
    mismatched = {key for key, q in expected.items()
                  if key in positions and positions[key] != q}
    unlinked_exposure = {key for key, q in positions.items()
                        if q != 0 and key not in expected}
    if missing_rows:
        reasons.add("MISSING_POSITION_ROW_IS_NOT_FLAT")
    if mismatched:
        reasons.add("BOUND_BUY_FILL_POSITION_QUANTITY_MISMATCH")
    if unlinked_exposure:
        reasons.add("UNLINKED_ACCOUNT_POSITION_EXPOSURE")
    if any(orders[oid]["status"] in {"OPEN", "PARTIAL"} for oid in matched):
        reasons.add("NONTERMINAL_BOUND_ORDER_REQUIRES_RECONCILIATION")
    return dict(
        position_reference_scope="CURRENT_SESSION_ENTRY_BUY_QUANTITIES_ONLY",
        position_reference_status="REFERENCE_QUANTITIES_MATCH" if not reasons
                                  else "BLOCKED_POSITION_REFERENCE_GAPS",
        current_entry_buy_position_quantities_match=not reasons,
        expected_position_key_count=len(expected),
        missing_position_row_count=len(missing_rows),
        mismatched_position_row_count=len(mismatched),
        unlinked_nonzero_position_key_count=len(unlinked_exposure),
        expected_bound_buy_fill_quantity=sum(expected.values()),
        position_reference_reasons=sorted(reasons),
        strategy_ownership_verified=False)


def validate_account_rows(snapshot):
    session = snapshot["session_date"]
    end = aware(snapshot["completed_at"])
    orders = {}
    for row in snapshot["orders"]:
        oid = ident(row["order_id"])
        need(oid not in orders, "DUPLICATE_ORDER_ID")
        ident(row["instrument"]); ident(row["product"])
        q, f, p = (row[k] for k in ("quantity", "filled", "pending"))
        need(all(type(v) is int for v in (q, f, p))
             and q > 0 and f >= 0 and p >= 0 and f+p <= q,
             "ORDER_QUANTITY_INVALID")
        state = row["status"]
        need(state in {"OPEN", "PARTIAL", "FILLED", "CANCELLED", "REJECTED"}
             and row["side"] in {"BUY", "SELL"}, "ORDER_STATE_INVALID")
        need(state != "FILLED" or (f == q and p == 0), "FILLED_ORDER_INCONSISTENT")
        need(state not in {"CANCELLED", "REJECTED"} or p == 0, "TERMINAL_ORDER_PENDING")
        need(state not in {"OPEN", "REJECTED"} or f == 0, "ORDER_FILLED_STATE_INVALID")
        need(state != "PARTIAL" or 0 < f < q, "PARTIAL_ORDER_INCONSISTENT")
        at = aware(row["placed_at"])
        need(day(at) == session and at <= end, "ORDER_TIME_INVALID")
        orders[oid] = row
    totals, trades = {}, set()
    for row in snapshot["trades"]:
        oid, tid = ident(row["order_id"]), ident(row["trade_id"])
        need((oid, tid) not in trades, "DUPLICATE_TRADE_ID")
        trades.add((oid, tid))
        need(oid in orders, "TRADE_ORDER_MISSING")
        order = orders[oid]
        need(all(row[k] == order[k] for k in ("instrument", "product", "side")),
             "TRADE_CONTRACT_MISMATCH")
        q = row["quantity"]
        need(type(q) is int and q > 0, "TRADE_QUANTITY_INVALID")
        price = row["price"]
        need(type(price) in (str, int, float), "TRADE_PRICE_INVALID")
        price = Decimal(str(price))
        need(price.is_finite() and price > 0, "TRADE_PRICE_INVALID")
        at = aware(row["filled_at"])
        need(day(at) == session and aware(order["placed_at"]) <= at <= end,
             "TRADE_TIME_INVALID")
        totals[oid] = totals.get(oid, 0) + q
    need(all(totals.get(oid, 0) == o["filled"] for oid, o in orders.items()),
         "ORDER_TRADE_FILL_TOTAL_MISMATCH")
    positions = {}
    for row in snapshot["positions"]:
        key = ident(row["instrument"]), ident(row["product"])
        need(key not in positions, "DUPLICATE_POSITION_KEY")
        need(type(row["quantity"]) is int, "POSITION_QUANTITY_INVALID")
        positions[key] = row["quantity"]
    return orders, positions


def correlate(source, snapshot, pin, *, as_of, verifier=verify):
    audit = assess(source)
    authenticated = authenticate_preparation_bundles(source, pin, as_of=as_of)
    need(source["scope"] == pin["scope"], "ACCOUNT_SCOPE_MISMATCH")
    verifier(snapshot, pin, as_of=as_of)
    need(snapshot.get("profile_verified_before_and_after") is True
         and snapshot.get("account_position_rows_complete") is True,
         "COMPLETE_PINNED_CAPTURE_REQUIRED")
    need(snapshot.get("source_atomic") is False
         and snapshot.get("position_fill_linkage_verified") is False
         and snapshot.get("live_pnl") is None, "UNEXPECTED_CAPTURE_AUTHORITY")
    ident(snapshot["snapshot_id"])
    start, end = aware(snapshot["generated_at"]), aware(snapshot["completed_at"])
    session = snapshot["session_date"]
    need(day(start) == day(end) == session, "CAPTURE_SESSION_MISMATCH")
    for name in ("orders", "trades", "positions"):
        need(isinstance(snapshot.get(name), list), "EVIDENCE_LIST_REQUIRED")
    orders, positions = validate_account_rows(snapshot)
    trades = {(r["order_id"], r["trade_id"]) for r in snapshot["trades"]}
    historical = _check(source["mode"], source["requests"],
                        source["attempts"], source["receipts"])
    requests = {key: json.loads(raw) for key, fp, raw in source["requests"]}
    matched, missing, prior, without_binding, filled = set(), 0, 0, 0, 0
    references = []
    for link in historical["bindings"]:
        request = requests[link["request_id"]]
        if day(aware(request["signal_at"])) != session:
            prior += 1
            continue
        if link["request_id"] not in source["bindings"]:
            without_binding += 1
            continue
        order = orders.get(link["order_id"])
        if order is None:
            missing += 1
            continue
        need(all(order[k] == link[k] for k in
                 ("instrument", "product", "side", "quantity")),
             "BOUND_ORDER_CONTRACT_MISMATCH")
        need(aware(order["placed_at"]) >= aware(request["signal_at"]),
             "ORDER_PRECEDES_SIGNAL")
        matched.add(link["order_id"])
        filled += order["filled"]
        references.append(sha(dict(request=link["request_id"],
            order=link["order_id"], snapshot=snapshot["snapshot_id"])))
    gaps = set(audit["gaps"])
    gaps.discard("CURRENT_SIGNED_ACCOUNT_EVIDENCE_NOT_ASSESSED")
    gaps.update({"PREPARATION_NESTED_EVIDENCE_NOT_REVALIDATED",
                 "POSITION_OWNERSHIP_RECONCILIATION_NOT_IMPLEMENTED",
                 "ORDER_MODIFICATION_HISTORY_NOT_ASSESSED"})
    if not authenticated:
        gaps.add("NO_BOUND_PREPARATION_BUNDLES_TO_AUTHENTICATE")
    if missing: gaps.add("CURRENT_BOUND_ORDER_MISSING")
    if without_binding: gaps.add("ACK_WITHOUT_APPLICATION_BINDING")
    if set(orders)-matched: gaps.add("CURRENT_ACCOUNT_ORDERS_NOT_LINKED")
    if not filled: gaps.add("NO_CURRENT_BOUND_FILL_REFERENCE")
    if any(positions.values()): gaps.add("CURRENT_POSITION_OWNERSHIP_UNVERIFIED")
    position_result = position_references(
        orders, positions, matched, missing=missing,
        unbound=historical["unbound_request_count"],
        without_binding=without_binding, prior=prior)
    gaps.update(position_result["position_reference_reasons"])
    return dict(
        model="HILEGA_LIVE_OWNERSHIP_REFERENCE_BRIDGE_V1",
        review_version="3.0.0-entry-buy-position-references",
        status="BLOCKED_OWNERSHIP_AND_RISK_INTEGRATION_PENDING",
        assessed_at=as_of,
        account_capture_generated_at=snapshot["generated_at"],
        account_capture_completed_at=snapshot["completed_at"],
        account_capture_age_seconds=(aware(as_of)-start).total_seconds(),
        account_identity_and_local_signature_verified=True,
        local_binding_reference_count=audit["local_binding_reference_count"],
        historical_ack_reference_count=len(historical["bindings"]),
        current_bound_order_reference_count=len(matched),
        current_bound_fill_quantity=filled,
        missing_current_bound_order_count=missing, prior_session_ack_count=prior,
        acknowledgements_without_application_binding=without_binding,
        current_unlinked_order_count=len(set(orders)-matched),
        current_trade_count=len(trades),
        nonzero_position_count=sum(q != 0 for q in positions.values()),
        reference_fingerprints=sorted(references), gaps=sorted(gaps),
        position_reference_review=position_result,
        evidence_sources_atomic=False,
        bundle_signatures_assessed=authenticated > 0,
        authenticated_historical_bundle_count=authenticated,
        bundle_authentication_scope="BOUND_HISTORICAL_OUTER_ENVELOPES_ONLY",
        historical_bundles_are_current_entry_evidence=False,
        nested_cash_signatures_revalidated=False,
        strategy_ownership_verified=False, fees_complete=False,
        realized_net_pnl_paise=None, open_net_pnl_paise=None,
        risk_gate_input_ready=False, real_funds_reservation_verified=False,
        database_modified=False, controller_changed=False, orders_sent=False,
        production_execution_enabled=False, entry_permission=False,
        reservation_release_permission=False, production_ready=False)

