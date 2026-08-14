from datetime import date, time
from pathlib import Path
import json

from red_bar_lab.services.historical_attribution_audit import (
    HistoricalAuditRequest,
    RangeHistoricalAttributionAudit,
)
from red_bar_lab.services.targeted_historical_pipeline_resolver import (
    TargetedHistoricalPipelineResolver,
)


class Database:
    def read_signal_attempts_range(self, instrument_key, date_from, date_to):
        return [
            {
                "signal_id": "PIPE-1",
                "instrument_key": instrument_key,
                "direction": "BEARISH",
                "confirmation_timestamp": "2026-08-13T09:20:00",
                "state": "CONFIRMED",
            }
        ]

    def read_trade_selection_evaluations(
        self, *, signal_id=None, trading_date=None, limit=200
    ):
        if signal_id == "PIPE-1":
            return [{
                "id": 10,
                "signal_id": "PIPE-1",
                "direction": "BEARISH",
                "candidate_symbol": "NIFTY-PE",
                "candidate_rank": 1,
                "selection_score": 88,
                "eligible": 1,
                "decision": "SELECTED",
                "evaluated_at": "2026-08-13T09:21:00",
            }]
        return []

    def read_opportunity_evaluations(
        self, *, limit=100, signal_id=None, entry_mode=None
    ):
        if signal_id == "PIPE-1":
            return [{
                "signal_id": "PIPE-1",
                "direction": "BEARISH",
                "candidate_symbol": "NIFTY-PE",
                "decision": "ELIGIBLE",
                "opportunity_score": 80,
                "evaluated_at": "2026-08-13T09:22:00",
            }]
        return []

    def read_institutional_execution_evaluations(
        self, *, signal_id=None, trading_date=None, limit=200
    ):
        if signal_id == "PIPE-1":
            return [{
                "signal_id": "PIPE-1",
                "direction": "BEARISH",
                "candidate_symbol": "NIFTY-PE",
                "decision": "APPROVED",
                "eligible": 1,
                "evaluated_at": "2026-08-13T09:23:00",
            }]
        return []

    def read_execution_queue(
        self, *, status=None, signal_id=None, trading_date=None, limit=200
    ):
        if signal_id == "PIPE-1":
            return [{
                "queue_id": "Q1",
                "signal_id": "PIPE-1",
                "direction": "BEARISH",
                "candidate_symbol": "NIFTY-PE",
                "status": "EXECUTED",
                "candidate_rank": 1,
                "created_at": "2026-08-13T09:24:00",
            }]
        return []

    def read_paper_execution_orders(self, account_id):
        return [{
            "order_id": "O1",
            "signal_id": "PIPE-1",
            "tradingsymbol": "NIFTY-PE",
            "option_type": "PE",
            "status": "CLOSED",
            "entry_timestamp": "2026-08-13T09:25:00",
            "exit_timestamp": "2026-08-13T10:00:00",
            "realized_pnl": 250.0,
        }]


def bundle():
    return {
        "bundle_id": "B1",
        "instrument_key": "NSE_INDEX|Nifty_50",
        "detected_at": "2026-08-13T09:15:00",
        "fresh_until": "2026-08-13T09:30:00",
        "direction": "BEARISH",
        "primary_setup_type": "BEARISH_STRUCTURE_BREAK",
        "primary_signal_id": "V43-1",
    }


def test_targeted_resolver_builds_strong_chain():
    result = TargetedHistoricalPipelineResolver(
        database=Database()
    ).resolve(
        bundle(),
        Database().read_signal_attempts_range(
            "NSE_INDEX|Nifty_50",
            "2026-08-13",
            "2026-08-13",
        ),
        instrument_key="NSE_INDEX|Nifty_50",
    )

    assert result["pipeline_signal_id"] == "PIPE-1"
    assert result["selected_candidate_symbol"] == "NIFTY-PE"
    assert result["opportunity_match_count"] == 1
    assert result["committee_match_count"] == 1
    assert result["queue_match_count"] == 1
    assert result["order_match_count"] == 1
    assert result["match_resolution"] == "STRONG_CHAIN_MATCH"
    assert result["realized_pnl"] == 250.0
    assert result["execution_allowed"] is False


def test_full_audit_uses_targeted_chain(tmp_path: Path):
    folder = tmp_path / "fresh_setup_bundles_v43"
    folder.mkdir(parents=True)
    (folder / "nifty.jsonl").write_text(
        json.dumps(bundle()) + "\n",
        encoding="utf-8",
    )

    result = RangeHistoricalAttributionAudit(
        database=Database(),
        runs_root=tmp_path,
    ).audit(
        HistoricalAuditRequest(
            instrument_key="NSE_INDEX|Nifty_50",
            date_from=date(2026, 8, 13),
            date_to=date(2026, 8, 13),
            start_time=time(9, 15),
            end_time=time(15, 30),
        )
    )

    assert result["summary"]["strong_chain_matches"] == 1
    assert result["matches"][0]["pipeline_signal_id"] == "PIPE-1"
    assert result["matches"][0]["order_id"] == "O1"


def test_pipeline_signal_cannot_be_reused():
    resolver = TargetedHistoricalPipelineResolver(database=Database())
    signals = Database().read_signal_attempts_range(
        "NSE_INDEX|Nifty_50",
        "2026-08-13",
        "2026-08-13",
    )
    used = set()
    first = resolver.resolve(
        bundle(),
        signals,
        instrument_key="NSE_INDEX|Nifty_50",
        used_signal_ids=used,
    )
    second_bundle = {
        **bundle(),
        "bundle_id": "B2",
        "primary_setup_type": "BEARISH_EMA_LOSS",
    }
    second = resolver.resolve(
        second_bundle,
        signals,
        instrument_key="NSE_INDEX|Nifty_50",
        used_signal_ids=used,
    )

    assert first["pipeline_signal_id"] == "PIPE-1"
    assert second["match_resolution"] == "NO_MATCH"
