from datetime import date, time
from pathlib import Path
import json

from red_bar_lab.services.historical_attribution_audit import (
    HistoricalAuditRequest,
    RangeHistoricalAttributionAudit,
)


class FakeDatabase:
    def read_signal_attempts_range(self, instrument_key, date_from, date_to):
        return [{
            "signal_id": "PIPE-1",
            "instrument_key": instrument_key,
            "direction": "BULLISH",
            "confirmation_timestamp": "2026-08-13T10:00:00",
        }]

    def read_trade_selection_evaluations(
        self, *, trading_date=None, limit=5000
    ):
        return [{
            "signal_id": "PIPE-1",
            "direction": "BULLISH",
            "candidate_symbol": "NIFTY-CE",
            "evaluated_at": "2026-08-13T10:01:00",
        }]

    def read_institutional_execution_evaluations(
        self, *, trading_date=None, limit=5000
    ):
        return []

    def read_execution_queue(
        self, *, trading_date=None, limit=5000
    ):
        return []

    def read_opportunity_evaluations(self, *, limit=50000):
        return []

    def read_paper_execution_orders(self, account_id):
        return []


def test_legacy_summary_and_match_aliases_remain_available(
    tmp_path: Path,
):
    folder = tmp_path / "fresh_setup_bundles_v43"
    folder.mkdir(parents=True)
    bundle = {
        "bundle_id": "B1",
        "instrument_key": "NSE_INDEX|Nifty_50",
        "detected_at": "2026-08-13T09:55:00",
        "fresh_until": "2026-08-13T10:10:00",
        "direction": "BULLISH",
        "primary_setup_type": "BULLISH_STRUCTURE_BREAK",
        "primary_signal_id": "V43-1",
    }
    (folder / "nifty.jsonl").write_text(
        json.dumps(bundle) + "\n",
        encoding="utf-8",
    )

    result = RangeHistoricalAttributionAudit(
        database=FakeDatabase(),
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

    assert result["summary"]["inferred_matches"] == 1
    assert result["summary"]["exact_matches"] == 0
    assert result["matches"][0]["match_method"] == (
        "DIRECTION_AND_WINDOW"
    )
    assert result["matches"][0]["match_resolution"] == (
        "PARTIAL_CHAIN_MATCH"
    )
