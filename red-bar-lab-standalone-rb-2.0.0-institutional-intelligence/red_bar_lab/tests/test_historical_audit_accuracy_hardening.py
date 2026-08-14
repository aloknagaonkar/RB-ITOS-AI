from datetime import date, time
from pathlib import Path
import json

from red_bar_lab.services.fresh_setup_bundle_store import (
    FreshSetupBundleStore,
)
from red_bar_lab.services.historical_attribution_audit import (
    HistoricalAuditRequest,
    RangeHistoricalAttributionAudit,
)


class Database:
    def read_signal_attempts_range(self, *args):
        return [
            {
                "signal_id": "DATE-ONLY",
                "trading_date": "2026-08-13",
                "direction": "BULLISH",
            }
        ]

    def read_trade_selection_evaluations(self, **kwargs):
        limit = kwargs.get("limit", 5000)
        rows = [
            {
                "signal_id": f"S-{index}",
                "direction": "BEARISH",
                "candidate_symbol": f"PE-{index}",
                "evaluated_at": "2026-08-13T09:20:00",
            }
            for index in range(limit)
        ]
        return rows

    def read_institutional_execution_evaluations(self, **kwargs):
        return []
    def read_execution_queue(self, **kwargs):
        return []
    def read_opportunity_evaluations(self, **kwargs):
        return []
    def read_paper_execution_orders(self, *args):
        return []


def request():
    return HistoricalAuditRequest(
        instrument_key="NSE_INDEX|Nifty_50",
        date_from=date(2026, 8, 13),
        date_to=date(2026, 8, 13),
        start_time=time(9, 15),
        end_time=time(15, 30),
    )


def test_bundle_store_deduplicates_manual_and_backfill(tmp_path: Path):
    store = FreshSetupBundleStore(tmp_path / "bundles.jsonl")
    manual = {
        "bundle_id": "MANUAL",
        "instrument_key": "NIFTY",
        "detected_at": "2026-08-13T09:55:00",
        "direction": "BULLISH",
        "primary_setup_type": "BULLISH_STRUCTURE_BREAK",
    }
    backfill = {
        **manual,
        "bundle_id": "BACKFILL",
        "historical_backfill": True,
    }
    assert store.append_many_once([manual]) == 1
    assert store.append_many_once([backfill]) == 0
    assert len(store.canonical_rows()) == 1


def test_date_only_signal_is_not_lost_by_session_filter(tmp_path: Path):
    folder = tmp_path / "fresh_setup_bundles_v43"
    folder.mkdir(parents=True)
    result = RangeHistoricalAttributionAudit(
        database=Database(),
        runs_root=tmp_path,
    ).audit(request())
    signals = next(
        row for row in result["sources"]
        if row["source"] == "signals"
    )
    assert signals["date_filtered"] == 1
    assert signals["session_filtered"] == 1
    assert signals["session_time_unavailable"] == 1


def test_limit_hit_and_result_incomplete_are_exposed(tmp_path: Path):
    result = RangeHistoricalAttributionAudit(
        database=Database(),
        runs_root=tmp_path,
    ).audit(request())
    selection = next(
        row for row in result["sources"]
        if row["source"] == "selection"
    )
    assert selection["query_limit_hit"] is True
    assert selection["result_complete"] is False
    assert result["summary"]["incomplete_sources"] >= 1


def test_one_pipeline_row_is_not_reused(tmp_path: Path):
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

    class OneRowDatabase(Database):
        def read_trade_selection_evaluations(self, **kwargs):
            return [{
                "signal_id": "PIPE",
                "direction": "BEARISH",
                "candidate_symbol": "NIFTY-PE",
                "evaluated_at": "2026-08-13T09:20:00",
            }]

    result = RangeHistoricalAttributionAudit(
        database=OneRowDatabase(),
        runs_root=tmp_path,
    ).audit(request())
    matched = [
        row for row in result["matches"]
        if row["match_method"] != "NO_MATCH"
    ]
    assert len(matched) == 1
