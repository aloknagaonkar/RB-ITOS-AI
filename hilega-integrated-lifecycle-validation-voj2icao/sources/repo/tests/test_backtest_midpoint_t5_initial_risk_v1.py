from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path("scripts/backtest_midpoint_t5_initial_risk_v1.py")
if not SCRIPT.exists():
    SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / SCRIPT.name
SPEC = importlib.util.spec_from_file_location("t5_policy_tested", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def trade(**changes):
    row = {
        "split": "IS_FROZEN_FIRST_70", "segment": "MORNING",
        "session_date": "2026-09-30", "family": "E",
        "direction": "BEARISH", "entry_timestamp": "2026-09-30T09:26:00+05:30",
        "selected_exit_timestamp": "2026-09-30T10:00:00+05:30",
        "selected_exit_points": "-30", "plus20_timestamp": "",
        "t5_available": "True", "t5_close_progress": "-5",
        "t5_directional_di_spread": "-2", "t5_combined_edge": "-10",
        "t5_price_momentum_support": "0", "t5_directional_vwap_change": "-3",
        "cohort": "BAD_UNPROVED_STRUCTURAL_LOSS",
    }
    row.update(changes)
    return row


def test_plus20_on_exact_t5_bypasses_candidate():
    row = trade(plus20_timestamp="2026-09-30T09:31:00+05:30")
    assert MODULE.t5_eligible(row) is False
    assert MODULE.policy_trigger("T5_DI_FAILURE_ZERO", row) is False


def test_plus20_after_t5_remains_eligible_and_counts_winner_damage():
    row = trade(
        plus20_timestamp="2026-09-30T09:32:00+05:30",
        cohort="GOOD_PLUS20_PROVED", selected_exit_points="20",
    )
    assert MODULE.t5_eligible(row) is True
    result = MODULE.impact([row], "T5_DI_FAILURE_ZERO")
    assert result["later_plus20_winners_stopped"] == 1
    assert result["later_plus20_winner_delta_points"] == -25


def test_structural_terminal_before_t5_is_not_eligible():
    row = trade(selected_exit_timestamp="2026-09-30T09:30:00+05:30")
    assert MODULE.t5_eligible(row) is False


def test_candidate_uses_observed_t5_close_not_theoretical_threshold():
    row = trade(t5_close_progress="-7.25")
    assert MODULE.policy_points("T5_DI_FAILURE_ZERO", row) == -7.25


def test_two_of_three_requires_two_observed_failures():
    row = trade(
        t5_directional_di_spread="-1", t5_combined_edge="5",
        t5_price_momentum_support="0",
    )
    assert MODULE.policy_trigger("T5_TWO_OF_THREE_FAILURE", row) is True
    row["t5_price_momentum_support"] = "1"
    assert MODULE.policy_trigger("T5_TWO_OF_THREE_FAILURE", row) is False


def test_combination_requires_all_named_evidence():
    row = trade(t5_directional_vwap_change="1")
    assert MODULE.policy_trigger("T5_DI_AND_EDGE_FAILURE_ZERO", row) is True
    assert MODULE.policy_trigger("T5_DI_EDGE_VWAP_FAILURE_ZERO", row) is False


def test_bad_trade_recovery_and_harm_are_explicit():
    improved = trade(selected_exit_points="-30", t5_close_progress="-5")
    harmed = trade(
        entry_timestamp="2026-09-30T10:00:00+05:30",
        selected_exit_timestamp="2026-09-30T11:00:00+05:30",
        selected_exit_points="-2", t5_close_progress="-5",
    )
    result = MODULE.impact([improved, harmed], "T5_DI_FAILURE_ZERO")
    assert result["bad_structural_improved"] == 1
    assert result["bad_structural_harmed"] == 1
    assert result["bad_structural_recovery_points"] == 22


def test_max_drawdown_uses_chronological_session_returns():
    assert MODULE.max_drawdown([10, -4, -8, 3, -2]) == 12


def test_safety_flags_are_hard_coded():
    source = SCRIPT.read_text()
    assert '"execution_enabled": False' in source
    assert '"paper_order_enabled": False' in source
    assert '"quantity": None' in source
    assert '"order_sent": False' in source

