"""Fixture-only chronological entry/exit fill references. Never release authority."""
from contextlib import closing
import hmac
import json
import sqlite3
from atomic_exit_binding import rollback_database
from bridge import validate_account_rows, ident
from exit_intent import MODEL, validate_reference
from historical_receipt_checks import _check, sha
from risk_evidence_audit import need
from signature_checks import verify, sign, aware, day


def reconcile_fixture_exit(reference_path,adapter_path,pin,snapshot,exit_id,*,
                           as_of,checkpoint=lambda stage:None):
    need(pin["scope"].startswith("FIXTURE:"),"FIXTURE_ACCOUNT_REQUIRED")
    verify(snapshot,pin,as_of=as_of)
    ident(snapshot["snapshot_id"])
    need(snapshot.get("profile_verified_before_and_after") is True
         and snapshot.get("account_position_rows_complete") is True
         and snapshot.get("source_atomic") is False
         and snapshot.get("position_fill_linkage_verified") is False
         and snapshot.get("live_pnl") is None,"READ_ONLY_COMPLETE_CAPTURE_REQUIRED")
    need(all(isinstance(snapshot.get(k),list) for k in ("orders","trades","positions")),
         "ACCOUNT_LISTS_REQUIRED")
    need(day(aware(snapshot["completed_at"]))==snapshot["session_date"],
         "CAPTURE_SESSION_MISMATCH")
    orders,positions=validate_account_rows(snapshot)
    app,adapter=map(rollback_database,(reference_path,adapter_path))
    need(not app.samefile(adapter),"DISTINCT_DATABASES_REQUIRED")
    need(app.stat().st_dev==adapter.stat().st_dev,"SAME_FILESYSTEM_REQUIRED")
    with closing(sqlite3.connect(app.resolve().as_uri()+"?mode=rw",
                                uri=True,timeout=15)) as db:
        db.execute("ATTACH DATABASE ? AS broker",(adapter.resolve().as_uri()+"?mode=ro",))
        db.execute("PRAGMA main.synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        try:
            meta=db.execute("SELECT data FROM exit_reference_meta WHERE id=1").fetchone()
            need(meta is not None and json.loads(meta[0])==dict(
                model=MODEL,scope=pin["scope"],mode="STAGED_REFERENCE_ONLY"),
                "REFERENCE_STORE_SCOPE_OR_MODE_MISMATCH")
            meta=db.execute("SELECT data FROM broker.meta WHERE id=1").fetchone()
            need(meta is not None and json.loads(meta[0])==dict(
                scope=pin["scope"],mode="OFFLINE_FIXTURE"),"FIXTURE_ADAPTER_REQUIRED")
            refrow=db.execute("SELECT data FROM exit_references WHERE id=?",(exit_id,)).fetchone()
            ackrow=db.execute("SELECT data FROM exit_acknowledgements WHERE id=?",(exit_id,)).fetchone()
            bindrow=db.execute("SELECT data FROM exit_request_bindings WHERE id=?",(exit_id,)).fetchone()
            need(refrow is not None and ackrow is not None and bindrow is not None,
                 "DURABLE_EXIT_ACK_AND_BINDING_REQUIRED")
            ref,ack,binding=map(lambda r:json.loads(r[0]),(refrow,ackrow,bindrow))
            validate_reference(ref,pin,as_of=ref["created_at"])
            need(ref["id"]==exit_id==ack["id"]==binding["id"]
                 and ref["session_date"]==snapshot["session_date"],
                 "EXIT_REFERENCE_SESSION_OR_ID_MISMATCH")
            need(sha(ref)==binding["reference_fingerprint"]
                 and sha(binding)==ack["atomic_binding_fingerprint"]
                 and binding["account_scope"]==pin["scope"]
                 and binding["parent_request_id"]==ref["parent_request_id"]
                 and ack["parent_request_id"]==ref["parent_request_id"],
                 "ACK_OR_BINDING_REFERENCE_CHANGED")
            need(all(ack.get(k) is False for k in (
                "fill_confirmed","flat_confirmed","retry_allowed",
                "strategy_ownership_verified","orders_sent","production_execution_enabled",
                "reservation_release_permission","production_ready")),
                "ACK_AUTHORITY_FLAGS_CHANGED")
            requests=db.execute("SELECT id,fingerprint,data FROM broker.requests").fetchmany(10001)
            attempts=db.execute("SELECT id,request_id,operation,data FROM broker.attempts").fetchmany(10001)
            receiptrows=db.execute("SELECT id,data FROM broker.receipts").fetchmany(10001)
            need(max(len(requests),len(attempts),len(receiptrows))<=10000,"SOURCE_LIMIT_EXCEEDED")
            receipts=dict(receiptrows)
            links={r["request_id"]:r for r in _check(
                "OFFLINE_FIXTURE",requests,attempts,receipts)["bindings"]}
            need(exit_id in links and ref["parent_request_id"] in links,
                 "CURRENT_DURABLE_PARENT_AND_EXIT_ACK_REQUIRED")
            entry,exitlink=links[ref["parent_request_id"]],links[exit_id]
            reqs={r[0]:r for r in requests}
            need(reqs[exit_id][1]==binding["request_fingerprint"]==ack["request_fingerprint"]
                 and reqs[ref["parent_request_id"]][1]==ref["parent_request_fingerprint"]
                 and sha(entry["order_id"])==ref["parent_order_fingerprint"]
                 and exitlink["order_id"]==ack["order_id"]
                 and ack["attempt_id"] in receipts
                 and sha(json.loads(receipts[ack["attempt_id"]]))==ack["receipt_fingerprint"],
                 "DURABLE_ACK_REFERENCE_CHANGED")
            need(entry["side"]=="BUY" and exitlink["side"]=="SELL"
                 and all(entry[k]==exitlink[k]==ref[k] for k in ("instrument","product"))
                 and exitlink["quantity"]==ref["quantity"],"EXIT_PARENT_CONTRACT_MISMATCH")
            allowed={entry["order_id"],exitlink["order_id"]}
            need(set(orders)==allowed,"MISSING_OR_UNLINKED_ACCOUNT_ORDER")
            for link in (entry,exitlink):
                order=orders[link["order_id"]]
                need(all(order[k]==link[k] for k in ("instrument","product","side","quantity")),
                     "ACK_ORDER_CONTRACT_MISMATCH")
                req=json.loads(reqs[link["request_id"]][2])
                need(aware(order["placed_at"])>=aware(req["signal_at"]),
                     "ORDER_PRECEDES_INTENT")
            need(orders[entry["order_id"]]["status"] in {"FILLED","CANCELLED","REJECTED"},
                 "PARENT_ENTRY_NOT_TERMINAL")
            need(orders[entry["order_id"]]["filled"]>=ref["quantity"],
                 "PARENT_FILL_BASELINE_BELOW_EXIT_INTENT")
            fills={}
            timeline=[]
            for fill in snapshot["trades"]:
                key=fill["order_id"]+"|"+fill["trade_id"]
                fills[key]=fill
                timeline.append((aware(fill["filled_at"]),fill))
            buy_times={at for at,f in timeline if f["side"]=="BUY"}
            sell_times={at for at,f in timeline if f["side"]=="SELL"}
            need(not buy_times.intersection(sell_times),"OPPOSITE_FILL_TIME_ORDER_AMBIGUOUS")
            remaining=0
            for at,fill in sorted(timeline,key=lambda item:item[0]):
                remaining+=(1 if fill["side"]=="BUY" else -1)*fill["quantity"]
                need(remaining>=0,"EXIT_PRECEDES_AVAILABLE_ENTRY_FILLS")
            key=(ref["instrument"],ref["product"])
            need(key in positions,"MISSING_POSITION_ROW_IS_NOT_FLAT")
            need(positions[key]==remaining,"BROKER_POSITION_QUANTITY_MISMATCH")
            need(not any(q for k,q in positions.items() if k!=key),"UNLINKED_ACCOUNT_EXPOSURE")
            db.execute("CREATE TABLE IF NOT EXISTS exit_fill_state(id TEXT PRIMARY KEY,data TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS exit_fill_snapshots("
                "id TEXT PRIMARY KEY,fingerprint TEXT)")
            old=db.execute("SELECT data FROM exit_fill_state WHERE id=?",(exit_id,)).fetchone()
            if old:
                previous=json.loads(old[0]);payload=dict(previous)
                signature=payload.pop("signature",None)
                need(isinstance(signature,str) and hmac.compare_digest(
                    sign(payload,pin),signature),"PERSISTED_FILL_STATE_SIGNATURE_INVALID")
                need(aware(snapshot["generated_at"])>=aware(previous["observed_at"]),
                     "OUT_OF_ORDER_FILL_SNAPSHOT")
                need(all(k in fills and fills[k]==v for k,v in previous["fills"].items()),
                     "PREVIOUS_FILL_CHANGED_OR_DISAPPEARED")
                for oid,o in orders.items():
                    p=previous["orders"][oid]
                    need(o["filled"]>=p["filled"],"CUMULATIVE_FILL_REGRESSION")
                    need(p["status"] not in {"FILLED","CANCELLED","REJECTED"}
                         or o["status"]==p["status"],"TERMINAL_ORDER_STATUS_CHANGED")
            sid=snapshot["snapshot_id"];fingerprint=sha(snapshot)
            oldshot=db.execute("SELECT fingerprint FROM exit_fill_snapshots WHERE id=?",(sid,)).fetchone()
            need(oldshot is None or oldshot[0]==fingerprint,"SNAPSHOT_ID_REUSED_WITH_CHANGED_EVIDENCE")
            terminal=all(o["status"] in {"FILLED","CANCELLED","REJECTED"} for o in orders.values())
            state=dict(id=exit_id,account_scope=pin["scope"],observed_at=snapshot["generated_at"],
                snapshot_id=sid,fills=fills,orders=orders,remaining_quantity=remaining,
                fixture_flat_reference_verified=remaining==0 and terminal,
                all_referenced_orders_terminal=terminal,
                production_execution_enabled=False,reservation_release_permission=False)
            state["signature"]=sign(state,pin)
            db.execute("INSERT OR REPLACE INTO exit_fill_state VALUES(?,?)",(exit_id,json.dumps(state)))
            checkpoint("AFTER_STATE_WRITE")
            db.execute("INSERT OR IGNORE INTO exit_fill_snapshots VALUES(?,?)",(sid,fingerprint))
            checkpoint("BEFORE_COMMIT")
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return dict(status="FIXTURE_EXIT_FILL_REFERENCES_RECONCILED",
        remaining_quantity=remaining,fixture_flat_reference_verified=remaining==0 and terminal,
        all_referenced_orders_terminal=terminal,fill_count=len(fills),
        fixture_only=True,runtime_integration=False,live_ownership_verified=False,
        fees_complete=False,net_pnl=None,retry_allowed=False,
        orders_sent=False,production_execution_enabled=False,
        reservation_release_permission=False,production_ready=False)
