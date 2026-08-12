from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.services.upstox_service import RedBarUpstoxService


EXPECTED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
INDIA_TZ = ZoneInfo("Asia/Kolkata")


def india_today() -> date:
    return datetime.now(INDIA_TZ).date()


def normalize_candles(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=EXPECTED_COLUMNS)
    result = frame.copy()
    missing = [name for name in EXPECTED_COLUMNS if name not in result.columns]
    if missing:
        raise ValueError(f"Historical candle data is missing columns: {missing}")
    result["timestamp"] = pd.to_datetime(result["timestamp"], errors="coerce", utc=True)
    result = result.dropna(subset=["timestamp"]).sort_values("timestamp")
    result = result.drop_duplicates(subset=["timestamp"], keep="last")
    return result.reset_index(drop=True)


@dataclass
class HistoricalDownloadResult:
    downloaded_dates: tuple[date, ...]
    existing_dates: tuple[date, ...]
    no_data_dates: tuple[date, ...]
    rows_stored: int
    in_progress_dates: tuple[date, ...] = ()
    future_dates: tuple[date, ...] = ()


@dataclass
class RedBarHistoricalService:
    provider: RedBarUpstoxService
    layout: ArtifactLayout
    provider_name: str = "upstox"

    @staticmethod
    def _filter_session_date(frame: pd.DataFrame, trading_date: date) -> pd.DataFrame:
        normalized = normalize_candles(frame)
        if normalized.empty:
            return normalized
        local_dates = normalized["timestamp"].dt.tz_convert(INDIA_TZ).dt.date
        return normalized.loc[local_dates == trading_date].reset_index(drop=True)

    def load_or_download(
        self,
        instrument_key: str,
        start_date: date,
        end_date: date,
        interval_minutes: int = 1,
        force: bool = False,
    ) -> HistoricalDownloadResult:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")

        downloaded: list[date] = []
        existing: list[date] = []
        no_data: list[date] = []
        in_progress: list[date] = []
        future: list[date] = []
        rows_stored = 0
        current = start_date
        today = india_today()

        while current <= end_date:
            path = self.layout.candle_path(
                self.provider_name, instrument_key, interval_minutes, current.isoformat()
            )

            if current > today:
                future.append(current)
                current += timedelta(days=1)
                continue

            # Completed dates are immutable cache artifacts unless force=True.
            if current < today and path.exists() and not force:
                existing.append(current)
                current += timedelta(days=1)
                continue

            # Today's session must always be refreshed because its cache is partial.
            if current == today:
                source = self.provider.intraday_candles(
                    instrument_key, interval_minutes=interval_minutes
                )
                in_progress.append(current)
            else:
                source = self.provider.historical_candles(
                    instrument_key, current, current, interval_minutes
                )

            frame = self._filter_session_date(source, current)
            if frame.empty:
                no_data.append(current)
                current += timedelta(days=1)
                continue

            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, index=False)
            downloaded.append(current)
            rows_stored += len(frame)
            current += timedelta(days=1)

        return HistoricalDownloadResult(
            tuple(downloaded),
            tuple(existing),
            tuple(no_data),
            rows_stored,
            tuple(in_progress),
            tuple(future),
        )

    def read_day(
        self,
        instrument_key: str,
        trading_date: date,
        interval_minutes: int = 1,
    ) -> pd.DataFrame:
        path = self.layout.candle_path(
            self.provider_name, instrument_key, interval_minutes, trading_date.isoformat()
        )
        if not path.exists():
            return pd.DataFrame(columns=EXPECTED_COLUMNS)
        return normalize_candles(pd.read_csv(path))

    def available_dates(
        self, instrument_key: str, interval_minutes: int = 1
    ) -> tuple[date, ...]:
        sample = self.layout.candle_path(
            self.provider_name, instrument_key, interval_minutes, "2000-01-01"
        )
        folder = sample.parent
        if not folder.exists():
            return ()
        result = []
        for path in folder.glob("*.csv"):
            try:
                result.append(date.fromisoformat(path.stem))
            except ValueError:
                continue
        return tuple(sorted(result))
