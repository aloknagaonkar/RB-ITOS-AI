from copy import deepcopy

import pytest

from fixture_closeout_review import assess_closeout
from test_lifecycle_signal_review import (
    synthetic_scope, env, bound_env, module, prepared,
    lifecycle, linked,
)
from test_signed_lifecycle_review import values
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign


def fees_for(snapshot, at):
    value = dict(
        model="HILEGA_FIXTURE_FEE_EVIDENCE_V1",
        account_scope=PIN["scope"],
        snapshot_fingerprint=sha(snapshot),
        generated_at=at, complete=True,
        production_execution_enabled=False,
        # Explicit fictional amounts, not a broker fee estimate.
        lines=[dict(
            order_id=t["order_id"], trade_id=t["trade_id"], fee_paise=100,
        ) for t in snapshot["trades"]],
    )
    value["signature"] = sign(value, PIN)
    return value


@pytest.fixture
def closed(lifecycle):
    data, event, sequence = linked(lifecycle)
    e, mod, store = lifecycle[0]
    transport = mod.FixtureTransport(store)
    sell = next(o for o in transport.orders() if o["side"] == "SELL")
    transport.fill(sell["order_id"], sell["quantity"])
    data = values(lifecycle)
    return lifecycle, data, sequence, fees_for(data[1], data[3])


def resign(fees):
    fees.pop("signature", None)
    fees["signature"] = sign(fees, PIN)


def run(case, *, fees="default"):
    lifecycle, data, sequence, evidence = case
    source, snapshot, key, at = data
    return assess_closeout(
        source, snapshot, PIN, entry_id=key,
        journal=lifecycle[0][0]["path"], exit_sequences=[sequence],
        fee_evidence=evidence if fees == "default" else fees, as_of=at,
    )


def test_exact_gross_fees_and_net_without_release(closed):
    before = deepcopy(closed[1])
    result = run(closed)
    quantity = closed[1][1]["orders"][0]["filled"]
    assert result["fixture_gross_realized_pnl_paise"] == quantity * 100
    assert result["fixture_fees_paise"] == 200
    assert result["fixture_net_realized_pnl_paise"] == quantity * 100 - 200
    assert result["fixture_release_conditions_passed"] is True
    assert result["reservation_release_permission"] is False
    assert result["application_reservation_modified"] is False
    assert result["actual_broker_fees_verified"] is False
    assert closed[1] == before


def test_missing_fees_retains_hold(closed):
    result = run(closed, fees=None)
    assert result["status"] == "HOLD_RETAINED"
    assert result["fixture_net_realized_pnl_paise"] is None


def test_incomplete_trade_fee_coverage_blocks(closed):
    evidence = deepcopy(closed[3])
    evidence["lines"].pop()
    resign(evidence)
    with pytest.raises(ValueError, match="FEE_TRADE_COVERAGE_MISMATCH"):
        run(closed, fees=evidence)


def test_duplicate_fee_line_blocks(closed):
    evidence = deepcopy(closed[3])
    evidence["lines"].append(deepcopy(evidence["lines"][0]))
    resign(evidence)
    with pytest.raises(ValueError, match="DUPLICATE_FEE_LINE"):
        run(closed, fees=evidence)


@pytest.mark.parametrize("amount", [True, -1, "100"])
def test_invalid_fee_amount_blocks(closed, amount):
    evidence = deepcopy(closed[3])
    evidence["lines"][0]["fee_paise"] = amount
    resign(evidence)
    with pytest.raises(ValueError, match="NONNEGATIVE_INTEGER_FEE_REQUIRED"):
        run(closed, fees=evidence)


def test_fee_tampering_blocks(closed):
    evidence = deepcopy(closed[3])
    evidence["lines"][0]["fee_paise"] += 1
    with pytest.raises(ValueError, match="FEE_SIGNATURE_INVALID"):
        run(closed, fees=evidence)


def test_open_exit_retains_hold(lifecycle):
    data, event, sequence = linked(lifecycle)
    evidence = fees_for(data[1], data[3])
    result = run((lifecycle, data, sequence, evidence))
    assert result["status"] == "HOLD_RETAINED"
    assert "POSITION_NOT_FLAT" in result["reasons"]
    assert "WORKING_OR_UNRESOLVED_ORDER" in result["reasons"]
    assert result["fixture_net_realized_pnl_paise"] is None
