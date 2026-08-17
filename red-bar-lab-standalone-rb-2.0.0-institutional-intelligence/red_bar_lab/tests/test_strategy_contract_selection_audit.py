from __future__ import annotations

from red_bar_lab.ui.strategy_contract_ranking import POLICIES
from red_bar_lab.ui.strategy_contract_selection_audit import build_selection_audit


def _selected_row(key: str, rank: int, score: float):
    return {
        "rank": rank,
        "ranking_decision": "PRIMARY" if rank == 1 else "FALLBACK",
        "instrument_key": key,
        "trading_symbol": key,
        "option_side": "PE",
        "expiry": "2026-08-20",
        "strike": 25000 + rank * 50,
        "ltp": 100.0 + rank,
        "spread_pct": 1.0,
        "volume": 1000.0,
        "oi": 5000.0,
        "delta": -0.5,
        "iv": 15.0,
        "spread_quality": 90.0,
        "volume_quality": 100.0,
        "oi_quality": 100.0,
        "delta_quality": 100.0,
        "iv_evidence": 100.0,
        "score": score,
    }


def _ranking(selected_rows):
    return {
        "outcome": "SELECTED" if len(selected_rows) == 2 else "PARTIAL",
        "reason": "test",
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "policy_version": "RSI-CONTRACT-RANK-V1",
        "bundle_id": "BUNDLE-1",
        "signal_id": "SIGNAL-1",
        "requested_side": "PE",
        "snapshot_timestamp": "2026-08-17T10:00:00+05:30",
        "ranked_rows": list(selected_rows),
        "selected_rows": list(selected_rows),
    }


def test_rsi_audit_builds_primary_and_fallback_handoff_records():
    policy = POLICIES["RSI_EXTREME_REVERSAL"]
    result = build_selection_audit(
        _ranking([_selected_row("OPT-1", 1, 95.0), _selected_row("OPT-2", 2, 90.0)]),
        policy=policy,
    )

    assert result["outcome"] == "HANDOFF_READY_READ_ONLY"
    assert result["selected_count"] == 2
    assert [row["role"] for row in result["handoff_rows"]] == ["PRIMARY", "FALLBACK"]
    assert {row["instrument_key"] for row in result["handoff_rows"]} == {"OPT-1", "OPT-2"}
    assert all(row["handoff_state"] == "PROPOSED_READ_ONLY" for row in result["handoff_rows"])
    assert all(row["persisted"] is False for row in result["handoff_rows"])
    assert all(row["bundle_consumed"] is False for row in result["handoff_rows"])


def test_audit_exposes_weighted_score_contributions():
    policy = POLICIES["RSI_EXTREME_REVERSAL"]
    result = build_selection_audit(_ranking([_selected_row("OPT-1", 1, 95.0)]), policy=policy)
    row = result["audit_rows"][0]

    assert row["spread_quality_contribution"] == 31.5
    assert row["volume_quality_contribution"] == 25.0
    assert row["oi_quality_contribution"] == 25.0
    assert row["delta_quality_contribution"] == 10.0
    assert row["iv_evidence_contribution"] == 5.0


def test_no_selected_contract_produces_no_handoff():
    policy = POLICIES["RED_BAR"]
    ranking = {
        "outcome": "NOT_ELIGIBLE",
        "reason": "Section 4 blocked the bundle.",
        "bundle_id": "BUNDLE-1",
        "signal_id": "SIGNAL-1",
        "requested_side": "CE",
        "snapshot_timestamp": "Unavailable",
        "ranked_rows": [],
        "selected_rows": [],
    }
    result = build_selection_audit(ranking, policy=policy)

    assert result["outcome"] == "NO_HANDOFF"
    assert result["selected_count"] == 0
    assert result["handoff_rows"] == []
    assert result["persisted"] is False
    assert result["executed"] is False


def test_audit_module_contains_no_write_or_execution_action():
    import red_bar_lab.ui.strategy_contract_selection_audit as audit_module

    source = open(audit_module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "create_candidate" not in source
    assert "mark_bundle_consumed" not in source
    assert "reserve_contract" not in source
    assert "update_position" not in source
