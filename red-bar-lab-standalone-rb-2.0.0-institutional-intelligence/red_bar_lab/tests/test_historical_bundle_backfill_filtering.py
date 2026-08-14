from datetime import date, time
from pathlib import Path
import json

import pandas as pd

from red_bar_lab.services.historical_bundle_backfill import (
    HistoricalBundleBackfillRequest,
    HistoricalV43BundleBackfill,
)
from red_bar_lab.services.historical_attribution_audit import (
    HistoricalAuditRequest,
    RangeHistoricalAttributionAudit,
)


class Settings:
    def __init__(self, root):
        self.runs_root = root


class Layout:
    def __init__(self, root):
        self.settings = Settings(root)

    def _safe_instrument(self, value):
        return value.replace("|", "_").replace(":", "_")


class Historical:
    def __init__(self):
        rows = []
        start = pd.Timestamp("2026-08-13T09:15:00")
        for index in range(390):
            price = 24000 + index * 0.2
            rows.append({
                "timestamp": start + pd.Timedelta(minutes=index),
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price + 0.5,
                "volume": 100,
            })
        self.one = pd.DataFrame(rows)
        five_rows = []
        for index in range(78):
            price = 24000 + index
            five_rows.append({
                "timestamp": start + pd.Timedelta(minutes=index * 5),
                "open": price,
                "high": price + 2.0,
                "low": price - 2.0,
                "close": price + 1.0,
                "volume": 500,
            })
        self.five = pd.DataFrame(five_rows)

    def load_or_download(self, *args, **kwargs):
        return None

    def read_day(self, instrument_key, trading_date, interval_minutes=1):
        return self.one.copy() if interval_minutes == 1 else self.five.copy()


class AuditDatabase:
    def read_signal_attempts_range(self, *args):
        return [{
            "signal_id": "S1",
            "instrument_key": "NSE_INDEX|Nifty_50",
            "direction": "BULLISH",
            "confirmation_timestamp": "2026-08-13T10:00:00",
        }]

    def read_trade_selection_evaluations(self, **kwargs):
        return [
            {
                "signal_id": "S1",
                "instrument_key": "NSE_INDEX|Nifty_50",
                "direction": "BULLISH",
                "evaluated_at": "2026-08-13T10:01:00",
            },
            {
                "signal_id": "OLD",
                "instrument_key": "NSE_INDEX|Nifty_50",
                "direction": "BULLISH",
                "evaluated_at": "2026-08-12T10:01:00",
            },
        ]

    def read_institutional_execution_evaluations(self, **kwargs):
        return []
    def read_execution_queue(self, **kwargs):
        return []
    def read_opportunity_evaluations(self, **kwargs):
        return []
    def read_paper_execution_orders(self, *args):
        return []


def test_backfill_generates_and_deduplicates_bundles(tmp_path: Path):
    request = HistoricalBundleBackfillRequest(
        instrument_key="NSE_INDEX|Nifty_50",
        date_from=date(2026, 8, 13),
        date_to=date(2026, 8, 13),
        start_time=time(9, 15),
        end_time=time(15, 30),
        persist_artifacts=True,
    )
    service = HistoricalV43BundleBackfill(
        historical=Historical(),
        layout=Layout(tmp_path),
    )
    first = service.run(request)
    second = service.run(request)

    assert first["summary"]["bars_evaluated"] > 0
    assert first["summary"]["bundles_inserted"] > 0
    assert second["summary"]["bundles_inserted"] == 0
    assert first["summary"]["execution_allowed"] is False


def test_source_counts_show_filter_reduction(tmp_path: Path):
    folder = tmp_path / "fresh_setup_bundles_v43"
    folder.mkdir(parents=True)
    bundle = {
        "bundle_id": "B1",
        "detected_at": "2026-08-13T09:55:00",
        "fresh_until": "2026-08-13T10:10:00",
        "direction": "BULLISH",
        "primary_setup_type": "BULLISH_STRUCTURE_BREAK",
        "primary_signal_id": "V43",
    }
    (folder/"NIFTY.jsonl").write_text(json.dumps(bundle)+"\n")
    result = RangeHistoricalAttributionAudit(
        database=AuditDatabase(),
        runs_root=tmp_path,
    ).audit(HistoricalAuditRequest(
        instrument_key="NSE_INDEX|Nifty_50",
        date_from=date(2026, 8, 13),
        date_to=date(2026, 8, 13),
        start_time=time(9, 15),
        end_time=time(15, 30),
    ))
    selection = next(
        row for row in result["sources"]
        if row["source"] == "selection"
    )
    assert selection["raw_rows"] == 2
    assert selection["date_filtered"] == 1
    assert selection["matching_rows"] == 1
    assert selection["read_only"] is True
