"""Fixture third-position EXIT and closeout. No live execution."""
from contextlib import closing
from copy import deepcopy
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3

from fixture_third_execution_candidate import preparation_proof, ADAPTER_SHA
from closed_history_baseline_candidate import order_identity, trade_identity
from authorized_exit_fixture import issue_exit, claim_exit
from owned_exit_pricing_candidate import review_owned_quote
from market_lab.hilega_execution_port_v1.mapping import draft
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE, normalized_tick
from market_lab.hilega_preparation_runtime_v1.ownership_state import SourceReader, rollback_database
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_connection
from market_lab.hilega_preparation_runtime_v1.ownership_checks.bridge import validate_account_rows
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import _check, sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import verify, sign, aware
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted

CLOSEOUTS = "fixture_third_position_closeouts"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def review_third_position(app, source, snapshot, pin, key, event, as_of):
    proof, archives = preparation_proof(app, source, pin, key)
    need(pin["scope"].startswith("FIXTURE:")
         and source["mode"] == "OFFLINE_FIXTURE",
         "FIXTURE_THIRD_POSITION_ONLY")
    verify(snapshot, pin, as_of=as_of)
    need(snapshot.get("profile_verified_before_and_after") is True
         and snapshot.get("account_position_rows_complete") is True
         and snapshot.get("source_atomic") is False
         and snapshot.get("position_fill_linkage_verified") is False,
         "COMPLETE_READ_ONLY_CAPTURE_REQUIRED")
    orders, positions = validate_account_rows(snapshot)
    old_ids, old_orders, old_trades, old_position_keys = set(), {}, {}, set()
    for archived in archives:
        for rid, fp, raw in archived["source"]["requests"]:
            need(rid not in old_ids, "DUPLICATE_ARCHIVED_REQUEST")
            old_ids.add(rid)
        previous_orders, previous_positions = validate_account_rows(
            archived["snapshot"])
        old_position_keys.update(previous_positions)
        for oid, order in previous_orders.items():
            need(oid not in old_orders, "DUPLICATE_ARCHIVED_ORDER")
            old_orders[oid] = order_identity(order)
        for trade in archived["snapshot"]["trades"]:
            tid = trade["order_id"], trade["trade_id"]
            need(tid not in old_trades, "DUPLICATE_ARCHIVED_TRADE")
            old_trades[tid] = trade_identity(trade)
    need(all(oid in orders and order_identity(orders[oid]) == expected
             for oid, expected in old_orders.items()),
         "ARCHIVED_ORDER_EVIDENCE_CHANGED")
    current_old_trades = {
        (t["order_id"], t["trade_id"]): trade_identity(t)
        for t in snapshot["trades"] if t["order_id"] in old_orders
    }
    need(current_old_trades == old_trades,
         "ARCHIVED_TRADE_EVIDENCE_CHANGED")


    requests = {
        rid: (fp, json.loads(raw))
        for rid, fp, raw in source["requests"]
    }
    need(len(requests) == len(source["requests"]), "DUPLICATE_REQUEST_ID")
    need(key not in old_ids and key in requests,
         "CURRENT_REPEAT_ENTRY_REQUIRED")
    entry_fp, entry = requests[key]
    stable = {name: entry[name] for name in (
        "request_id", "draft", "signal_id", "signal_at",
        "direction", "reservation_reference",
    )}
    need(sha(stable) == entry_fp
         == source["bindings"][key]["request_fingerprint"]
         == proof["request_fingerprint"],
         "CURRENT_ENTRY_FINGERPRINT_CHANGED")
    need(event["role"] == "EXIT"
         and event["direction"] == entry["direction"]
         and event.get("entry_reference_at") is not None
         and aware(event["entry_reference_at"]) == aware(entry["signal_at"])
         and aware(entry["signal_at"]) <= aware(event["event_at"])
             <= aware(snapshot["completed_at"]),
         "REPEAT_EXIT_PARENT_MISMATCH")
    exit_id = sha(["SYNTHETIC_STRATEGY_EXIT", key, event["id"]])
    need(set(requests)-old_ids in ({key}, {key, exit_id}),
         "UNATTRIBUTED_CURRENT_REQUEST")
    need(old_ids <= set(requests), "ARCHIVED_REQUEST_MISSING")
    expected_fps = {
        rid: fp for archived in archives
        for rid, fp, raw in archived["source"]["requests"]
    }
    need(all(requests[rid][0] == fp for rid, fp in expected_fps.items()),
         "ARCHIVED_REQUEST_FINGERPRINT_CHANGED")
    expected_old_attempts = {
        aid: (rid, op, sha(json.loads(raw)["wire"]))
        for archived in archives
        for aid, rid, op, raw in archived["source"]["attempts"]
    }
    actual_old_attempts = {
        aid: (rid, op, sha(json.loads(raw)["wire"]))
        for aid, rid, op, raw in source["attempts"] if rid in old_ids
    }
    need(actual_old_attempts == expected_old_attempts,
         "ARCHIVED_TRANSPORT_HISTORY_CHANGED")
    for archived in archives:
        for aid, raw in archived["source"]["receipts"].items():
            need(aid in source["receipts"]
                 and sha(json.loads(source["receipts"][aid]))
                     == sha(json.loads(raw)),
                 "ARCHIVED_RECEIPT_CHANGED")
    need(all(row["state"] not in {
        "UNKNOWN", "IN_FLIGHT", "CANCEL_IN_FLIGHT", "CANCEL_OUTCOME_UNKNOWN",
    } for fp, row in requests.values()), "UNRESOLVED_REQUEST_OUTCOME")
    need(all(op == "PLACE" for aid, rid, op, raw in source["attempts"]
             if rid not in old_ids), "CURRENT_CANCEL_REQUIRES_SEPARATE_REVIEW")
    historical = _check(
        "OFFLINE_FIXTURE", source["requests"],
        source["attempts"], source["receipts"])
    links = {row["request_id"]: row for row in historical["bindings"]}
    need(key in links, "CURRENT_ENTRY_ACKNOWLEDGEMENT_REQUIRED")
    parent_link = links[key]
    buy = orders.get(parent_link["order_id"])
    need(buy is not None and parent_link["side"] == "BUY",
         "CURRENT_ENTRY_ORDER_REQUIRED")
    need(all(buy[name] == parent_link[name] for name in (
        "instrument", "product", "side", "quantity",
    )), "CURRENT_ENTRY_ORDER_IDENTITY_MISMATCH")
    need(buy["status"] == "FILLED"
         and buy["filled"] == buy["quantity"]
         and buy["pending"] == 0,
         "FULL_CURRENT_ENTRY_FILL_REQUIRED")

    need(aware(buy["placed_at"]) >= aware(entry["signal_at"]),
         "ENTRY_ORDER_PRECEDES_SIGNAL")
    sell = None
    expected_unbound = 0
    if exit_id in requests:
        exit_fp, exit_request = requests[exit_id]
        exit_stable = {name: exit_request[name] for name in (
            "request_id", "draft", "signal_id", "signal_at",
            "direction", "reservation_reference",
        )}
        disabled = exit_request["draft"]
        body = disabled["body"]
        need(sha(exit_stable) == exit_fp
             and sha(body) == disabled["fingerprint"]
             and disabled["request_id"] == exit_id
             and all(disabled.get(flag) is False for flag in (
                 "submission_enabled", "entry_permission", "orders_sent",
             )), "REPEAT_EXIT_DRAFT_CHANGED")
        need(
            (disabled["documented_method"], disabled["documented_host"],
             disabled["documented_path"])
            == ("POST", "api-hft.upstox.com", "/v3/order/place"),
            "REPEAT_EXIT_ENDPOINT_CHANGED")
        need(exit_request["signal_id"] == event["id"]
             and aware(exit_request["signal_at"]) == aware(event["event_at"])
             and exit_request["direction"] == entry["direction"]
             and exit_request["reservation_reference"]
                 == entry["reservation_reference"]
             and body["transaction_type"] == "SELL"
             and body["order_type"] == "LIMIT"
             and body["instrument_token"] == buy["instrument"]
             and body["product"] == buy["product"]
             and type(body["quantity"]) is int
             and body["quantity"] == buy["filled"],
             "REPEAT_EXIT_PARENT_OR_QUANTITY_CHANGED")
        if exit_id in links:
            sell = orders.get(links[exit_id]["order_id"])
            need(sell is not None and all(
                sell[name] == links[exit_id][name]
                for name in ("instrument", "product", "side", "quantity")),
                "REPEAT_EXIT_ORDER_IDENTITY_MISMATCH")
        else:
            need(exit_request["state"] == "PREPARED"
                 and exit_request.get("order_id") is None
                 and not any(rid == exit_id
                             for aid, rid, op, raw in source["attempts"]),
                 "UNACKNOWLEDGED_EXIT_REQUIRES_RECOVERY")
            expected_unbound = 1

    need(historical["unbound_request_count"] == expected_unbound,
         "UNATTRIBUTED_UNBOUND_REQUEST")
    expected_orders = {link["order_id"] for link in links.values()}
    need(set(orders) == expected_orders,
         "UNATTRIBUTED_OR_MISSING_CAPTURE_ORDER")
    sold = sell["filled"] if sell else 0
    remaining = buy["filled"] - sold
    need(remaining >= 0, "REPEAT_EXIT_EXCEEDS_ENTRY_FILL")
    expected_positions = {position: 0 for position in old_position_keys}
    position = buy["instrument"], buy["product"]
    expected_positions[position] = remaining
    need(set(expected_positions) <= set(positions),
         "MISSING_POSITION_ROW_IS_NOT_FLAT")
    need(all(positions[k] == q for k, q in expected_positions.items())
         and not any(q != 0 for k, q in positions.items()
                     if k not in expected_positions),
         "REPEAT_POSITION_OR_EXTERNAL_EXPOSURE_MISMATCH")
    pending = sell["pending"] if sell else 0
    need(pending <= remaining, "PENDING_SELL_EXCEEDS_REMAINING")
    return dict(
        entry_id=key, exit_id=exit_id,
        entry_quantity=buy["filled"], exit_filled_quantity=sold,
        remaining_quantity=remaining, pending_exit_quantity=pending,
        all_orders_terminal=all(
            o["status"] in {"FILLED", "CANCELLED", "REJECTED"}
            and o["pending"] == 0 for o in orders.values()),
        ownership=dict(
            filled=buy["filled"], status=buy["status"],
            direction=entry["direction"], instrument=buy["instrument"],
            product=buy["product"], order_id=buy["order_id"]),
        archived_lifecycle_count=2*len(archives),
        source_fingerprint=sha(source),
        snapshot_fingerprint=sha(snapshot),
        strategy_ownership_verified=False,
        reservation_release_permission=False,
        production_execution_enabled=False)



