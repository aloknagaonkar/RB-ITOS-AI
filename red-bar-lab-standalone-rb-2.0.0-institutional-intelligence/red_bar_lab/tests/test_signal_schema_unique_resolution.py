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


class MultiRowDatabase:
    def read_signal_attempts_range(
        self, instrument_key, date_from, date_to
    ):
        return [{
            "signal_id": "PIPE-SIGNAL",
            "instrument_key": instrument_key,
            "direction": "BEARISH",
            # created_at is deliberately outside session; the resolver must
            # discover and prefer the actual market timestamp.
            "created_at": "2026-08-13T18:00:00",
            "market_event_time": "2026-08-13T09:20:00",
        }]

    def read_trade_selection_evaluations(self, **kwargs):
        signal_id = kwargs.get("signal_id")
        rows = [
            {
                "id": 1,
                "signal_id": "PIPE-SIGNAL",
                "direction": "BEARISH",
                "candidate_symbol": "NIFTY-PE-1",
                "candidate_rank": 2,
                "selection_score": 60,
                "evaluated_at": "2026-08-13T09:20:00",
            },
            {
                "id": 2,
                "signal_id": "PIPE-SIGNAL",
                "direction": "BEARISH",
                "candidate_symbol": "NIFTY-PE-2",
                "candidate_rank": 1,
                "selection_score": 90,
                "eligible": 1,
                "decision": "SELECTED",
                "evaluated_at": "2026-08-13T09:20:00",
            },
        ]
        if signal_id and signal_id != "PIPE-SIGNAL":
            return []
        return rows

    def read_opportunity_evaluations(self, **kwargs):
        return []
    def read_institutional_execution_evaluations(self, **kwargs):
        return []
    def read_execution_queue(self, **kwargs):
        return []
    def read_paper_execution_orders(self, account_id):
        return []


def bundle(bundle_id="B1", setup="BEARISH_STRUCTURE_BREAK"):
    return {
        "bundle_id": bundle_id,
        "instrument_key": "NSE_INDEX|Nifty_50",
        "detected_at": "2026-08-13T09:15:00",
        "fresh_until": "2026-08-13T09:30:00",
        "direction": "BEARISH",
        "primary_setup_type": setup,
        "primary_signal_id": "V43-1",
    }


def test_dynamic_timestamp_discovery_prefers_market_time():
    resolver = TargetedHistoricalPipelineResolver(
        database=MultiRowDatabase()
    )
    result = resolver.resolve(
        bundle(),
        MultiRowDatabase().read_signal_attempts_range(
            "NSE_INDEX|Nifty_50",
            "2026-08-13",
            "2026-08-13",
        ),
        instrument_key="NSE_INDEX|Nifty_50",
    )
    assert result["pipeline_signal_id"] == "PIPE-SIGNAL"
    assert result["pipeline_signal_time_field"] == "market_event_time"
    assert result["selected_candidate_symbol"] == "NIFTY-PE-2"


def test_multiple_selection_rows_same_signal_are_not_ambiguous():
    resolver = TargetedHistoricalPipelineResolver(
        database=MultiRowDatabase()
    )
    result = resolver.resolve(
        bundle(),
        [],
        instrument_key="NSE_INDEX|Nifty_50",
        selection_fallback_rows=(
            MultiRowDatabase().read_trade_selection_evaluations()
        ),
    )
    assert result["pipeline_signal_id"] == "PIPE-SIGNAL"
    assert result["match_resolution"] == "PARTIAL_CHAIN_MATCH"
    assert result["pipeline_signal_candidates"] == 1
    assert result["candidate_matches_found"] == 2


def test_signal_id_remains_one_to_one():
    resolver = TargetedHistoricalPipelineResolver(
        database=MultiRowDatabase()
    )
    rows = MultiRowDatabase().read_trade_selection_evaluations()
    used = set()
    first = resolver.resolve(
        bundle(),
        [],
        instrument_key="NSE_INDEX|Nifty_50",
        selection_fallback_rows=rows,
        used_signal_ids=used,
    )
    second = resolver.resolve(
        bundle("B2", "BEARISH_EMA_LOSS"),
        [],
        instrument_key="NSE_INDEX|Nifty_50",
        selection_fallback_rows=rows,
        used_signal_ids=used,
    )
    assert first["pipeline_signal_id"] == "PIPE-SIGNAL"
    assert second["match_resolution"] == "NO_MATCH"


def test_audit_exposes_schema_diagnostics(tmp_path: Path):
    folder = tmp_path / "fresh_setup_bundles_v43"
    folder.mkdir(parents=True)
    (folder / "nifty.jsonl").write_text(
        json.dumps(bundle()) + "\n",
        encoding="utf-8",
    )
    result = RangeHistoricalAttributionAudit(
        database=MultiRowDatabase(),
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
    signals = next(
        row for row in result["sources"]
        if row["source"] == "signals"
    )
    assert signals["session_filtered"] == 1
    assert "market_event_time" in signals[
        "timestamp_fields_detected"
    ]
    assert result["matches"][0]["pipeline_signal_id"] == (
        "PIPE-SIGNAL"
    )
