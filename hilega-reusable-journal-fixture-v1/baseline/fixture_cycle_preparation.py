"""Reusable fixture-cycle preparation; no live execution authority."""
from contextlib import closing
from decimal import Decimal
import hmac
import json
import sqlite3

from fixture_cycle_cash import review_repeat_entry
from fixture_cycle_history import load_closed_history
from fixture_reference_retirement_candidate import ACTIVE
from owned_exit_pricing_candidate import review_owned_quote
from market_lab.hilega_preparation_runtime_v1.evidence import FLAGS, dependencies
from market_lab.hilega_preparation_runtime_v1.cash_reservation import reserve_local
from market_lab.hilega_preparation_runtime_v1.ownership_state import rollback_database
from market_lab.hilega_preparation_runtime_v1.source import entry_clock_open, event_digest
from market_lab.hilega_execution_port_v1.adapter import validated_request
from market_lab.hilega_execution_port_v1.mapping import draft
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE, normalized_tick
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted
from market_lab.hilega_production_bridge_health_v1 import effective
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import _check, sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign, aware, day

TABLE = "fixture_cycle_admissions"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def market_plan(bundle, pin, direction, now):
    rules, _ = dependencies()
    underlying = rules.quote_map(
        bundle["quotes"], [rules.UNDERLYING])[rules.UNDERLYING]
    age = (now-rules.timestamp(underlying["timestamp"])).total_seconds()
    need(0 <= age <= 10, "UNDERLYING_QUOTE_STALE_OR_FUTURE")
    mapping = rules.select(
        bundle["contracts"], underlying["last_price"], [0], 1,
        now.astimezone(rules.IST).date())
    side = "CE" if direction == "BULLISH" else "PE"
    rows = [r for r in mapping["contracts"] if r["side"] == side]
    need(len(rows) == 1, "EXACT_CURRENT_ATM_CONTRACT_REQUIRED")
    selected = rows[0]
    contract = next(
        c for c in bundle["contracts"]
        if c["instrument_key"] == selected["instrument_key"])
    pricing = review_owned_quote(
        bundle, pin, contract, quantity=selected["quantity"],
        as_of=now.isoformat())
    return contract, selected["quantity"], pricing