def execute_third_exit_fixture(
    application_store, execution_store, pin, *,
    adapter_module, entry_id, journal, sequence,
    capture_provider, clock, timeout_after=False,
    checkpoint=lambda stage: None,
):
    need(pin["scope"].startswith("FIXTURE:"), "FIXTURE_THIRD_EXIT_ONLY")
    path = Path(adapter_module.__file__)
    need(path.is_file() and not path.is_symlink()
         and hashlib.sha256(path.read_bytes()).hexdigest() == ADAPTER_SHA,
         "PINNED_FIXTURE_ADAPTER_REQUIRED")
    need(type(execution_store) is adapter_module.Store
         and execution_store.mode == "OFFLINE_FIXTURE"
         and execution_store.scope == pin["scope"],
         "EXACT_FIXTURE_EXECUTION_STORE_REQUIRED")
    records = verified_records(journal)
    need(type(sequence) is int and 1 <= sequence <= len(records),
         "JOURNAL_SEQUENCE_INVALID")
    events = accepted(records[sequence-1])
    need(len(events) == 1 and events[0]["role"] == "EXIT",
         "SINGLE_CONFIRMED_EXIT_REQUIRED")
    event = events[0]
    exit_id = sha(["SYNTHETIC_STRATEGY_EXIT", entry_id, event["id"]])
    app_path = rollback_database(application_store.path)
    broker_path = rollback_database(execution_store.path)
    need(not app_path.samefile(broker_path), "DISTINCT_DATABASES_REQUIRED")
    transport = adapter_module.FixtureTransport(execution_store)
    adapter = adapter_module.Adapter(execution_store, transport)
    with application_store.lock():
        with closing(sqlite3.connect(
            app_path.as_uri()+"?mode=ro", uri=True, timeout=10,
        )) as app:
            app.execute("PRAGMA query_only=ON")
            app.execute("BEGIN")
            try:
                with execution_store.tx() as db:
                    source = read_connection(
                        SourceReader(app, db), pin["scope"],
                        expected_mode="OFFLINE_FIXTURE")
                    found = db.execute(
                        "SELECT fingerprint,data FROM requests WHERE id=?",
                        (exit_id,),
                    ).fetchone()
                    attempts = db.execute(
                        "SELECT id,request_id,operation,data FROM attempts "
                        "WHERE request_id=?", (exit_id,),
                    ).fetchall()
                preparation_proof(app, source, pin, entry_id)
                parent_fp, parent_raw = next(
                    (fp, raw) for rid, fp, raw in source["requests"]
                    if rid == entry_id)
                parent = json.loads(parent_raw)
                parent_stable = {name: parent[name] for name in (
                    "request_id", "draft", "signal_id", "signal_at",
                    "direction", "reservation_reference",
                )}
                need(sha(parent_stable) == parent_fp
                     == source["bindings"][entry_id]["request_fingerprint"],
                     "REPEAT_PARENT_FINGERPRINT_CHANGED")
                need(event["direction"] == parent["direction"]
                     and event.get("entry_reference_at") is not None
                     and aware(event["entry_reference_at"])
                         == aware(parent["signal_at"]),
                     "REPEAT_EXIT_PARENT_MISMATCH")

                if attempts:
                    need(len(attempts) == 1 and found is not None,
                         "SINGLE_REPEAT_EXIT_ATTEMPT_REQUIRED")
                    exit_fp, raw_exit = found
                    saved = json.loads(raw_exit)
                    stable = {name: saved[name] for name in (
                        "request_id", "draft", "signal_id", "signal_at",
                        "direction", "reservation_reference",
                    )}
                    body = saved["draft"]["body"]
                    need(sha(stable) == exit_fp
                         and saved["request_id"] == exit_id
                         and saved["signal_id"] == event["id"]
                         and aware(saved["signal_at"]) == aware(event["event_at"])
                         and saved["direction"] == parent["direction"]
                         and saved["reservation_reference"]
                             == parent["reservation_reference"]
                         and body["transaction_type"] == "SELL"
                         and body["quantity"] == parent["draft"]["body"]["quantity"]
                         and body["instrument_token"]
                             == parent["draft"]["body"]["instrument_token"]
                         and body["product"] == parent["draft"]["body"]["product"],
                         "REPEAT_EXIT_RECOVERY_REQUEST_CHANGED")
                    aid, rid, operation, raw_attempt = attempts[0]
                    attempt = json.loads(raw_attempt)
                    need(attempt["attempt_id"] == aid
                         and attempt["request_id"] == rid == exit_id
                         and attempt["operation"] == operation == "PLACE"
                         and attempt["wire"] == adapter._wire(saved, "PLACE"),
                         "REPEAT_EXIT_RECOVERY_ATTEMPT_CHANGED")
                    adapter.recover()
                    recovered = next(
                        row for row in execution_store.requests()
                        if row["request_id"] == exit_id)
                    return dict(
                        status="EXISTING_THIRD_EXIT_RECOVERED_NO_SUBMISSION",
                        exit_id=exit_id, exit_state=recovered["state"],
                        recovery_only=True, new_attempt_created=False,
                        orders_sent_to_upstox=False,
                        reservation_release_permission=False,
                        production_execution_enabled=False)

                captures = capture_provider()
                need(isinstance(captures, dict)
                     and set(captures) == {"account", "market"},
                     "EXACT_REPEAT_EXIT_CAPTURE_SET_REQUIRED")
                now = clock()
                need(0 <= (now-aware(event["event_at"])).total_seconds() <= 60,
                     "FRESH_REPEAT_EXIT_SIGNAL_REQUIRED")
                report = review_third_position(
                    app, source, captures["account"], pin,
                    entry_id, event, now.isoformat())
                contract = source["plans"][entry_id]["evidence"]["contract"]
                pricing = review_owned_quote(
                    captures["market"], pin, contract,
                    quantity=report["entry_quantity"], as_of=now.isoformat())
                selected = dict(contract)
                for field in ("lot_size", "minimum_lot", "freeze_quantity"):
                    value = selected[field]
                    need(not isinstance(value, bool) and int(value) == value,
                         "INTEGRAL_CONTRACT_QUANTITY_REQUIRED")
                    selected[field] = int(value)
                need(report["remaining_quantity"] == report["entry_quantity"]
                     == selected["lot_size"], "FULL_REPEAT_POSITION_REQUIRED")

                request_at = (
                    aware(json.loads(found[1])["draft"]["created_at"])
                    if found is not None else now)
                need(0 <= (now-request_at).total_seconds() <= 10,
                     "REPEAT_EXIT_REQUEST_STALE")
                request_draft = draft(
                    selected, request_id=exit_id, side="SELL", lots=1,
                    as_of=request_at.isoformat(), order_type="LIMIT",
                    limit_price=pricing["limit_price"],
                    normalized_tick_rupees=normalized_tick(
                        selected, profile=PROFILE))
                saved = adapter.prepare(
                    request_draft, signal_id=event["id"],
                    signal_at=event["event_at"], direction=event["direction"],
                    reservation_reference=parent["reservation_reference"],
                    as_of=now.isoformat())
                wire = adapter._wire(saved, "PLACE")
                from decimal import Decimal
                need(Decimal(str(wire["body"]["price"]))
                     == Decimal(pricing["limit_price"]),
                     "REPEAT_EXIT_WIRE_PRICE_CHANGED")
                with execution_store.tx() as db:
                    prepared_source = read_connection(
                        SourceReader(app, db), pin["scope"],
                        expected_mode="OFFLINE_FIXTURE")
                prepared_report = review_third_position(
                    app, prepared_source, captures["account"], pin,
                    entry_id, event, now.isoformat())
                need(prepared_report["ownership"] == report["ownership"]
                     and prepared_report["remaining_quantity"]
                         == report["remaining_quantity"],
                     "REPEAT_POSITION_CHANGED_DURING_PREPARATION")
                frame_fingerprint = sha(dict(
                    source=prepared_source, captures=captures))
                grant = issue_exit(
                    pin, request_id=exit_id, parent_id=entry_id,
                    event=event, wire=wire,
                    ownership=prepared_report["ownership"],
                    at=now.isoformat())

                def authorize(db, attempt):
                    current = read_connection(
                        SourceReader(app, db), pin["scope"],
                        expected_mode="OFFLINE_FIXTURE")
                    final_at = clock()
                    final_report = review_third_position(
                        app, current, captures["account"], pin,
                        entry_id, event, final_at.isoformat())
                    final_price = review_owned_quote(
                        captures["market"], pin, contract,
                        quantity=final_report["entry_quantity"],
                        as_of=final_at.isoformat())
                    need(sha(dict(source=current, captures=captures))
                         == frame_fingerprint
                         and attempt["operation"] == "PLACE"
                         and attempt["wire"] == wire
                         and Decimal(str(wire["body"]["price"]))
                             == Decimal(final_price["limit_price"]),
                         "REPEAT_EXIT_CONTEXT_CHANGED_BEFORE_ATTEMPT")

                    need(
                        0 <= (final_at-request_at).total_seconds() <= 10,
                        "REPEAT_EXIT_REQUEST_STALE_BEFORE_ATTEMPT")
                    need(
                        0 <= (
                            final_at-aware(event["event_at"])
                        ).total_seconds() <= 60,
                        "REPEAT_EXIT_EVENT_STALE_BEFORE_ATTEMPT")
                    claimed = claim_exit(
                        db, grant, pin,
                        parent_id=entry_id,
                        event=event,
                        ownership=final_report["ownership"],
                        request_id=exit_id,
                        wire=attempt["wire"],
                        at=final_at.isoformat(),
                        attempt_id=attempt["attempt_id"],
                    )
                    checkpoint("AFTER_THIRD_EXIT_CLAIM")
                    return claimed

                adapter.fixture_authorization_claim = authorize
                transport.timeout_after = timeout_after
                result = adapter.submit(exit_id)
                return dict(
                    status="THIRD_EXIT_ATTEMPT_RECORDED",
                    exit_id=exit_id,
                    adapter_result=result,
                    recovery_only=False,
                    new_attempt_created=not result.get(
                        "idempotent_replay", False),
                    orders_sent_to_upstox=False,
                    reservation_release_permission=False,
                    production_execution_enabled=False,
                )
            finally:
                app.rollback()


