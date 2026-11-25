"""Historical preparation-reference checks; no broker ownership authority."""
import json
from pathlib import Path

from .evidence import FLAGS, aware, digest, need, readonly
from .pricing_preview import preview
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE


def records(db, table):
    rows = db.execute("SELECT id,data FROM " + table).fetchall()
    result = {}
    for key, raw in rows:
        value = json.loads(raw)
        need(isinstance(value, dict), "PREPARATION_RECORD_INVALID")
        need(value.get("id") == key, "PREPARATION_RECORD_ID_MISMATCH")
        need(key not in result, "DUPLICATE_PREPARATION_RECORD")
        result[key] = value
    return result


def review(application_db, adapter_db, pin):
    need(
        Path(application_db).resolve() != Path(adapter_db).resolve(),
        "DISTINCT_SOURCE_DATABASES_REQUIRED",
    )
    links = []
    with readonly(application_db) as app, readonly(adapter_db) as broker:
        route = app.execute(
            "SELECT data FROM preparation_route WHERE id=1"
        ).fetchone()
        need(
            route is not None and json.loads(route[0]) == {
                "route": "PREPARATION_ONLY",
                "model": "APPLICATION_PREPARATION_ROUTE_V1",
            },
            "PERSISTED_PREPARATION_ROUTE_REQUIRED",
        )
        meta = broker.execute("SELECT data FROM meta WHERE id=1").fetchone()
        need(
            meta is not None and json.loads(meta[0]) == {
                "scope": pin["scope"], "mode": "LIVE_CLOSED",
            },
            "LIVE_CLOSED_ACCOUNT_SCOPE_REQUIRED",
        )
        need(
            not any(
                broker.execute("SELECT 1 FROM " + table + " LIMIT 1").fetchone()
                for table in ("requests", "attempts", "receipts")
            ),
            "UNEXPECTED_ADAPTER_ACTIVITY_FOR_UNSENT_ROUTE",
        )
        need(
            not any(
                app.execute("SELECT 1 FROM " + table + " LIMIT 1").fetchone()
                for table in (
                    "intents", "sim_orders", "sim_fills",
                    "sim_allocation_reservations",
                )
            ),
            "EXECUTION_HISTORY_CANNOT_MIX_WITH_UNSENT_PREPARATION",
        )

        plans = records(app, "preparation_plans")
        holds = records(app, "preparation_shadow_holds")
        outbox = records(app, "preparation_outbox")
        need(
            set(plans) == set(holds) == set(outbox),
            "PLAN_HOLD_OUTBOX_IDS_MISMATCH",
        )
        control = json.loads(app.execute(
            "SELECT data FROM control WHERE id=1"
        ).fetchone()[0])
        if plans:
            need(control["mode"] == "PAUSED", "PENDING_PREPARATION_MUST_BE_PAUSED")

        for key, plan in plans.items():
            hold, out = holds[key], outbox[key]
            need(
                all(row.get(flag) is False
                    for row in (plan, hold, out) for flag in FLAGS),
                "PREPARATION_PERMISSION_FLAGS_CHANGED",
            )
            need(
                plan["status"] == "EVIDENCE_LINKED_UNSENT"
                and plan["account_scope"] == pin["scope"],
                "UNSENT_PLAN_ACCOUNT_REQUIRED",
            )
            need(
                hold["evidence_mode"] == "REAL_CASH_OBSERVED_SHADOW_ONLY"
                and hold["real_cash_reserved"] is False,
                "SHADOW_HOLD_CANNOT_CLAIM_REAL_RESERVATION",
            )
            need(
                out["status"] == "NON_EXECUTABLE_PRICING_POLICY_PENDING"
                and "request_body" in out and out["request_body"] is None,
                "NON_EXECUTABLE_OUTBOX_REQUIRED",
            )
            need(
                out["reservation_reference"] == key,
                "OUTBOX_HOLD_REFERENCE_MISMATCH",
            )
            need(
                type(plan["quantity"]) is int and plan["quantity"] > 0
                and out["quantity"] == plan["quantity"]
                and type(out["quantity"]) is int
                and out["instrument"] == plan["instrument"],
                "OUTBOX_PLAN_CONTRACT_MISMATCH",
            )
            evidence = plan["evidence"]
            fingerprint = evidence["bundle_fingerprint"]
            need(
                out["bundle_fingerprint"] == fingerprint,
                "OUTBOX_EVIDENCE_REFERENCE_MISMATCH",
            )
            row = app.execute(
                "SELECT data FROM preparation_evidence WHERE digest=?",
                (fingerprint,),
            ).fetchone()
            need(row is not None, "PERSISTED_SIGNED_EVIDENCE_REQUIRED")
            bundle = json.loads(row[0])
            need(digest(bundle) == fingerprint, "PERSISTED_EVIDENCE_HASH_MISMATCH")

            # Historical assessment at creation time, never current clearance.
            created = aware(plan["created_at"])
            signal = aware(plan["signal_at"])
            need(
                0 <= (created - signal).total_seconds() <= 60,
                "PREPARATION_SIGNAL_TIME_MISMATCH",
            )
            assessed = preview(
                bundle, pin, as_of=plan["created_at"], profile=PROFILE,
            )
            selected = [
                value for value in assessed["plans"]
                if value["direction"] == plan["direction"]
            ]
            need(len(selected) == 1, "EXACT_DIRECTIONAL_PLAN_REQUIRED")
            expected = selected[0]
            need(
                expected["evidence_checks_passed"] is True
                and evidence["evidence_checks_passed"] is True,
                "ORIGINAL_PREPARATION_EVIDENCE_NOT_CLEARED",
            )
            fields = (
                "bundle_fingerprint", "cash_capture_fingerprint",
                "contract_fingerprint", "quote_fingerprint", "instrument",
                "quantity", "proposed_cost_cents",
            )
            need(
                all(evidence[field] == expected[field] for field in fields)
                and plan["instrument"] == expected["instrument"]
                and plan["quantity"] == expected["quantity"],
                "PERSISTED_PLAN_EVIDENCE_MISMATCH",
            )
            cost = expected["proposed_cost_cents"]
            need(
                type(hold["held_cents"]) is int
                and hold["held_cents"] > 0 and hold["held_cents"] == cost,
                "SHADOW_HOLD_AMOUNT_MISMATCH",
            )
            consumed = app.execute(
                "SELECT fingerprint FROM preparation_consumed WHERE id=?",
                (key,),
            ).fetchone()
            need(consumed is not None, "CONSUMED_SIGNAL_REFERENCE_REQUIRED")
            links.append(dict(
                preparation_id=key,
                reference_fingerprint=digest({
                    "plan": plan, "hold": hold, "outbox": out,
                }),
            ))

    return dict(
        FLAGS,
        model="HILEGA_PREPARATION_REFERENCE_REVIEW_V1",
        status=(
            "UNSENT_PREPARATION_REFERENCES_CHECKED"
            if links else "NO_PREPARATION_RECORDS"
        ),
        reference_count=len(links),
        references=links,
        historical_assessment_only=True,
        current_market_freshness_verified=False,
        application_hold_link_verified=False,
        broker_order_ownership_verified=False,
        production_ready=False,
        broker_reads_performed=False,
        next_requirement="REAL_RESERVATION_AND_EXECUTABLE_REQUEST_REQUIRED",
    )
