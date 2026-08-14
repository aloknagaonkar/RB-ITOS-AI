from datetime import date, time
from pathlib import Path
import json

from red_bar_lab.services.historical_attribution_audit import (
    HistoricalAuditRequest,
    RangeHistoricalAttributionAudit,
    resolve_range_preset,
)


class FakeDatabase:
    def read_signal_attempts_range(self, instrument_key, date_from, date_to):
        return [
            {
                "signal_id": "PIPE-1",
                "instrument_key": instrument_key,
                "trading_date": "2026-08-13",
                "direction": "BULLISH",
                "confirmation_timestamp": "2026-08-13T10:00:00",
            }
        ]

    def read_trade_selection_evaluations(
        self, *, trading_date=None, limit=5000
    ):
        if trading_date != "2026-08-13":
            return []
        return [
            {
                "signal_id": "PIPE-1",
                "trading_date": trading_date,
                "direction": "BULLISH",
                "candidate_symbol": "NIFTY-CE",
                "evaluated_at": "2026-08-13T10:01:00",
            }
        ]

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


def write_bundle(runs_root: Path):
    folder = runs_root / "fresh_setup_bundles_v43"
    folder.mkdir(parents=True)
    row = {
        "bundle_id": "BND-1",
        "detected_at": "2026-08-13T09:55:00",
        "fresh_until": "2026-08-13T10:10:00",
        "direction": "BULLISH",
        "primary_setup_type": "BULLISH_STRUCTURE_BREAK",
        "primary_signal_id": "SIG-V43-1",
        "execution_allowed": False,
    }
    (folder / "NIFTY.jsonl").write_text(
        json.dumps(row) + "\n",
        encoding="utf-8",
    )


def test_range_presets():
    start, end = resolve_range_preset(
        "Previous 5 Trading Days",
        date(2026, 8, 14),
    )
    assert end == date(2026, 8, 14)
    assert start <= end


def test_read_only_range_audit_matches_direction_and_window(
    tmp_path: Path,
):
    write_bundle(tmp_path)
    request = HistoricalAuditRequest(
        instrument_key="NSE_INDEX|Nifty_50",
        date_from=date(2026, 8, 13),
        date_to=date(2026, 8, 13),
        start_time=time(9, 15),
        end_time=time(15, 30),
    )
    result = RangeHistoricalAttributionAudit(
        database=FakeDatabase(),
        runs_root=tmp_path,
    ).audit(request)

    assert result["summary"]["bundles"] == 1
    assert result["summary"]["inferred_matches"] == 1
    assert result["matches"][0]["match_method"] == (
        "DIRECTION_AND_WINDOW"
    )
    assert result["matches"][0]["execution_allowed"] is False
    assert result["matches"][0]["source_read_only"] is True


def test_rejects_range_over_90_days():
    request = HistoricalAuditRequest(
        instrument_key="NIFTY",
        date_from=date(2026, 1, 1),
        date_to=date(2026, 5, 1),
        start_time=time(9, 15),
        end_time=time(15, 30),
    )
    try:
        request.validate()
    except ValueError as exc:
        assert "maximum" in str(exc)
    else:
        raise AssertionError("Expected range validation error.")
