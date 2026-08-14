from pathlib import Path

from red_bar_lab.services.signal_trade_attribution import (
    create_ledger_record,
    link_candidate,
    link_opportunity,
    link_committee_decision,
    link_trade_entry,
    close_trade,
)
from red_bar_lab.services.signal_trade_attribution_store import (
    SignalTradeAttributionStore,
)
from red_bar_lab.services.signal_trade_attribution_summary import (
    summarize_by_primary_setup,
    funnel_summary,
)
from red_bar_lab.services.signal_trade_pipeline_adapter import (
    apply_pipeline_event,
)


def bundle():
    return {
        "bundle_id": "BND-1",
        "regime_snapshot_id": "REG-1",
        "transition_id": "TR-1",
        "detected_at": "2026-08-13T10:00:00",
        "direction": "BULLISH",
        "primary_signal_id": "SIG-1",
        "primary_setup_type": "BULLISH_STRUCTURE_BREAK",
        "supporting_signal_ids": ["SIG-2", "SIG-3"],
        "supporting_setup_types": [
            "BULLISH_RANGE_BREAKOUT",
            "BULLISH_EMA_RECLAIM",
        ],
        "trigger_level": 24364.5,
        "invalidation_level": 24342.25,
        "fresh_until": "2026-08-13T10:15:00",
        "red_bar_alignment": "NOT_AVAILABLE",
    }


def test_full_attribution_lifecycle():
    record = create_ledger_record(bundle(), instrument_key="NIFTY")
    record = link_candidate(
        record,
        candidate_id="CAND-1",
        status="ACTIVE",
        created_at="2026-08-13T10:01:00",
    )
    record = link_opportunity(
        record,
        opportunity_id="OPP-1",
        status="READY",
        created_at="2026-08-13T10:02:00",
    )
    record = link_committee_decision(
        record,
        decision_id="COM-1",
        decision="APPROVED",
        reason=None,
        decided_at="2026-08-13T10:03:00",
    )
    record = link_trade_entry(
        record,
        trade_id="TRD-1",
        trade_mode="PAPER",
        option_side="CE",
        option_symbol="NIFTY-CE",
        entry_time="2026-08-13T10:04:00",
        entry_price=100.0,
    )
    record = close_trade(
        record,
        exit_time="2026-08-13T10:30:00",
        exit_price=120.0,
        realized_pnl=20.0,
        pnl_percentage=20.0,
        maximum_favorable_excursion=25.0,
        maximum_adverse_excursion=5.0,
        target_hit=True,
        stop_hit=False,
        exit_reason="TARGET",
    )
    assert record.outcome == "SUCCESS"
    assert record.primary_setup_type == "BULLISH_STRUCTURE_BREAK"
    assert record.execution_allowed is False


def test_store_upserts_same_ledger_id(tmp_path: Path):
    store = SignalTradeAttributionStore(tmp_path / "ledger.jsonl")
    record = create_ledger_record(bundle(), instrument_key="NIFTY")
    assert store.upsert(record.as_record()) is True
    assert store.upsert(record.as_record()) is False

    updated = link_candidate(
        record,
        candidate_id="CAND-1",
        status="ACTIVE",
        created_at="2026-08-13T10:01:00",
    )
    assert store.upsert(updated.as_record()) is True
    assert store.by_bundle("BND-1")["candidate_id"] == "CAND-1"


def test_summary_counts_success_by_primary_signal():
    first = create_ledger_record(bundle(), instrument_key="NIFTY")
    first = link_trade_entry(
        first,
        trade_id="TRD-1",
        trade_mode="PAPER",
        option_side="CE",
        option_symbol=None,
        entry_time="2026-08-13T10:04:00",
        entry_price=100.0,
    )
    first = close_trade(
        first,
        exit_time="2026-08-13T10:30:00",
        exit_price=110.0,
        realized_pnl=10.0,
        pnl_percentage=10.0,
        maximum_favorable_excursion=15.0,
        maximum_adverse_excursion=4.0,
        target_hit=True,
        stop_hit=False,
        exit_reason="TARGET",
    )
    rows = [first.as_record()]
    summary = summarize_by_primary_setup(rows)[0]
    assert summary["successful"] == 1
    assert summary["win_rate_pct"] == 100.0
    assert funnel_summary(rows)["entered_trades"] == 1


def test_normalized_pipeline_adapter():
    record = create_ledger_record(bundle(), instrument_key="NIFTY")
    updated = apply_pipeline_event(
        record,
        "CANDIDATE",
        {
            "candidate_id": "CAND-1",
            "status": "ACTIVE",
            "created_at": "2026-08-13T10:01:00",
        },
    )
    assert updated.candidate_id == "CAND-1"
