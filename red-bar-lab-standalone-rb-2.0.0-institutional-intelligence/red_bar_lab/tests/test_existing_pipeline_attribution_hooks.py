from pathlib import Path
from types import SimpleNamespace

from red_bar_lab.services.signal_trade_attribution import (
    create_ledger_record,
)
from red_bar_lab.services.signal_trade_attribution_store import (
    SignalTradeAttributionStore,
)
from red_bar_lab.services.attribution_pipeline_reconciler import (
    AttributionPipelineReconciler,
)


class FakeDatabase:
    def read_trade_selection_evaluations(self, limit=5000):
        return [{
            "scan_id": "SCAN-1",
            "signal_id": "LEGACY-SIG-1",
            "direction": "BULLISH",
            "candidate_rank": 1,
            "candidate_symbol": "NIFTY-CE",
            "instrument_token": 123,
            "decision": "PAPER BUY",
            "evaluated_at": "2026-08-13T10:01:00",
        }]

    def read_opportunity_evaluations(self, limit=5000):
        return [{
            "scan_id": "SCAN-1",
            "signal_id": "LEGACY-SIG-1",
            "direction": "BULLISH",
            "candidate_symbol": "NIFTY-CE",
            "decision": "BUY CE",
            "evaluated_at": "2026-08-13T10:02:00",
        }]

    def read_institutional_execution_evaluations(self, limit=5000):
        return [{
            "scan_id": "SCAN-1",
            "signal_id": "LEGACY-SIG-1",
            "direction": "BULLISH",
            "candidate_symbol": "NIFTY-CE",
            "decision": "APPROVED",
            "reason": "PASS",
            "evaluated_at": "2026-08-13T10:03:00",
        }]

    def read_execution_queue(self, limit=5000):
        return []

    def read_paper_execution_orders(self, account_id="PAPER-STD"):
        return [{
            "order_id": "ORDER-1",
            "signal_id": "LEGACY-SIG-1",
            "direction": "BULLISH",
            "instrument_token": 123,
            "tradingsymbol": "NIFTY-CE",
            "option_type": "CE",
            "entry_timestamp": "2026-08-13T10:04:00",
            "entry_price": 100.0,
            "exit_timestamp": "2026-08-13T10:25:00",
            "exit_price": 115.0,
            "quantity": 75,
            "status": "CLOSED",
            "realized_pnl": 1125.0,
            "pnl_percentage": 15.0,
            "mfe_points": 20.0,
            "mae_points": 4.0,
            "exit_reason": "EMA10_EXIT",
        }]


def test_reconciler_links_full_existing_pipeline(tmp_path: Path):
    runs = tmp_path / "runs"
    ledger_path = (
        runs / "signal_trade_attribution_v43" / "NIFTY.jsonl"
    )
    store = SignalTradeAttributionStore(ledger_path)
    bundle = {
        "bundle_id": "BND-1",
        "regime_snapshot_id": "REG-1",
        "transition_id": "TR-1",
        "detected_at": "2026-08-13T10:00:00",
        "direction": "BULLISH",
        "primary_signal_id": "SIG-1",
        "primary_setup_type": "BULLISH_STRUCTURE_BREAK",
        "supporting_signal_ids": [],
        "supporting_setup_types": [],
        "trigger_level": 24364.5,
        "invalidation_level": 24342.25,
        "fresh_until": "2026-08-13T10:15:00",
        "red_bar_alignment": "NOT_AVAILABLE",
    }
    record = create_ledger_record(
        bundle,
        instrument_key="NSE_INDEX|Nifty 50",
    )
    store.upsert(record.as_record())

    stats = AttributionPipelineReconciler(
        database=FakeDatabase(),
        runs_root=runs,
    ).reconcile()

    updated = store.by_bundle("BND-1")
    assert stats["candidate_links"] == 1
    assert stats["opportunity_links"] == 1
    assert stats["committee_links"] == 1
    assert stats["trade_entry_links"] == 1
    assert stats["trade_exit_links"] == 1
    assert updated["candidate_id"].startswith("CAND-")
    assert updated["committee_decision"] == "APPROVED"
    assert updated["trade_id"] == "ORDER-1"
    assert updated["outcome"] == "SUCCESS"
    assert updated["primary_setup_type"] == "BULLISH_STRUCTURE_BREAK"
    assert updated["execution_allowed"] is False


def test_workspace_installs_attribution_aware_runtime():
    workspace = Path("red_bar_lab/ui/workspace.py").read_text(
        encoding="utf-8"
    )
    assert "AttributionAwarePaperAutomationService" in workspace
    assert (
        "paper_trading.RedBarPaperAutomationService = "
        "AttributionAwarePaperAutomationService"
    ) in workspace
