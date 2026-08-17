from dataclasses import dataclass

from red_bar_lab.execution.rsi_approval_policy import (
    apply_rsi_approval_policy,
    apply_rsi_entry_limit,
)


@dataclass(frozen=True)
class Contract:
    instrument_token: int = 123
    lot_size: int = 75
    tradingsymbol: str = "NIFTY26AUG25000CE"


@dataclass(frozen=True)
class Candidate:
    contract: Contract = Contract()
    ltp: float = 100.0
    best_bid: float = 99.5
    best_ask: float = 100.0
    liquidity_score: float = 10.0
    total_score: float = 20.0


@dataclass(frozen=True)
class Committee:
    eligible: bool = False
    decision: str = "REJECT"
    reason: str = "LOW_COMPOSITE_SCORE"
    primary_decision: str = "REJECT"
    primary_confidence_pct: float = 10.0


def test_rsi_observational_committee_cannot_veto_valid_contract():
    result = apply_rsi_approval_policy(
        Committee(),
        candidate=Candidate(total_score=1.0),
        strategy_source="RSI_EXTREME_REVERSAL_V1",
        duplicate=False,
    )
    assert result.eligible is True
    assert result.decision == "EXECUTE"
    assert "OBSERVATIONAL_COMMITTEE_BYPASSED" in result.reason


def test_rsi_spread_remains_authoritative_hard_gate():
    result = apply_rsi_approval_policy(
        Committee(eligible=True, decision="EXECUTE"),
        candidate=Candidate(
            ltp=100.0,
            best_bid=95.0,
            best_ask=101.0,
        ),
        strategy_source="RSI_EXTREME_REVERSAL_V1",
        duplicate=False,
    )
    assert result.eligible is False
    assert "SPREAD_TOO_WIDE" in result.reason


def test_rsi_liquidity_remains_authoritative_hard_gate():
    result = apply_rsi_approval_policy(
        Committee(),
        candidate=Candidate(liquidity_score=5.0),
        strategy_source="RSI_EXTREME_REVERSAL_V1",
        duplicate=False,
    )
    assert result.eligible is False
    assert "INSUFFICIENT_LIQUIDITY" in result.reason


def test_duplicate_remains_authoritative_hard_gate():
    result = apply_rsi_approval_policy(
        Committee(),
        candidate=Candidate(),
        strategy_source="RSI_EXTREME_REVERSAL_V1",
        duplicate=True,
    )
    assert result.eligible is False
    assert "DUPLICATE_CANDIDATE" in result.reason


def test_non_rsi_committee_result_is_unchanged():
    original = Committee(
        eligible=False,
        decision="WAIT",
        reason="STANDARD_POLICY",
    )
    result = apply_rsi_approval_policy(
        original,
        candidate=Candidate(),
        strategy_source="REFERENCE_LEVEL",
        duplicate=False,
    )
    assert result is original


def test_rsi_entry_limit_accepts_first_two_eligible_contracts():
    committee = Committee(eligible=True, decision="EXECUTE")
    first = apply_rsi_entry_limit(
        committee,
        strategy_source="RSI_EXTREME_REVERSAL_V1",
        selected_entries=0,
    )
    second = apply_rsi_entry_limit(
        committee,
        strategy_source="RSI_EXTREME_REVERSAL_V1",
        selected_entries=1,
    )
    assert first.eligible is True
    assert second.eligible is True


def test_rsi_entry_limit_rejects_third_eligible_contract():
    result = apply_rsi_entry_limit(
        Committee(eligible=True, decision="EXECUTE"),
        strategy_source="RSI_EXTREME_REVERSAL_V1",
        selected_entries=2,
    )
    assert result.eligible is False
    assert result.decision == "REJECT"
    assert "RSI_ENTRY_LIMIT_REACHED:2" in result.reason


def test_rsi_entry_limit_does_not_change_hard_gate_rejection():
    original = Committee(
        eligible=False,
        decision="REJECT",
        reason="RSI_HARD_GATE_FAIL",
    )
    result = apply_rsi_entry_limit(
        original,
        strategy_source="RSI_EXTREME_REVERSAL_V1",
        selected_entries=2,
    )
    assert result is original


def test_zero_fill_terminal_orders_do_not_consume_rsi_slot():
    from red_bar_lab.execution.rsi_approval_policy import (
        rsi_order_consumes_entry_slot,
    )
    for status in ("REJECTED", "FAILED", "CANCELLED", "EXPIRED"):
        assert rsi_order_consumes_entry_slot({
            "status": status,
            "filled_quantity": 0,
        }) is False


def test_filled_terminal_order_still_consumes_rsi_slot():
    from red_bar_lab.execution.rsi_approval_policy import (
        rsi_order_consumes_entry_slot,
    )
    assert rsi_order_consumes_entry_slot({
        "status": "CANCELLED",
        "filled_quantity": 25,
    }) is True
    assert rsi_order_consumes_entry_slot({
        "status": "CLOSED",
        "filled_quantity": 50,
    }) is True


def test_active_and_legacy_unknown_orders_consume_rsi_slot():
    from red_bar_lab.execution.rsi_approval_policy import (
        rsi_order_consumes_entry_slot,
    )
    assert rsi_order_consumes_entry_slot({
        "status": "OPEN",
        "filled_quantity": 0,
    }) is True
    assert rsi_order_consumes_entry_slot({}) is True


def test_restart_count_uses_only_same_signal_rsi_slot_consumers():
    from red_bar_lab.execution.rsi_approval_policy import (
        count_slot_consuming_rsi_orders,
    )
    orders = [
        {
            "signal_id": "RSI-1",
            "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
            "status": "FILLED",
            "filled_quantity": 50,
        },
        {
            "signal_id": "RSI-1",
            "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
            "status": "REJECTED",
            "filled_quantity": 0,
        },
        {
            "signal_id": "RSI-1",
            "execution_strategy_source": "RED_BAR",
            "status": "FILLED",
            "filled_quantity": 50,
        },
        {
            "signal_id": "RSI-2",
            "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
            "status": "FILLED",
            "filled_quantity": 50,
        },
    ]
    assert count_slot_consuming_rsi_orders(
        orders,
        signal_id="RSI-1",
    ) == 1


def test_two_persisted_slot_consumers_reject_next_eligible_entry():
    from red_bar_lab.execution.rsi_approval_policy import (
        count_slot_consuming_rsi_orders,
    )
    orders = [
        {
            "signal_id": "RSI-1",
            "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
            "status": "OPEN",
        },
        {
            "signal_id": "RSI-1",
            "execution_strategy_source": "RSI_EXTREME_REVERSAL_V1",
            "status": "CLOSED",
            "filled_quantity": 50,
        },
    ]
    selected = count_slot_consuming_rsi_orders(
        orders,
        signal_id="RSI-1",
    )
    result = apply_rsi_entry_limit(
        Committee(eligible=True, decision="EXECUTE"),
        strategy_source="RSI_EXTREME_REVERSAL_V1",
        selected_entries=selected,
    )
    assert selected == 2
    assert result.eligible is False
    assert "RSI_ENTRY_LIMIT_REACHED:2" in result.reason


def test_rsi_allocation_mode_is_full_quantity_per_entry():
    from red_bar_lab.execution.rsi_approval_policy import (
        RSI_ENTRY_ALLOCATION_MODE,
    )
    assert RSI_ENTRY_ALLOCATION_MODE == "FULL_QUANTITY_PER_ENTRY"

