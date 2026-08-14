from datetime import date, time
from pathlib import Path
import json

from red_bar_lab.services.historical_attribution_audit import (
    HistoricalAuditRequest,
    RangeHistoricalAttributionAudit,
)


class SelectionOnlyDatabase:
    def read_signal_attempts_range(
        self, instrument_key, date_from, date_to
    ):
        return []

    def read_trade_selection_evaluations(self, **kwargs):
        signal_id = kwargs.get("signal_id")
        if signal_id and signal_id != "PIPE":
            return []
        return [{
            "signal_id": "PIPE",
            "direction": "BEARISH",
            "candidate_symbol": "NIFTY-PE",
            "evaluated_at": "2026-08-13T09:20:00",
        }]

    def read_institutional_execution_evaluations(self, **kwargs):
        return []

    def read_execution_queue(self, **kwargs):
        return []

    def read_opportunity_evaluations(self, **kwargs):
        return []

    def read_paper_execution_orders(self, account_id):
        return []


def test_unique_selection_fallback_matches_only_one_bundle(
    tmp_path: Path,
):
    folder = tmp_path / "fresh_setup_bundles_v43"
    folder.mkdir(parents=True)
    rows = [
        {
            "bundle_id": "B1",
            "instrument_key": "NSE_INDEX|Nifty_50",
            "detected_at": "2026-08-13T09:15:00",
            "fresh_until": "2026-08-13T09:30:00",
            "direction": "BEARISH",
            "primary_setup_type": "BEARISH_STRUCTURE_BREAK",
            "primary_signal_id": "X1",
        },
        {
            "bundle_id": "B2",
            "instrument_key": "NSE_INDEX|Nifty_50",
            "detected_at": "2026-08-13T09:15:00",
            "fresh_until": "2026-08-13T09:30:00",
            "direction": "BEARISH",
            "primary_setup_type": "BEARISH_EMA_LOSS",
            "primary_signal_id": "X2",
        },
    ]
    (folder / "nifty.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    result = RangeHistoricalAttributionAudit(
        database=SelectionOnlyDatabase(),
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

    matched = [
        row
        for row in result["matches"]
        if row["match_method"] != "NO_MATCH"
    ]

    assert len(matched) == 1
    assert matched[0]["pipeline_signal_id"] == "PIPE"
    assert matched[0]["pipeline_signal_source"] == (
        "SELECTION_FALLBACK"
    )
    assert matched[0]["match_resolution"] == (
        "PARTIAL_CHAIN_MATCH"
    )
