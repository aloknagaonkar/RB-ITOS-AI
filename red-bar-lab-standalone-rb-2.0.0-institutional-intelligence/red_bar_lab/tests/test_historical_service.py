from datetime import date

import pandas as pd

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services import historical_service as historical_module
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.storage.artifacts import ArtifactLayout


def candle_frame(day: date, close: float = 104.0) -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "timestamp": f"{day.isoformat()}T09:15:00+05:30",
            "open": 100,
            "high": 105,
            "low": 99,
            "close": close,
            "volume": 1000,
            "open_interest": 0,
        }]
    )


class Provider:
    def __init__(self):
        self.historical_calls = []
        self.intraday_calls = []
        self.intraday_close = 104.0

    def historical_candles(self, instrument_key, start_date, end_date, interval_minutes=1):
        self.historical_calls.append((start_date, end_date, interval_minutes))
        return candle_frame(start_date)

    def intraday_candles(self, instrument_key, interval_minutes=1):
        self.intraday_calls.append(interval_minutes)
        return candle_frame(date(2026, 8, 6), self.intraday_close)


def service(tmp_path, provider):
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    layout = ArtifactLayout(settings)
    layout.ensure()
    return RedBarHistoricalService(provider, layout), layout


def test_historical_download_uses_separate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(historical_module, "india_today", lambda: date(2026, 8, 6))
    provider = Provider()
    historical, layout = service(tmp_path, provider)
    result = historical.load_or_download(
        "NSE_INDEX|Nifty 50", date(2026, 7, 31), date(2026, 7, 31)
    )
    assert result.rows_stored == 1
    path = layout.candle_path("upstox", "NSE_INDEX|Nifty 50", 1, "2026-07-31")
    assert path.exists()
    assert provider.historical_calls
    assert not provider.intraday_calls


def test_today_uses_intraday_and_refreshes_existing_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(historical_module, "india_today", lambda: date(2026, 8, 6))
    provider = Provider()
    historical, _ = service(tmp_path, provider)

    first = historical.load_or_download(
        "NSE_INDEX|Nifty 50", date(2026, 8, 6), date(2026, 8, 6)
    )
    provider.intraday_close = 111.0
    second = historical.load_or_download(
        "NSE_INDEX|Nifty 50", date(2026, 8, 6), date(2026, 8, 6)
    )

    stored = historical.read_day("NSE_INDEX|Nifty 50", date(2026, 8, 6))
    assert first.in_progress_dates == (date(2026, 8, 6),)
    assert second.in_progress_dates == (date(2026, 8, 6),)
    assert len(provider.intraday_calls) == 2
    assert not provider.historical_calls
    assert float(stored.iloc[0]["close"]) == 111.0


def test_completed_date_reuses_cache_but_today_does_not(tmp_path, monkeypatch):
    monkeypatch.setattr(historical_module, "india_today", lambda: date(2026, 8, 6))
    provider = Provider()
    historical, _ = service(tmp_path, provider)
    day = date(2026, 8, 5)
    historical.load_or_download("NIFTY", day, day)
    again = historical.load_or_download("NIFTY", day, day)
    assert again.existing_dates == (day,)
    assert len(provider.historical_calls) == 1


def test_future_date_is_skipped_without_provider_call(tmp_path, monkeypatch):
    monkeypatch.setattr(historical_module, "india_today", lambda: date(2026, 8, 6))
    provider = Provider()
    historical, _ = service(tmp_path, provider)
    result = historical.load_or_download(
        "NIFTY", date(2026, 8, 7), date(2026, 8, 7)
    )
    assert result.future_dates == (date(2026, 8, 7),)
    assert result.rows_stored == 0
    assert not provider.historical_calls
    assert not provider.intraday_calls
