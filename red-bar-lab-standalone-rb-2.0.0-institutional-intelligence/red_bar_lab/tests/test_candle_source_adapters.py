from datetime import date

import pandas as pd

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.candle_source_adapters import (
    build_historical_candle_reader,
    build_live_persisted_candle_reader,
)
from red_bar_lab.storage.artifacts import ArtifactLayout


def test_live_reader_uses_persisted_current_session_csv(tmp_path):
    settings = RedBarSettings(artifacts_root=tmp_path / "artifacts")
    layout = ArtifactLayout(settings)
    path = layout.live_session_path("upstox", "NSE_INDEX|Nifty 50", 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [{"timestamp": "2026-08-21T10:20:00+05:30", "close": 25000.0}]
    ).to_csv(path, index=False)

    rows = build_live_persisted_candle_reader(settings)(
        instrument_key="NSE_INDEX|Nifty 50",
        timeframe="1m",
        cutoff_timestamp="2026-08-21T10:25:00+05:30",
    )

    assert len(rows) == 1
    assert rows[0]["close"] == 25000.0


def test_live_reader_returns_empty_when_persisted_file_missing(tmp_path):
    settings = RedBarSettings(artifacts_root=tmp_path / "artifacts")
    rows = build_live_persisted_candle_reader(settings)(
        instrument_key="NSE_INDEX|Nifty 50",
        timeframe="1m",
        cutoff_timestamp="2026-08-21T10:25:00+05:30",
    )
    assert rows == []


class FakeHistorical:
    def __init__(self):
        self.calls = []

    def read_day(self, instrument_key, trading_date, interval_minutes):
        self.calls.append((instrument_key, trading_date, interval_minutes))
        return pd.DataFrame(
            [{"timestamp": "2026-08-20T10:20:00+05:30", "close": 24900.0}]
        )


def test_historical_reader_uses_cutoff_date_and_timeframe():
    historical = FakeHistorical()
    rows = build_historical_candle_reader(historical)(
        instrument_key="NSE_INDEX|Nifty 50",
        timeframe="5m",
        cutoff_timestamp="2026-08-20T10:25:00+05:30",
    )

    assert len(rows) == 1
    assert historical.calls == [
        ("NSE_INDEX|Nifty 50", date(2026, 8, 20), 5)
    ]
