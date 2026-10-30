"""Read-only application binding -> acknowledgement -> signed fill references.
No ownership adoption, financial authentication, persistence or execution authority.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from risk_evidence_audit import assess, read_sources, regular, need
from historical_receipt_checks import _check, sha
from signature_checks import verify, aware, day


def ident(value):
    need(isinstance(value, str) and 0 < len(value) <= 200
         and value.strip() == value and not any(ord(c) < 32 for c in value),
         "IDENTIFIER_INVALID")
    return value


def correlate(source, snapshot, pin, *, as_of, verifier=verify):
    audit = assess(source)
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
    gaps.update({"PREPARATION_BUNDLE_SIGNATURES_NOT_ASSESSED",
                 "POSITION_OWNERSHIP_RECONCILIATION_NOT_IMPLEMENTED",
                 "ORDER_MODIFICATION_HISTORY_NOT_ASSESSED"})
    if missing: gaps.add("CURRENT_BOUND_ORDER_MISSING")
    if without_binding: gaps.add("ACK_WITHOUT_APPLICATION_BINDING")
    if set(orders)-matched: gaps.add("CURRENT_ACCOUNT_ORDERS_NOT_LINKED")
    if not filled: gaps.add("NO_CURRENT_BOUND_FILL_REFERENCE")
    if any(positions.values()): gaps.add("CURRENT_POSITION_OWNERSHIP_UNVERIFIED")
    return dict(
        model="HILEGA_LIVE_OWNERSHIP_REFERENCE_BRIDGE_V1",
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
        evidence_sources_atomic=False, bundle_signatures_assessed=False,
        strategy_ownership_verified=False, fees_complete=False,
        realized_net_pnl_paise=None, open_net_pnl_paise=None,
        risk_gate_input_ready=False, real_funds_reservation_verified=False,
        database_modified=False, controller_changed=False, orders_sent=False,
        production_execution_enabled=False, entry_permission=False,
        reservation_release_permission=False, production_ready=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check"])
    parser.add_argument("--capture-account", action="store_true", required=True)
    parser.add_argument("--repo", type=Path, default=Path.home()/"RB-ITOS-AI")
    parser.add_argument("--pin-file", type=Path,
        default=Path.home()/"hilega-private/upstox-account-pin.json")
    args = parser.parse_args()
    root = args.repo.resolve()
    folder = Path(__file__).parent
    manifest = json.loads((folder/"manifest.json").read_text())
    for name, expected in manifest["installed_source_sha256"].items():
        need(hashlib.sha256(regular(root/name).read_bytes()).hexdigest() == expected,
             "INSTALLED_SOURCE_CHANGED")
    for name, expected in manifest["package_sha256"].items():
        need(hashlib.sha256(regular(folder/name).read_bytes()).hexdigest() == expected,
             "PACKAGE_SOURCE_CHANGED")
    sys.path.insert(0, str(root/"backend"))
    from market_lab.hilega_production_account_adapter_v1 import (
        read_pin, capture, Client, verify as installed_verify)
    from dotenv import dotenv_values
    pin = read_pin(args.pin_file)
    app = root/"data/research/hilega-production-workspace/sim.sqlite"
    adapter = root/"data/research/hilega-broker-adapter-closed/adapter.sqlite"
    before = read_sources(app, adapter, pin["scope"])
    assess(before)
    settings = dotenv_values(root/".env")
    def setting(name):
        shell, file = os.getenv(name), settings.get(name)
        need(not(shell and file and shell != file), "TOKEN_CONFIGURATION_CONFLICT")
        return shell or file
    primary = setting("HILEGA_PRODUCTION_BROKER_READ_TOKEN")
    secondary = setting("UPSTOX_ACCESS_TOKEN")
    token = (primary or secondary or "").strip()
    need(bool(token), "READ_TOKEN_MISSING")
    snapshot = capture(Client(token), pin)
    after = read_sources(app, adapter, pin["scope"])
    need(before == after, "LOCAL_SOURCES_CHANGED_DURING_CAPTURE")
    report = correlate(after, snapshot, pin,
        as_of=datetime.now(timezone.utc).isoformat(), verifier=installed_verify)
    report["broker_reads_performed"] = True
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        message = str(exc)
        print(json.dumps(dict(status="STOPPED_FOR_REVIEW",
            reason=message if re.fullmatch("[A-Z][A-Z0-9_]{0,179}", message)
                   else type(exc).__name__,
            production_ready=False, production_execution_enabled=False)))
        raise SystemExit(1)
