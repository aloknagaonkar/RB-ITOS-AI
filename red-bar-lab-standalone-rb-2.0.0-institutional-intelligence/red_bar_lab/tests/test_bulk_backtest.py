from datetime import date

import pandas as pd

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.bulk_backtest_service import BulkHistoricalBacktestService
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.storage.database import RedBarDatabase


def session(day: str) -> pd.DataFrame:
    # 09:15 through 15:29, deterministic 1-minute session.
    timestamps = pd.date_range(
        f"{day} 09:15",
        f"{day} 15:29",
        freq="1min",
        tz="Asia/Kolkata",
    )
    rows = []
    for i, ts in enumerate(timestamps):
        # Gentle oscillation around 100 to create crossings.
        base = 100 + ((i // 5) % 4 - 2) * 2
        rows.append(
            {
                "timestamp": ts,
                "open": base,
                "high": base + 3,
                "low": base - 3,
                "close": base + (1 if i % 2 == 0 else -1),
                "volume": 0,
                "oi": 0,
            }
        )
    return pd.DataFrame(rows)


class CacheOnlyProvider:
    def historical_candles(self, *args, **kwargs):
        raise AssertionError("Bulk backtest must not call provider")

    def intraday_candles(self, *args, **kwargs):
        raise AssertionError("Bulk backtest must not call provider")


def write_day(layout, day: date, frame: pd.DataFrame):
    path = layout.candle_path(
        "upstox", "NSE_INDEX|Nifty 50", 1, day.isoformat()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def test_bulk_backtest_uses_cached_dates_and_is_idempotent(tmp_path):
    settings = RedBarSettings(artifacts_root=tmp_path / "red_bar")
    layout = ArtifactLayout(settings)
    layout.ensure()
    database = RedBarDatabase(settings.database_path)
    historical = RedBarHistoricalService(CacheOnlyProvider(), layout)

    days = [
        date(2026, 7, 30),
        date(2026, 7, 31),
        date(2026, 8, 3),
    ]
    for day in days:
        write_day(layout, day, session(day.isoformat()))

    service = BulkHistoricalBacktestService(historical, database)
    first = service.run(
        "NSE_INDEX|Nifty 50",
        days[0],
        days[-1],
    )
    rows1 = database.paper_trade_range_rows(
        "NSE_INDEX|Nifty 50",
        days[0].isoformat(),
        days[-1].isoformat(),
    )

    second = service.run(
        "NSE_INDEX|Nifty 50",
        days[0],
        days[-1],
    )
    rows2 = database.paper_trade_range_rows(
        "NSE_INDEX|Nifty 50",
        days[0].isoformat(),
        days[-1].isoformat(),
    )

    assert first.trading_days_processed == 3
    assert second.trading_days_processed == 3
    assert len(rows1) == len(rows2)
