from pathlib import Path

module = Path(
    "backend/market_lab/hilega_preparation_runtime_v1/limit_candidate.py"
)
tests = Path("tests/test_hilega_limit_candidate_v1.py")

module_text = r'''"""Persist an unapproved LIMIT candidate; no broker submission authority."""
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
'''

test_text = r'''import json
from datetime import timedelta

import pytest

from test_hilega_application_preparation_v1 import env, process, counts
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE
from market_lab.hilega_preparation_runtime_v1.evidence import Blocked
from market_lab.hilega_preparation_runtime_v1.limit_candidate import stage
from market_lab.hilega_execution_port_v1.adapter import (
    Adapter, Store, HttpTransport,
)


def plan_id(env):
    with env["store"].db() as db:
        return db.execute("SELECT id FROM preparation_plans").fetchone()[0]


def run(env, fee=10000):
    return stage(
        env["s"], plan_id(env), PIN,
        fee_buffer_cents=fee, profile=PROFILE,
    )


def saved(env):
    with env["store"].db() as db:
        return json.loads(db.execute(
            "SELECT data FROM preparation_outbox"
        ).fetchone()[0])


def test_actual_application_plan_gets_disabled_cash_bounded_limit(env):
    process(env)
    before_counts = counts(env)
    control = env["store"].control()
    calls = len(env["calls"])
    result = run(env)
    body = result["draft"]["body"]
    assert body["order_type"] == "LIMIT"
    assert body["transaction_type"] == "BUY"
    assert body["quantity"] == 65
    assert body["price"] == 100
    assert body["product"] == "I" and body["validity"] == "DAY"
    assert body["is_amo"] is False and body["slice"] is False
    assert "market_protection" not in body
    assert result["premium_cents"] == 650000
    assert result["budget_cents"] == 660000
    assert result["draft"]["submission_enabled"] is False
    assert result["policy_approved_for_production"] is False
    assert result["real_funds_reservation_verified"] is False
    assert result["entry_permission"] is False
    out = saved(env)
    assert out["request_body"] is None
    assert out["status"] == "NON_EXECUTABLE_PRICING_POLICY_PENDING"
    assert out["disabled_request_candidate"]["reservation_reference"] == plan_id(env)
    assert counts(env) == before_counts
    assert env["store"].control() == control
    assert len(env["calls"]) == calls


def test_candidate_is_accepted_by_real_mapper_adapter_but_cannot_submit(
    env, tmp_path,
):
    process(env)
    candidate = run(env)
    key = plan_id(env)
    adapter = Adapter(
        Store(tmp_path / "closed-adapter.sqlite", PIN["scope"], "LIVE_CLOSED"),
        HttpTransport(lambda: pytest.fail("Token must not be accessed")),
    )
    prepared = adapter.prepare(
        candidate["draft"], signal_id=key,
        signal_at="2026-10-26T09:25:00+05:30",
        direction="BULLISH", reservation_reference=key,
        as_of=env["clock"][0].isoformat(),
    )
    assert prepared["reservation_verified"] is False
    result = adapter.submit(key)
    assert result["status"] == "PRODUCTION_MUTATIONS_CLOSED_IN_CODE"
    assert adapter.status()["attempts"] == []


def test_duplicate_preserves_original_candidate(env):
    process(env)
    first = run(env)
    before = saved(env)
    env["clock"][0] += timedelta(milliseconds=10)
    second = run(env)
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert saved(env) == before


def test_changed_fee_cannot_overwrite_candidate(env):
    process(env)
    run(env)
    before = saved(env)
    with pytest.raises(Blocked, match="IMMUTABLE_CANDIDATE_CONFLICT"):
        run(env, fee=9000)
    assert saved(env) == before


@pytest.mark.parametrize("fee", [0, -1, True, 1.5])
def test_fee_buffer_must_be_explicit_positive_integer(env, fee):
    process(env)
    before = saved(env)
    with pytest.raises(Blocked, match="FEE_BUFFER"):
        run(env, fee=fee)
    assert saved(env) == before


def test_candidate_cannot_exceed_existing_shadow_hold(env):
    process(env)
    before = saved(env)
    with pytest.raises(Blocked, match="EXCEEDS_CASH_CAP_OR_SHADOW_HOLD"):
        run(env, fee=10001)
    assert saved(env) == before


def test_stale_market_evidence_cannot_create_candidate(env):
    process(env)
    before = saved(env)
    env["clock"][0] += timedelta(seconds=11)
    with pytest.raises(Blocked):
        run(env)
    assert saved(env) == before


def test_tampered_candidate_cannot_be_reused(env):
    process(env)
    run(env)
    out = saved(env)
    out["disabled_request_candidate"]["draft"]["body"]["quantity"] = 130
    with env["store"].db() as db:
        db.execute(
            "UPDATE preparation_outbox SET data=?", (json.dumps(out),),
        )
    before = saved(env)
    with pytest.raises(Blocked, match="IMMUTABLE_CANDIDATE_CONFLICT"):
        run(env)
    assert saved(env) == before
'''

for path, content in ((module, module_text), (tests, test_text)):
    if not path.parent.is_dir():
        raise SystemExit("STOP: parent directory missing: " + str(path.parent))
    if path.exists() or path.is_symlink():
        raise SystemExit("STOP: file already exists: " + str(path))
    compile(content, str(path), "exec")

for path, content in ((module, module_text), (tests, test_text)):
    with path.open("x") as stream:
        stream.write(content)
    print("Created:", path)

print("Syntax checked. Tests not executed. No activation performed.")