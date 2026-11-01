from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import Mock, patch

import pytest

from fixture_repeat_execution_candidate import execute_repeat_fixture
from test_repeat_entry_preparation_candidate import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle,
    closed, history, reentry, second, run as prepare_second,
)
from hilega_application_preparation_fixtures import PIN


def build_case(second, module, *, bearish=False):
    result = prepare_second(second, bearish=bearish)
    return dict(
        setup=second, mod=module, key=result["request_id"],
        captures=dict(
            account=deepcopy(second["account"]),
            cash=deepcopy(second["cash"]),
            market=deepcopy(second["market"])))


@pytest.fixture
def ready(second, module):
    return build_case(second, module)


def run(case, *, provider=None, clock=None, **kwargs):
    setup = case["setup"]
    return execute_repeat_fixture(
        setup["e"]["store"], setup["execution"], PIN,
        adapter_module=case["mod"], request_id=case["key"],
        capture_provider=provider or (lambda: deepcopy(case["captures"])),
        clock=clock or (lambda: setup["now"]), **kwargs)


def counts(case):
    with case["setup"]["execution"].tx() as db:
        claims = db.execute(
            "SELECT COUNT(*) FROM fixture_authorization_claims "
            "WHERE request_id=?", (case["key"],)).fetchone()[0]
        attempts = db.execute(
            "SELECT COUNT(*) FROM attempts WHERE request_id=?",
            (case["key"],)).fetchone()[0]
    return claims, attempts


@pytest.mark.parametrize("bearish", [False, True])
def test_second_buy_submits_once_with_history_preserved(
    second, module, bearish,
):
    case = build_case(second, module, bearish=bearish)
    result = run(case)
    assert result["status"] == "REPEAT_ENTRY_ATTEMPT_RECORDED"
    assert counts(case) == (1, 1)
    saved = second["execution"].requests()
    for previous in second["old_requests"]:
        assert previous in saved
    current = next(r for r in saved if r["request_id"] == case["key"])
    assert current["state"] == "ACKNOWLEDGED_NOT_FILLED"
    orders = module.FixtureTransport(second["execution"]).orders()
    assert len(orders) == 3
    assert result["production_execution_enabled"] is False



def test_delayed_recovery_needs_no_new_capture_or_send(ready):
    run(ready)
    provider = Mock(side_effect=AssertionError("No recovery capture"))
    with patch.object(
        ready["mod"].FixtureTransport, "send",
        side_effect=AssertionError("No repeated BUY"),
    ):
        result = run(
            ready, provider=provider,
            clock=lambda: ready["setup"]["now"]+timedelta(hours=2))
    assert result["recovery_only"] is True
    assert counts(ready) == (1, 1)
    provider.assert_not_called()


def test_expired_authorization_creates_no_attempt(ready):
    now = ready["setup"]["now"]
    times = iter([now, now+timedelta(seconds=10)])
    with pytest.raises(ValueError, match="EXPIRED"):
        run(ready, clock=lambda: next(times))
    assert counts(ready) == (0, 0)


def test_failure_after_claim_rolls_back_both(ready):
    def interrupt(stage):
        raise RuntimeError("SYNTHETIC_REPEAT_CLAIM_INTERRUPTION")
    with pytest.raises(RuntimeError, match="REPEAT_CLAIM_INTERRUPTION"):
        run(ready, checkpoint=interrupt)
    assert counts(ready) == (0, 0)
    orders = ready["mod"].FixtureTransport(
        ready["setup"]["execution"]).orders()
    assert len(orders) == 2


def test_new_cash_shortfall_blocks_second_buy(ready):
    from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign
    captures = deepcopy(ready["captures"])
    cash = captures["cash"]
    for field in ("funds_before", "funds_after"):
        cash[field]["cash_available_to_trade"] = "1"
    cash.pop("signature")
    cash["signature"] = sign(cash, PIN)
    with pytest.raises(ValueError, match="CURRENT_REPEAT_CASH_BLOCKED"):
        run(ready, provider=lambda: captures)
    assert counts(ready) == (0, 0)


def test_unknown_second_buy_never_resubmits(ready):
    result = run(ready, timeout_after=True)
    assert result["adapter_result"]["state"] == "UNKNOWN"
    provider = Mock(side_effect=AssertionError("No new capture for recovery"))
    with patch.object(
        ready["mod"].FixtureTransport, "send",
        side_effect=AssertionError("No unknown-outcome retry"),
    ):
        recovered = run(
            ready, provider=provider,
            clock=lambda: ready["setup"]["now"]+timedelta(hours=2))
    assert recovered["recovery_only"] is True
    assert counts(ready) == (1, 1)
    provider.assert_not_called()
    rows = ready["setup"]["execution"].requests()
    current = next(r for r in rows if r["request_id"] == ready["key"])
    assert current["state"] == "UNKNOWN"
    with ready["setup"]["e"]["store"].db() as db:
        held = db.execute(
            "SELECT data FROM preparation_cash_reservations WHERE id=?",
            (ready["key"],)).fetchone()
        assert held is not None
        assert json.loads(held[0])["held_cents"] > 0


def test_tampered_preparation_proof_blocks(ready):
    from repeat_entry_preparation_candidate import TABLE
    with ready["setup"]["e"]["store"].db() as db:
        row = json.loads(db.execute(
            "SELECT data FROM "+TABLE+" WHERE id=?",
            (ready["key"],)).fetchone()[0])
        row["production_execution_enabled"] = True
        db.execute("UPDATE "+TABLE+" SET data=? WHERE id=?",
                   (json.dumps(row), ready["key"]))
    with pytest.raises(ValueError, match="REPEAT_PREPARATION_SIGNATURE_INVALID"):
        run(ready)
    assert counts(ready) == (0, 0)

