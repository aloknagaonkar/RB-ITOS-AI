from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.services.upstox_service import RedBarUpstoxService


EXPECTED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
INDIA_TZ = ZoneInfo("Asia/Kolkata")
MINIMUM_PREVIOUS_SESSIONS = 10
PREVIOUS_SESSION_LOOKBACK_DAYS = 30


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

    def _cached_dates(
        self,
        instrument_key: str,
        interval_minutes: int = 1,
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

    def ensure_previous_sessions(
        self,
        instrument_key: str,
        *,
        trading_date: date | None = None,
        interval_minutes: int = 1,
        minimum_sessions: int = MINIMUM_PREVIOUS_SESSIONS,
    ) -> tuple[date, ...]:
        """Ensure enough completed underlying sessions exist for PD levels.

        Live refresh previously downloaded only today's candles, then asked the
        local cache for prior dates. On a fresh runtime/cache that returned no
        history, so PD1_315..PD10_315 could not be built at all. This method
        performs a bounded, cache-aware backfill only when prior sessions are
        missing. Existing completed files remain immutable and are not fetched
        again.
        """
        target_date = trading_date or india_today()
        cached = self._cached_dates(instrument_key, interval_minutes)
        previous = [day for day in cached if day < target_date]
        if len(previous) >= int(minimum_sessions):
            return tuple(previous[-int(minimum_sessions):])

        end_date = target_date - timedelta(days=1)
        start_date = target_date - timedelta(days=PREVIOUS_SESSION_LOOKBACK_DAYS)
        try:
            self.load_or_download(
                instrument_key,
                start_date,
                end_date,
                interval_minutes=interval_minutes,
                force=False,
            )
        except Exception:
            # History enrichment must not break the live page. The caller can
            # continue with whatever cache is already available.
            pass

        cached = self._cached_dates(instrument_key, interval_minutes)
        previous = [day for day in cached if day < target_date]
        return tuple(previous[-int(minimum_sessions):])

    def available_dates(
        self, instrument_key: str, interval_minutes: int = 1
    ) -> tuple[date, ...]:
        cached = self._cached_dates(instrument_key, interval_minutes)
        today = india_today()

        # If today's session is present, this call is part of the live/current
        # workflow. Ensure the historical context required for PD1..PD10 exists
        # before returning the available date list. Historical-only callers that
        # do not have a current-session file keep the original read-only behavior.
        if today in cached:
            previous = [day for day in cached if day < today]
            if len(previous) < MINIMUM_PREVIOUS_SESSIONS:
                self.ensure_previous_sessions(
                    instrument_key,
                    trading_date=today,
                    interval_minutes=interval_minutes,
                    minimum_sessions=MINIMUM_PREVIOUS_SESSIONS,
                )
                cached = self._cached_dates(instrument_key, interval_minutes)

        return cached
