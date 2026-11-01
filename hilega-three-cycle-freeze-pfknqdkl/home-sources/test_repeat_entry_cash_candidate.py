from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from repeat_entry_cash_candidate import review_repeat_entry
from test_closed_history_baseline_candidate import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle, closed, history,
)
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign


def resign(value):
    value.pop("signature", None)
    value["signature"] = sign(value, PIN)


@pytest.fixture
def reentry(history):
    source, archived, account, at = history
    cash = deepcopy(account)
    cash.pop("signature")
    cash.update(
        model="HILEGA_READ_ONLY_CASH_OBSERVATION_V1",
        evidence_mode="LIVE_READ_ONLY_ACCOUNT_PINNED",
        snapshot_id="fresh-repeat-entry-cash",
        started_at=account["generated_at"],
        capture_atomic=False, debit_attribution="NOT_VALIDATED",
        funds_changed_during_capture=False,
        diagnostics=dict(issues=["BROKER_ORDERS_NOT_MAPPED_TO_STRATEGY"]),
    )
    funds = dict(
        field="data.available_to_trade.cash_available_to_trade.total",
        cash_available_to_trade="20000.00",
        cash_margin_used="0",
    )
    cash["funds_before"] = deepcopy(funds)
    cash["funds_after"] = deepcopy(funds)
    resign(cash)
    return account, cash, archived, at


def run(case, **changes):
    account, cash, archived, at = case
    options = dict(
        signal_at=account["generated_at"],
        premium_paise=990000, fee_buffer_paise=10000, as_of=at,
    )
    options.update(changes)
    return review_repeat_entry(
        account, cash, [archived], PIN, **options)


def test_exact_half_of_fresh_cash_with_closed_history(reentry):
    before = deepcopy(reentry)
    result = run(reentry)
    assert result["status"] == "REENTRY_REFERENCE_CHECKS_PASS"
    assert result["verified_available_cash_paise"] == 2000000
    assert result["half_cash_budget_paise"] == 1000000
    assert result["proposed_budget_paise"] == 1000000
    assert result["entry_permission"] is False
    assert result["historical_cash_used_as_current_capacity"] is False
    assert reentry == before


def test_smaller_current_cash_does_not_use_old_capacity(reentry):
    for key in ("funds_before", "funds_after"):
        reentry[1][key]["cash_available_to_trade"] = "10000.00"
    resign(reentry[1])
    result = run(reentry)
    assert result["status"] == "BLOCKED"
    assert result["half_cash_budget_paise"] == 500000
    assert "HALF_CASH_CAP_EXCEEDED" in result["reasons"]


def test_zero_cash_blocks(reentry):
    for key in ("funds_before", "funds_after"):
        reentry[1][key]["cash_available_to_trade"] = "0"
    resign(reentry[1])
    assert "NO_CASH_CAPACITY" in run(reentry)["reasons"]


def test_funds_drift_remains_blocked(reentry):
    reentry[1]["funds_after"]["cash_available_to_trade"] = "19000"
    reentry[1]["funds_changed_during_capture"] = True
    resign(reentry[1])
    assert "FUNDS_CHANGED_DURING_CAPTURE" in run(reentry)["reasons"]


def test_forged_cash_signature_blocks(reentry):
    reentry[1]["signature"] = "0"*64
    with pytest.raises(ValueError):
        run(reentry)


def test_cash_and_account_rows_must_match(reentry):
    reentry[1]["trades"][0]["price"] = "999"
    resign(reentry[1])
    with pytest.raises(ValueError, match="CAPTURE_ROWS_DIFFER"):
        run(reentry)


def test_unresolved_diagnostic_cannot_be_discarded(reentry):
    reentry[1]["diagnostics"]["issues"].append("ORDER_TRADE_FILL_TOTAL_MISMATCH")
    resign(reentry[1])
    with pytest.raises(ValueError, match="UNRESOLVED_CASH_DIAGNOSTICS"):
        run(reentry)


def test_old_signal_cannot_reuse_closed_history(reentry):
    old = reentry[2]["source"]["plans"][reentry[2]["entry_id"]]["signal_at"]
    with pytest.raises(ValueError, match="SIGNAL_NOT_AFTER"):
        run(reentry, signal_at=old)


def test_stale_captures_block(reentry):
    later = datetime.fromisoformat(reentry[3]) + timedelta(seconds=31)
    with pytest.raises(ValueError):
        run(reentry, as_of=later.isoformat())


@pytest.mark.parametrize("changes", [
    dict(premium_paise=True),
    dict(fee_buffer_paise=-1),
])
def test_invalid_budget_components_block(reentry, changes):
    with pytest.raises(ValueError, match="POSITIVE_INTEGER"):
        run(reentry, **changes)


def test_wrong_cash_field_blocks(reentry):
    for key in ("funds_before", "funds_after"):
        reentry[1][key]["field"] = "gross_balance"
    resign(reentry[1])
    with pytest.raises(ValueError, match="NET_CASH_FIELD_REQUIRED"):
        run(reentry)
