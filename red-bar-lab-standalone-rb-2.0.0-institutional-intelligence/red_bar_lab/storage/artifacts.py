from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from red_bar_lab.config import RedBarSettings


@dataclass(frozen=True)
class ArtifactLayout:
    settings: RedBarSettings

    def ensure(self) -> None:
        for path in (
            self.settings.artifacts_root,
            self.settings.database_path.parent,
            self.settings.logs_root,
            self.settings.historical_root,
            self.settings.live_root,
            self.settings.reports_root,
            self.settings.runs_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_instrument(instrument_key: str) -> str:
        return (
            instrument_key.replace("|", "_")
            .replace(" ", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )

    def candle_path(
        self,
        provider: str,
        instrument_key: str,
        interval_minutes: int,
        trading_date: str,
    ) -> Path:
        return (
            self.settings.historical_root
            / provider
            / self._safe_instrument(instrument_key)
            / str(interval_minutes)
            / f"{trading_date}.csv"
        )

    def live_session_path(
        self,
        provider: str,
        instrument_key: str,
        interval_minutes: int = 1,
    ) -> Path:
        return (
            self.settings.live_root
            / provider
            / self._safe_instrument(instrument_key)
            / f"current_{interval_minutes}m.csv"
        )
