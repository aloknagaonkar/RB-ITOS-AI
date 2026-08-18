from __future__ import annotations

from red_bar_lab.execution.shadow_evaluation_journal import (
    append_evaluation_cycle,
    read_evaluation_cycles,
    summarize_evaluation_cycles,
)


def test_journal_persists_restart_safe_cycle_and_safety_flags(tmp_path):
    written = append_evaluation_cycle(
        tmp_path,
        {
            "strategy_id": "RED_BAR",
            "trading_date": "2026-08-18",
            "section_9_outcome": "SHADOW_HANDOFF_READY_DISABLED",
            "section_10d_outcome": "ROUTED_SHADOW_ONLY",
            "terminal_section": "9F",
            "terminal_reason": "LIVE_ACTIVATION_DISABLED",
        },
    )

    rows = read_evaluation_cycles(
        tmp_path,
        trading_date="2026-08-18",
    )

    assert len(rows) == 1
    assert rows[0]["evaluation_id"] == written["evaluation_id"]
    assert rows[0]["source_read_only"] is True
    assert rows[0]["capital_reserved"] is False
    assert rows[0]["bundle_consumed"] is False
    assert rows[0]["position_created"] is False
    assert rows[0]["order_created"] is False
    assert rows[0]["order_submitted"] is False


def test_journal_summary_counts_strategy_terminal_and_routes(tmp_path):
    append_evaluation_cycle(
        tmp_path,
        {
            "strategy_id": "RED_BAR",
            "trading_date": "2026-08-18",
            "section_9_outcome": "SHADOW_HANDOFF_READY_DISABLED",
            "section_10d_outcome": "ROUTED_SHADOW_ONLY",
            "terminal_section": "9F",
        },
    )
    append_evaluation_cycle(
        tmp_path,
        {
            "strategy_id": "RSI_EXTREME_REVERSAL",
            "trading_date": "2026-08-18",
            "section_9_outcome": "NOT_ELIGIBLE",
            "section_10d_outcome": "NO_SHADOW_EVIDENCE",
            "terminal_section": "4",
        },
    )

    summary = summarize_evaluation_cycles(
        read_evaluation_cycles(tmp_path, trading_date="2026-08-18")
    )

    assert summary["cycle_count"] == 2
    assert summary["healthy_candidate_count"] == 1
    assert summary["shadow_routed_count"] == 1
    assert summary["strategy_counts"] == {
        "RSI_EXTREME_REVERSAL": 1,
        "RED_BAR": 1,
    }
    assert summary["terminal_section_counts"] == {"4": 1, "9F": 1}
