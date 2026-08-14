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


class MixedTimezoneDatabase:
    def read_signal_attempts_range(
        self, instrument_key, date_from, date_to
    ):
        return [{
            "signal_id": "PIPE-TZ",
            "instrument_key": instrument_key,
            "direction": "BEARISH",
            "confirmation_timestamp": (
                "2026-08-13T14:50:00+05:30"
            ),
        }]

    def read_trade_selection_evaluations(self, **kwargs):
        signal_id = kwargs.get("signal_id")
        if signal_id and signal_id != "PIPE-TZ":
            return []
        return [{
            "signal_id": "PIPE-TZ",
            "direction": "BEARISH",
            "candidate_symbol": "NIFTY-PE",
            "evaluated_at": "2026-08-13T09:21:00Z",
            "candidate_rank": 1,
            "eligible": 1,
            "decision": "SELECTED",
        }]

    def read_opportunity_evaluations(self, **kwargs):
        return []
    def read_institutional_execution_evaluations(self, **kwargs):
        return []
    def read_execution_queue(self, **kwargs):
        return []
    def read_paper_execution_orders(self, account_id):
        return []


def bundle():
    return {
        "bundle_id": "B-TZ",
        "instrument_key": "NSE_INDEX|Nifty_50",
        "detected_at": "2026-08-13T09:15:00",
        "fresh_until": "2026-08-13T09:30:00",
        "direction": "BEARISH",
        "primary_setup_type": "BEARISH_STRUCTURE_BREAK",
        "primary_signal_id": "V43-TZ",
    }


def test_resolver_handles_mixed_timezone_inputs():
    result = TargetedHistoricalPipelineResolver(
        database=MixedTimezoneDatabase()
    ).resolve(
        bundle(),
        MixedTimezoneDatabase().read_signal_attempts_range(
            "NSE_INDEX|Nifty_50",
            "2026-08-13",
            "2026-08-13",
        ),
        instrument_key="NSE_INDEX|Nifty_50",
        selection_fallback_rows=(
            MixedTimezoneDatabase()
            .read_trade_selection_evaluations()
        ),
    )

    assert result["pipeline_signal_id"] == "PIPE-TZ"
    assert result["match_resolution"] == "PARTIAL_CHAIN_MATCH"
    assert result["selected_candidate_symbol"] == "NIFTY-PE"


def test_full_audit_handles_mixed_timezone_inputs(tmp_path: Path):
    folder = tmp_path / "fresh_setup_bundles_v43"
    folder.mkdir(parents=True)
    (folder / "nifty.jsonl").write_text(
        json.dumps(bundle()) + "\n",
        encoding="utf-8",
    )

    result = RangeHistoricalAttributionAudit(
        database=MixedTimezoneDatabase(),
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

    assert result["matches"][0]["pipeline_signal_id"] == "PIPE-TZ"
    assert result["summary"]["partial_chain_matches"] == 1