def record_third_closeout(
    application_store, execution_store, pin, *,
    entry_id, journal, sequence, capture_provider, clock,
    checkpoint=lambda stage: None,
):
    need(pin["scope"].startswith("FIXTURE:"),
         "FIXTURE_THIRD_CLOSEOUT_ONLY")
    records = verified_records(journal)
    need(type(sequence) is int and 1 <= sequence <= len(records),
         "JOURNAL_SEQUENCE_INVALID")
    events = accepted(records[sequence-1])
    need(len(events) == 1 and events[0]["role"] == "EXIT",
         "SINGLE_CONFIRMED_EXIT_REQUIRED")
    event = events[0]
    app_path, broker_path = map(
        rollback_database,
        (application_store.path, execution_store.path))
    need(not app_path.samefile(broker_path),
         "DISTINCT_DATABASES_REQUIRED")
    with application_store.lock():
        with closing(sqlite3.connect(
            app_path.as_uri()+"?mode=rw", uri=True, timeout=10,
        )) as db:
            db.execute(
                "ATTACH DATABASE ? AS broker",
                (broker_path.as_uri()+"?mode=ro",))
            need(
                db.execute("PRAGMA main.journal_mode").fetchone()[0]
                == "delete",
                "DELETE_JOURNAL_REQUIRED")
            db.execute("PRAGMA main.synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                source = read_connection(
                    db, pin["scope"], expected_mode="OFFLINE_FIXTURE")
                snapshot = capture_provider()
                now = clock()
                report = review_third_position(
                    db, source, snapshot, pin,
                    entry_id, event, now.isoformat())
                need(
                    report["remaining_quantity"] == 0
                    and report["pending_exit_quantity"] == 0
                    and report["all_orders_terminal"] is True,
                    "REPEAT_POSITION_NOT_TERMINAL_FLAT")
                input_fingerprint = sha(dict(
                    source=source, snapshot=snapshot, event=event))
                db.execute(
                    "CREATE TABLE IF NOT EXISTS "+CLOSEOUTS+"("
                    "id TEXT PRIMARY KEY,data TEXT NOT NULL)")
                old = db.execute(
                    "SELECT data FROM "+CLOSEOUTS+" WHERE id=?",
                    (entry_id,)).fetchone()

                if old is not None:
                    saved = json.loads(old[0])
                    payload = dict(saved)
                    signature = payload.pop("signature", None)
                    need(
                        isinstance(signature, str)
                        and hmac.compare_digest(
                            sign(payload, pin), signature),
                        "REPEAT_CLOSEOUT_SIGNATURE_INVALID")
                    need(
                        saved.get("model")
                        == "HILEGA_FIXTURE_THIRD_CLOSEOUT_V1"
                        and saved.get("entry_id") == entry_id
                        and saved.get("account_scope") == pin["scope"]
                        and saved.get("input_fingerprint")
                            == input_fingerprint,
                        "THIRD_CLOSEOUT_REPLAY_CONFLICT")
                    db.rollback()
                    return dict(
                        status="THIRD_CLOSEOUT_REPLAY",
                        record=saved, idempotent_replay=True,
                        reservation_release_permission=False,
                        production_execution_enabled=False)
                record = dict(
                    model="HILEGA_FIXTURE_THIRD_CLOSEOUT_V1",
                    entry_id=entry_id, account_scope=pin["scope"],
                    assessed_at=now.isoformat(), event=event,
                    input_fingerprint=input_fingerprint,
                    source_fingerprint=sha(source),
                    snapshot_fingerprint=sha(snapshot),
                    source=source, snapshot=snapshot, review=report,
                    active_references_retired=False,
                    fees_complete=False,
                    reservation_release_permission=False,
                    orders_sent_to_upstox=False,
                    production_execution_enabled=False)
                # Match the persisted JSON representation before signing.
                record = json.loads(json.dumps(record))
                record["signature"] = sign(record, pin)
                db.execute(
                    "INSERT INTO "+CLOSEOUTS+" VALUES(?,?)",
                    (entry_id, json.dumps(record)))
                checkpoint("AFTER_THIRD_CLOSEOUT_INSERT")
                checkpoint("BEFORE_THIRD_CLOSEOUT_COMMIT")
                final_at = clock()
                final_source = read_connection(
                    db, pin["scope"], expected_mode="OFFLINE_FIXTURE")
                need(sha(final_source) == sha(source),
                     "REPEAT_CLOSEOUT_SOURCE_CHANGED")
                final_report = review_third_position(
                    db, final_source, snapshot, pin,
                    entry_id, event, final_at.isoformat())
                need(final_report == report,
                     "REPEAT_CLOSEOUT_REVIEW_CHANGED")
                current_records = verified_records(journal)
                need(current_records[:sequence] == records[:sequence],
                     "REPEAT_CLOSEOUT_JOURNAL_CHANGED")
                db.commit()
                return dict(
                    status="THIRD_CLOSEOUT_RECORDED",
                    record=record, idempotent_replay=False,
                    reservation_release_permission=False,
                    production_execution_enabled=False)
            finally:
                if db.in_transaction:
                    db.rollback()

