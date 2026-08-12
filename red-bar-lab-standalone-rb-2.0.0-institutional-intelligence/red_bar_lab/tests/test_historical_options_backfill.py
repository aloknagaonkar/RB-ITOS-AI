from datetime import date

from red_bar_lab.backfill.historical_options import (
    RedBarHistoricalOptionsBackfillService,
    _select_expiry,
    summarize_historical_oi,
)
from red_bar_lab.config import RedBarSettings
from red_bar_lab.storage.database import RedBarDatabase


def test_selects_first_expiry_on_or_after_trading_day():
    expiries = [
        "2026-07-09",
        "2026-07-16",
        "2026-07-23",
        "2026-07-30",
    ]
    assert _select_expiry(date(2026, 7, 10), expiries) == "2026-07-16"
    assert _select_expiry(date(2026, 7, 30), expiries) == "2026-07-30"


def test_summarizes_historical_oi_without_entry_alignment():
    oi = {
        "total_puts": 1800,
        "total_calls": 1500,
        "spot_closing_price": 25010.0,
        "expiry": "2026-07-16",
        "call_put_oi_data_list": [
            {"strike_price": 24950, "call_oi": 200, "put_oi": 900},
            {"strike_price": 25000, "call_oi": 1000, "put_oi": 700},
            {"strike_price": 25050, "call_oi": 300, "put_oi": 200},
        ],
    }
    change = {
        "total_put_change_oi": 300,
        "total_call_change_oi": -100,
        "spot_closing_price": 25010.0,
        "expiry": "2026-07-16",
        "call_put_oi_data_list": [
            {
                "strike_price": 25000,
                "call_change_oi": -100,
                "put_change_oi": 300,
            }
        ],
    }

    row = summarize_historical_oi(
        instrument_key="NSE_INDEX|Nifty 50",
        trading_date="2026-07-10",
        expiry="2026-07-16",
        oi_data=oi,
        change_data=change,
    )

    assert row["pcr_oi"] == 1.2
    assert row["call_wall_strike"] == 25000.0
    assert row["put_wall_strike"] == 24950.0
    assert row["entry_aligned"] == 0
    assert row["source_type"] == "UPSTOX_PLUS_HISTORICAL_OI_EOD"


class FakeProvider:
    def expired_option_expiries(self, instrument_key):
        return ["2026-07-09", "2026-07-16", "2026-07-23"]

    def option_expiries(self, instrument_key):
        return []

    def historical_oi(self, instrument_key, expiry, trading_date):
        return {
            "total_puts": 1200,
            "total_calls": 1000,
            "spot_closing_price": 25000.0,
            "expiry": expiry,
            "call_put_oi_data_list": [
                {"strike_price": 25000, "call_oi": 1000, "put_oi": 1200}
            ],
        }

    def historical_change_oi(
        self,
        instrument_key,
        expiry,
        trading_date,
        interval_days=1,
    ):
        return {
            "total_put_change_oi": 120,
            "total_call_change_oi": 100,
            "spot_closing_price": 25000.0,
            "expiry": expiry,
            "call_put_oi_data_list": [
                {
                    "strike_price": 25000,
                    "call_change_oi": 100,
                    "put_change_oi": 120,
                }
            ],
        }


def test_backfill_range_persists_weekdays_and_skips_weekend(tmp_path):
    settings = RedBarSettings(
        artifacts_root=tmp_path / "artifacts"
    )
    db = RedBarDatabase(settings.database_path)
    db.initialize()

    service = RedBarHistoricalOptionsBackfillService(
        FakeProvider(),
        db,
        settings,
    )
    report = service.backfill_range(
        instrument_key="NSE_INDEX|Nifty 50",
        date_from=date(2026, 7, 10),  # Friday
        date_to=date(2026, 7, 13),    # Monday
    )

    assert report.completed_days == 2
    assert report.skipped_days == 2
    rows = db.read_historical_option_backfill_range(
        "NSE_INDEX|Nifty 50",
        "2026-07-10",
        "2026-07-13",
    )
    assert len(rows) == 2
    assert all(row["entry_aligned"] == 0 for row in rows)
