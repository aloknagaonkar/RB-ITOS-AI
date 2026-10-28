import json
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
