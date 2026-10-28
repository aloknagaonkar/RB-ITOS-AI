"""Persist an unapproved LIMIT candidate; no broker submission authority."""
import json
import os
from decimal import Decimal
from pathlib import Path

from . import ensure_route
from .evidence import FLAGS, aware, day, digest, need, readonly
from .pricing_preview import preview
from .reference_review import review
from market_lab.hilega_nifty_option_price_grid_v1 import (
    normalized_tick, number,
)
from market_lab.hilega_execution_port_v1.mapping import draft
from market_lab.hilega_production_foundation.core import Service, encode

POLICY = "UNAPPROVED_ONE_LOT_BUY_LIMIT_AT_ASK_V1"


def fresh_plan(bundle, pin, direction, now, profile):
    result = preview(bundle, pin, as_of=now.isoformat(), profile=profile)
    plans = [p for p in result["plans"] if p["direction"] == direction]
    need(
        len(plans) == 1 and plans[0]["evidence_checks_passed"] is True,
        "FRESH_CANDIDATE_EVIDENCE_REQUIRED",
    )
    return plans[0]


def record(db, table, key):
    row = db.execute(
        "SELECT data FROM " + table + " WHERE id=?", (key,),
    ).fetchone()
    need(row is not None, "PREPARATION_RECORD_REQUIRED")
    return json.loads(row[0])


