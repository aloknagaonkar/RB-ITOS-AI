from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from red_bar_lab.services.nifty_futures_history_backfill import (
    backfill_nifty_futures_history,
    resolve_expired_nifty_future,
)


class FakeExpiredGateway:
    def __init__(self):
        self.candle_calls = []

    def expiries(self, instrument_key):
        return ["2026-07-07", "2026-07-14", "2026-07-21", "2026-07-28"]

    def future_contracts(self, instrument_key, expiry_date):
        if expiry_date != "2026-07-28":
            return []
        return [
            {
                "name": "NIFTY",
                "segment": "NSE_FO",
                "expiry": expiry_date,
                "instrument_key": "NSE_FO|JULY|28-07-2026",
                "trading_symbol": "NIFTY FUT 28 JUL 26",
                "instrument_type": "FUT",
                "underlying_symbol": "NIFTY",
            }
        ]

    def historical_candles(self, expired_instrument_key, trading_date):
        self.candle_calls.append((expired_instrument_key, trading_date))
        timestamps = pd.date_range(
            f"{trading_date.isoformat()} 09:15", periods=375, freq="1min", tz="Asia/Kolkata"
        )
        return pd.DataFrame(
            {
                "timestamp": timestamps,
                "open": [100.0] * 375,
                "high": [101.0] * 375,
                "low": [99.0] * 375,
                "close": [100.0] * 375,
                "volume": [1000.0] * 375,
            }
        )


def test_expired_resolver_skips_weekly_expiries_and_selects_monthly_future():
    contract = resolve_expired_nifty_future(
        FakeExpiredGateway(),
        trading_date=date(2026, 7, 13),
    )
    assert contract.instrument_key == "NSE_FO|JULY|28-07-2026"
    assert contract.expiry == date(2026, 7, 28)
    assert contract.source == "UPSTOX_EXPIRED_FUTURES_API"


class FakeLayout:
    def __init__(self, root: Path):
        self.root = root

    def candle_path(self, provider_name, instrument_key, interval, day):
        safe = instrument_key.replace("|", "_")
        return self.root / provider_name / safe / str(interval) / f"{day}.csv"


class FakeHistorical:
    provider_name = "upstox"

    def __init__(self, root: Path):
        self.layout = FakeLayout(root)

    @staticmethod
    def _filter_session_date(frame, trading_date):
        result = frame.copy()
        result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True)
        mask = result["timestamp"].dt.tz_convert("Asia/Kolkata").dt.date == trading_date
        return result.loc[mask].reset_index(drop=True)

    def read_day(self, instrument_key, trading_date, interval_minutes=1):
        path = self.layout.candle_path(
            self.provider_name, instrument_key, interval_minutes, trading_date.isoformat()
        )
        return pd.read_csv(path) if path.exists() else pd.DataFrame()

    def load_or_download(self, *args, **kwargs):
        raise AssertionError("July date must use expired futures, not active August futures")


def test_backfill_prefers_expired_current_month_contract_for_july_date(tmp_path):
    active_august = [
        {
            "underlying_symbol": "NIFTY",
            "segment": "NSE_FO",
            "instrument_type": "FUT",
            "expiry": "2026-08-25",
            "instrument_key": "NSE_FO|58072",
            "trading_symbol": "NIFTY FUT 25 AUG 26",
        }
    ]
    result = backfill_nifty_futures_history(
        [date(2026, 7, 13)],
        historical=FakeHistorical(tmp_path),
        active_instruments=active_august,
        expired_gateway=FakeExpiredGateway(),
        artifacts_root=tmp_path,
    )

    assert result.downloaded_days == 1
    assert result.blocked_days == 0
    assert result.days[0].source_type == "EXPIRED"
    assert result.days[0].instrument_key == "NSE_FO|JULY|28-07-2026"
    manifest = pd.read_csv(result.manifest_path)
    assert manifest.iloc[0]["futures_instrument_key"] == "NSE_FO|JULY|28-07-2026"
