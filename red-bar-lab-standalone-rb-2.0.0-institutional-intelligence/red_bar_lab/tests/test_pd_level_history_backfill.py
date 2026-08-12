from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

import red_bar_lab.services.historical_service as historical_service_module
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.strategy.level_engine import build_daily_levels


class _Layout:
    def __init__(self, root: Path):
        self.root = root

    def candle_path(self, provider, instrument_key, interval_minutes, trading_date):
        safe_key = instrument_key.replace("|", "_").replace(":", "_")
        return (
            self.root
            / "candles"
            / provider
            / safe_key
            / str(interval_minutes)
            / f"{trading_date}.csv"
        )


class _Provider:
    def __init__(self, today: date):
        self.today = today
        self.historical_calls = []

    @staticmethod
    def _session(day: date):
        if day.weekday() >= 5:
            return pd.DataFrame(
                columns=("timestamp", "open", "high", "low", "close", "volume")
            )
        start = pd.Timestamp(day, tz="Asia/Kolkata") + pd.Timedelta(hours=9, minutes=15)
        rows = []
        for index in range(375):
            ts = start + pd.Timedelta(minutes=index)
            base = 24000.0 + day.day + index * 0.01
            rows.append(
                {
                    "timestamp": ts.isoformat(),
                    "open": base,
                    "high": base + 2.0,
                    "low": base - 2.0,
                    "close": base + 0.5,
                    "volume": 1000 + index,
                }
            )
        return pd.DataFrame(rows)

    def intraday_candles(self, instrument_key, interval_minutes=1):
        return self._session(self.today)

    def historical_candles(self, instrument_key, start_date, end_date, interval_minutes):
        self.historical_calls.append((start_date, end_date, interval_minutes))
        return self._session(start_date)


def test_live_available_dates_backfills_previous_sessions_for_pd_levels(tmp_path, monkeypatch):
    today = date(2026, 8, 12)
    monkeypatch.setattr(historical_service_module, "india_today", lambda: today)

    provider = _Provider(today)
    service = RedBarHistoricalService(provider, _Layout(tmp_path))
    instrument = "NSE_INDEX|Nifty 50"

    # Reproduce a fresh live cache: today's intraday file exists, but no prior
    # underlying session files have been downloaded yet.
    service.load_or_download(
        instrument,
        today,
        today,
        interval_minutes=1,
        force=True,
    )
    assert service._cached_dates(instrument, 1) == (today,)

    available = service.available_dates(instrument, interval_minutes=1)
    previous_dates = [day for day in available if day < today]

    assert len(previous_dates) == 10
    assert provider.historical_calls

    current = service.read_day(instrument, today, interval_minutes=1)
    previous = [
        (day, service.read_day(instrument, day, interval_minutes=1))
        for day in previous_dates
    ]
    levels = build_daily_levels(today, current, previous, previous_days=10)

    assert len(levels.previous_day_levels) == 10
    assert [level.level_type for level in levels.previous_day_levels] == [
        f"PD{rank}_315" for rank in range(1, 11)
    ]


def test_backfill_is_cache_aware_after_ten_previous_sessions_exist(tmp_path, monkeypatch):
    today = date(2026, 8, 12)
    monkeypatch.setattr(historical_service_module, "india_today", lambda: today)

    provider = _Provider(today)
    service = RedBarHistoricalService(provider, _Layout(tmp_path))
    instrument = "NSE_INDEX|Nifty 50"

    service.load_or_download(instrument, today, today, interval_minutes=1, force=True)
    service.available_dates(instrument, interval_minutes=1)
    first_call_count = len(provider.historical_calls)

    service.available_dates(instrument, interval_minutes=1)

    assert len(provider.historical_calls) == first_call_count
