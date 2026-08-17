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