def stage(service, plan_id, pin, *, fee_buffer_cents, profile):
    need(type(service) is Service, "INSTALLED_CONTROLLER_SERVICE_REQUIRED")
    need(
        type(fee_buffer_cents) is int and fee_buffer_cents > 0,
        "EXPLICIT_POSITIVE_FEE_BUFFER_REQUIRED",
    )
    store = service.store
    adapter_path = Path(os.getenv(
        "HILEGA_PREPARATION_ADAPTER_DB",
        "data/research/hilega-broker-adapter-closed/adapter.sqlite",
    ))

    with store.lock():
        ensure_route(store)
        checked = review(store.path, adapter_path, pin)
        references = {
            row["preparation_id"]: row["reference_fingerprint"]
            for row in checked["references"]
        }
        need(
            len(references) == 1 and plan_id in references,
            "EXACTLY_ONE_MATCHING_PREPARATION_REQUIRED",
        )

        with readonly(adapter_path) as broker, store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            meta = broker.execute(
                "SELECT data FROM meta WHERE id=1"
            ).fetchone()
            need(
                meta is not None and json.loads(meta[0]) == {
                    "scope": pin["scope"], "mode": "LIVE_CLOSED",
                },
                "ADAPTER_SCOPE_CHANGED",
            )
            need(
                not any(broker.execute(
                    "SELECT 1 FROM " + table + " LIMIT 1"
                ).fetchone() for table in ("requests", "attempts", "receipts")),
                "ADAPTER_ACTIVITY_REQUIRES_REVIEW",
            )
            control = json.loads(db.execute(
                "SELECT data FROM control WHERE id=1"
            ).fetchone()[0])
            stop = db.execute(
                "SELECT generation,handled FROM sim_stop_state WHERE id=1"
            ).fetchone()
            need(
                control["mode"] == "PAUSED" and stop is not None
                and stop[0] == stop[1],
                "PAUSED_WITH_NO_PENDING_STOP_REQUIRED",
            )
            plan = record(db, "preparation_plans", plan_id)
            hold = record(db, "preparation_shadow_holds", plan_id)
            out = record(db, "preparation_outbox", plan_id)
            need(
                digest({"plan": plan, "hold": hold, "outbox": out})
                == references[plan_id],
                "PREPARATION_CHANGED_BEFORE_CANDIDATE",
            )
            need(
                all(db.execute(
                    "SELECT COUNT(*) FROM " + table
                ).fetchone()[0] == 1 for table in (
                    "preparation_plans", "preparation_shadow_holds",
                    "preparation_outbox",
                )),
                "CONFLICTING_PREPARATION_RECORDS",
            )
            fingerprint = plan["evidence"]["bundle_fingerprint"]
            row = db.execute(
                "SELECT data FROM preparation_evidence WHERE digest=?",
                (fingerprint,),
            ).fetchone()
            need(row is not None, "SIGNED_EVIDENCE_REQUIRED")
            bundle = json.loads(row[0])
            need(digest(bundle) == fingerprint, "SIGNED_EVIDENCE_CHANGED")

            now = service.now()
            signal = aware(plan["signal_at"])
            need(
                day(now) == day(signal) == control["session_date"]
                and 0 <= (now - signal).total_seconds() <= 60,
                "FRESH_SAME_SESSION_SIGNAL_REQUIRED",
            )
            selected = fresh_plan(
                bundle, pin, plan["direction"], now, profile,
            )
            need(
                selected["instrument"] == plan["instrument"]
                and selected["quantity"] == plan["quantity"],
                "CANDIDATE_CONTRACT_CHANGED",
            )
            contract = dict(selected["contract"])
            # Explicitly normalize only positive integral quantity metadata.
            for name in ("lot_size", "minimum_lot", "freeze_quantity"):
                value = number(contract[name])
                need(value == value.to_integral_value(),
                     "INTEGRAL_CONTRACT_QUANTITY_REQUIRED")
                contract[name] = int(value)
            quantity = selected["quantity"]
            need(quantity == contract["lot_size"], "EXACTLY_ONE_LOT_REQUIRED")
            ask = number(selected["pricing_preview"]["ask"])
            numerator, denominator = ask.as_integer_ratio()
            premium, remainder = divmod(
                numerator * quantity * 100, denominator,
            )
            need(remainder == 0, "EXACT_PAISE_PREMIUM_REQUIRED")
            budget = premium + fee_buffer_cents
            need(
                budget <= selected["half_cash_cap_cents"]
                and budget <= hold["held_cents"],
                "CANDIDATE_EXCEEDS_CASH_CAP_OR_SHADOW_HOLD",
            )

            old = out.get("disabled_request_candidate")
            if old is not None:
                need(
                    isinstance(old, dict) and isinstance(old.get("draft"), dict)
                    and isinstance(old["draft"].get("created_at"), str),
                    "EXISTING_CANDIDATE_INVALID",
                )
                request_at = aware(old["draft"]["created_at"])
                need(
                    0 <= (now - request_at).total_seconds() <= 10,
                    "EXISTING_CANDIDATE_STALE_REQUIRES_REVIEW",
                )
            else:
                request_at = now

            request = draft(
                contract, request_id=plan_id, side="BUY", lots=1,
                as_of=request_at.isoformat(), order_type="LIMIT",
                limit_price=ask,
                normalized_tick_rupees=normalized_tick(
                    contract, profile=profile,
                ),
            )
            need(
                Decimal(str(request["body"]["price"])) == ask,
                "WIRE_PRICE_PRECISION_CHANGED",
            )
            base_outbox = {
                key: value for key, value in out.items()
                if key != "disabled_request_candidate"
            }
            candidate = dict(
                FLAGS,
                model="HILEGA_DISABLED_LIMIT_CANDIDATE_V1",
                policy_id=POLICY,
                policy_approved_for_production=False,
                fee_buffer_approved_for_production=False,
                tick_units_verified=False,
                executable_request_created=False,
                production_ready=False,
                preparation_id=plan_id,
                reservation_reference=plan_id,
                premium_cents=premium,
                fee_buffer_cents=fee_buffer_cents,
                budget_cents=budget,
                input_fingerprint=digest({
                    "plan": plan, "shadow_hold": hold,
                    "outbox": base_outbox, "profile": profile,
                    "fee_buffer_cents": fee_buffer_cents, "policy": POLICY,
                }),
                draft=request,
            )
            final_now = service.now()
            need(
                0 <= (final_now - request_at).total_seconds() <= 10,
                "CANDIDATE_REQUEST_STALE_BEFORE_COMMIT",
            )
            fresh_plan(bundle, pin, plan["direction"], final_now, profile)
            if old is not None:
                need(old == candidate, "IMMUTABLE_CANDIDATE_CONFLICT")
                return dict(candidate, idempotent_replay=True)

            out["disabled_request_candidate"] = candidate
            # The actionable outbox remains disabled and unsent.
            need(out["request_body"] is None, "OUTBOX_MUST_REMAIN_DISABLED")
            db.execute(
                "UPDATE preparation_outbox SET data=? WHERE id=?",
                (encode(out), plan_id),
            )
    return dict(candidate, idempotent_replay=False)