def prepare_cycle_fixture(
    application_store, execution_path, pin, *,
    journal, sequence, account_capture, cash_capture, market_bundle,
    expected_version, bridge_run_id, fee_buffer_paise, clock,
    checkpoint=lambda stage: None,
):
    need(pin["scope"].startswith("FIXTURE:"),
         "FIXTURE_CYCLE_PREPARATION_ONLY")
    records = verified_records(journal)
    need(type(sequence) is int and 1 <= sequence <= len(records),
         "JOURNAL_SEQUENCE_INVALID")
    events = accepted(records[sequence-1])
    need(len(events) == 1 and events[0]["role"] == "ENTRY",
         "SINGLE_CONFIRMED_ENTRY_REQUIRED")
    event = events[0]
    key = event["id"]
    app, broker = map(
        rollback_database, (application_store.path, execution_path))
    need(not app.samefile(broker), "DISTINCT_DATABASES_REQUIRED")
    input_fp = sha(dict(
        event=event, account=account_capture, cash=cash_capture,
        market=market_bundle, fee_buffer_paise=fee_buffer_paise,
    ))
    with application_store.lock():
        with closing(sqlite3.connect(
            app.as_uri()+"?mode=rw", uri=True, timeout=10,
        )) as db:
            db.execute("ATTACH DATABASE ? AS broker",
                       (broker.as_uri()+"?mode=rw",))
            need(
                db.execute("PRAGMA main.journal_mode").fetchone()[0] == "delete"
                and db.execute(
                    "PRAGMA broker.journal_mode").fetchone()[0] == "delete",
                "DELETE_JOURNAL_REQUIRED")
            db.execute("PRAGMA main.synchronous=FULL")
            db.execute("PRAGMA broker.synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            try:
                meta = json.loads(db.execute(
                    "SELECT data FROM broker.meta WHERE id=1"
                ).fetchone()[0])
                need(meta == dict(
                    scope=pin["scope"], mode="OFFLINE_FIXTURE"),
                    "EXACT_FIXTURE_ADAPTER_REQUIRED")
                exists = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name=?", (TABLE,)
                ).fetchone()
                old = db.execute(
                    "SELECT data FROM "+TABLE+" WHERE id=?", (key,)
                ).fetchone() if exists else None
                if old:
                    row = json.loads(old[0])
                    payload = dict(row)
                    signed = payload.pop("signature", None)
                    need(isinstance(signed, str)
                         and hmac.compare_digest(sign(payload, pin), signed)
                         and row["input_fingerprint"] == input_fp,
                         "REPEAT_ADMISSION_REPLAY_CONFLICT")
                    for table, fp in row["active_fingerprints"].items():
                        found = db.execute(
                            "SELECT data FROM "+table+" WHERE id=?", (key,)
                        ).fetchone()
                        need(found is not None
                             and sha(json.loads(found[0])) == fp,
                             "REPLAY_ACTIVE_REFERENCE_CHANGED")
                    found = db.execute(
                        "SELECT fingerprint FROM broker.requests WHERE id=?",
                        (key,),
                    ).fetchone()
                    need(found is not None
                         and found[0] == row["request_fingerprint"],
                         "REPLAY_DISABLED_REQUEST_CHANGED")
                    db.rollback()
                    return dict(
                        status="FIXTURE_CYCLE_PREPARATION_REPLAY",
                        idempotent_replay=True,
                        production_execution_enabled=False)


                control = json.loads(db.execute(
                    "SELECT data FROM control WHERE id=1").fetchone()[0])
                stop = db.execute(
                    "SELECT generation,handled FROM sim_stop_state WHERE id=1"
                ).fetchone()
                now = clock()
                need(control["mode"] == "ARMED"
                     and control["version"] == expected_version
                     and control.get("reconciled") is True
                     and control["session_date"] == day(now)
                     and control.get("resumed_at")
                     and aware(event["event_at"]) > aware(control["resumed_at"])
                     and control.get("last_reconciled_at")
                     and 0 <= (now-aware(control["last_reconciled_at"])).total_seconds() <= 30
                     and stop is not None and stop[0] == stop[1],
                     "CONTROL_RESUME_OR_STOP_CHECK_FAILED")
                need(entry_clock_open(now)
                     and entry_clock_open(aware(event["event_at"])),
                     "ENTRY_CLOCK_WINDOW_CLOSED")
                route = json.loads(db.execute(
                    "SELECT data FROM preparation_route WHERE id=1"
                ).fetchone()[0])
                need(route == dict(
                    route="PREPARATION_ONLY",
                    model="APPLICATION_PREPARATION_ROUTE_V1"),
                    "PREPARATION_ROUTE_REQUIRED")
                need(not any(db.execute(
                    "SELECT 1 FROM "+table+" LIMIT 1").fetchone()
                    for table in ACTIVE), "ACTIVE_REFERENCE_REQUIRES_REVIEW")
                need(not any(db.execute(
                    "SELECT 1 FROM "+table+" LIMIT 1").fetchone()
                    for table in ("intents", "sim_orders", "sim_fills",
                                  "sim_allocation_reservations")),
                     "SIMULATOR_ACTIVITY_PRESENT")
                archives = load_closed_history(db, pin)
                need(bool(archives), "CLOSED_HISTORY_REQUIRED")
                requests = db.execute(
                    "SELECT id,fingerprint,data FROM broker.requests ORDER BY rowid"
                ).fetchall()
                attempts = db.execute(
                    "SELECT id,request_id,operation,data FROM broker.attempts"
                ).fetchall()
                receipts = dict(db.execute(
                    "SELECT id,data FROM broker.receipts"))
                historical = _check(
                    "OFFLINE_FIXTURE", requests, attempts, receipts)
                expected_links, expected_ids = [], set()
                for archived in archives:
                    previous = archived["source"]
                    expected_links.extend(_check(
                        "OFFLINE_FIXTURE", previous["requests"],
                        previous["attempts"], previous["receipts"])["bindings"])
                    for rid, fp, raw in previous["requests"]:
                        need(rid not in expected_ids,
                             "DUPLICATE_ARCHIVED_REQUEST")
                        expected_ids.add(rid)
                ordered = lambda links: sorted(
                    links, key=lambda row: row["request_id"])
                need(historical["unbound_request_count"] == 0
                     and {r[0] for r in requests} == expected_ids
                     and ordered(historical["bindings"]) == ordered(expected_links),
                     "BROKER_HISTORY_NOT_FULLY_ARCHIVED")
                need(all(json.loads(raw)["state"] not in {
                    "UNKNOWN", "IN_FLIGHT", "CANCEL_IN_FLIGHT",
                    "CANCEL_OUTCOME_UNKNOWN",
                } for rid, fp, raw in requests), "UNRESOLVED_BROKER_OUTCOME")
                need(not db.execute(
                    "SELECT 1 FROM preparation_consumed WHERE id=?", (key,)
                ).fetchone(), "SIGNAL_ALREADY_CONSUMED")

                def checked(at):
                    contract, quantity, pricing = market_plan(
                        market_bundle, pin, event["direction"], at)
                    n, d = Decimal(pricing["observed_ask"]).as_integer_ratio()
                    premium, remainder = divmod(n*quantity*100, d)
                    need(remainder == 0, "EXACT_PAISE_PREMIUM_REQUIRED")
                    cash = review_repeat_entry(
                        account_capture, cash_capture, archives, pin,
                        signal_at=event["event_at"], premium_paise=premium,
                        fee_buffer_paise=fee_buffer_paise, as_of=at.isoformat())
                    need(cash["status"] == "REENTRY_REFERENCE_CHECKS_PASS",
                         "REPEAT_ENTRY_CASH_BLOCKED")
                    health = json.loads(db.execute(
                        "SELECT data FROM sim_bridge_health WHERE id=1"
                    ).fetchone()[0])
                    need(health.get("run_id") == bridge_run_id
                         and effective(health, at)["healthy"],
                         "BRIDGE_HEALTH_NOT_READY")
                    need(entry_clock_open(at), "ENTRY_CLOCK_WINDOW_CLOSED")
                    return contract, quantity, pricing, premium, cash

                contract, quantity, pricing, premium, cash = checked(now)

                selected = dict(contract)
                for field in ("lot_size", "minimum_lot", "freeze_quantity"):
                    value = selected[field]
                    need(not isinstance(value, bool) and int(value) == value,
                         "INTEGRAL_CONTRACT_QUANTITY_REQUIRED")
                    selected[field] = int(value)
                need(quantity == selected["lot_size"], "EXACTLY_ONE_LOT_REQUIRED")
                request_draft = draft(
                    selected, request_id=key, side="BUY", lots=1,
                    as_of=now.isoformat(), order_type="LIMIT",
                    limit_price=pricing["observed_ask"],
                    normalized_tick_rupees=normalized_tick(
                        selected, profile=PROFILE))
                request, fingerprint = validated_request(
                    request_draft, signal_id=key,
                    signal_at=event["event_at"], direction=event["direction"],
                    reservation_reference=key, as_of=now.isoformat())
                budget = premium + fee_buffer_paise
                evidence = dict(
                    contract=contract, instrument=contract["instrument_key"],
                    quantity=quantity, bundle_fingerprint=sha(market_bundle),
                    cash_capture_fingerprint=sha(cash_capture),
                    half_cash_cap_cents=cash["half_cash_budget_paise"],
                    repeat_entry_reference_checks_passed=True,
                    evidence_checks_passed=False,
                    legacy_first_entry_authorization_compatible=False)
                plan = dict(
                    FLAGS, model="HILEGA_FIXTURE_CYCLE_ENTRY_PLAN_V1",
                    cycle_index=archives[0]["cycle_count"]+1,
                    id=key, signal_at=event["event_at"],
                    direction=event["direction"], account_scope=pin["scope"],
                    instrument=contract["instrument_key"], quantity=quantity,
                    evidence=evidence, created_at=now.isoformat(),
                    status="FIXTURE_REPEAT_PREPARED_DISABLED")
                hold = dict(
                    FLAGS, id=key, held_cents=budget, real_cash_reserved=False,
                    evidence_mode="REAL_CASH_OBSERVED_SHADOW_ONLY")
                out = dict(
                    FLAGS, id=key, reservation_reference=key,
                    bundle_fingerprint=sha(market_bundle),
                    instrument=plan["instrument"], quantity=quantity,
                    status="NON_EXECUTABLE_REPEAT_POLICY_PENDING",
                    request_body=None,
                    disabled_request_candidate=dict(
                        FLAGS, draft=request_draft, premium_cents=premium,
                        fee_buffer_cents=fee_buffer_paise, budget_cents=budget,
                        policy_approved_for_production=False))
                def insert(table, value):
                    db.execute("INSERT INTO "+table+" VALUES(?,?)",
                               (key, json.dumps(value, sort_keys=True)))
                insert("preparation_plans", plan)
                insert("preparation_shadow_holds", hold)
                insert("preparation_outbox", out)
                reserve_local(
                    db, plan, hold, out, pin,
                    {"half_cash_cap_cents": cash["half_cash_budget_paise"]},
                    fingerprint, now=now)
                binding = dict(
                    FLAGS, model="HILEGA_FIXTURE_CYCLE_DISABLED_BINDING_V1",
                    id=key, account_scope=pin["scope"],
                    request_fingerprint=fingerprint,
                    plan_fingerprint=sha(plan), hold_fingerprint=sha(hold),
                    outbox_fingerprint=sha(out), held_cents=budget,
                    cash_cap_cents=cash["half_cash_budget_paise"],
                    bundle_fingerprint=sha(market_bundle),
                    local_budget_reference_bound=True, broker_cash_locked=False,
                    status="FIXTURE_REPEAT_PREPARED_DISABLED")

                insert("preparation_request_bindings", binding)
                checkpoint("AFTER_ACTIVE_REFERENCES")
                db.execute("INSERT INTO broker.requests VALUES(?,?,?)",
                           (key, fingerprint, json.dumps(request, sort_keys=True)))
                db.execute("INSERT INTO broker.events(data) VALUES(?)",
                           (json.dumps(dict(
                               type="REQUEST_PREPARED", request_id=key,
                               origin="FIXTURE_REPEAT_ATOMIC_BINDING")),))
                checkpoint("AFTER_DISABLED_REQUEST_INSERT")
                db.execute("INSERT INTO preparation_consumed VALUES(?,?)",
                           (key, event_digest(event)))
                row = dict(
                    FLAGS, model="HILEGA_FIXTURE_CYCLE_ADMISSION_V1",
                    cycle_index=archives[0]["cycle_count"]+1,
                    input_fingerprint=input_fp,
                    request_fingerprint=fingerprint,
                    active_fingerprints={
                        table: sha(json.loads(db.execute(
                            "SELECT data FROM "+table+" WHERE id=?", (key,)
                        ).fetchone()[0])) for table in ACTIVE},
                    account_capture=account_capture,
                    cash_capture=cash_capture, market_bundle=market_bundle,
                    event=event,
                    closed_history_fingerprints=[sha(a) for a in archives])
                row["signature"] = sign(row, pin)
                db.execute("CREATE TABLE IF NOT EXISTS "+TABLE+
                           "(id TEXT PRIMARY KEY,data TEXT NOT NULL)")
                insert(TABLE, row)
                paused = dict(
                    control, mode="PAUSED", version=control["version"]+1,
                    reconciled=False,
                    reason="FIXTURE_REPEAT_PREPARATION_REQUIRES_REVIEW")
                db.execute("UPDATE control SET data=? WHERE id=1",
                           (json.dumps(paused, sort_keys=True),))
                checkpoint("BEFORE_REPEAT_COMMIT")
                need([sha(a) for a in load_closed_history(db, pin)]
                     == [sha(a) for a in archives],
                     "THIRD_CLOSED_BASELINE_CHANGED_BEFORE_COMMIT")
                final_now = clock()
                need(checked(final_now) ==
                     (contract, quantity, pricing, premium, cash),
                     "REPEAT_EVIDENCE_CHANGED")
                need(0 <= (final_now-now).total_seconds() <= 10,
                     "DISABLED_REQUEST_STALE_BEFORE_COMMIT")
                current = verified_records(journal)
                need(len(current) >= sequence
                     and current[sequence-1]["record_hash"]
                         == records[sequence-1]["record_hash"],
                     "JOURNAL_CHANGED_BEFORE_COMMIT")
                db.commit()
                return dict(
                    status="FIXTURE_CYCLE_PREPARED_DISABLED",
                    request_id=key, direction=event["direction"],
                    quantity=quantity, budget_paise=budget,
                    half_cash_cap_paise=cash["half_cash_budget_paise"],
                    idempotent_replay=False,
                    previous_broker_history_preserved=True,
                    orders_sent=False, production_execution_enabled=False,
                    legacy_execution_authorization_compatible=False)
            except BaseException:
                db.rollback()
                raise

