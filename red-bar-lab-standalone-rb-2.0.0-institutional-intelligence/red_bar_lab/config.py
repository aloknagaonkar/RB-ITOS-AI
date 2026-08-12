from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class RedBarSettings:
    app_name: str = "Red Bar Strategy Lab"
    version: str = "RB-1.5.2c"
    port: int = 8502
    artifacts_root: Path = Path("artifacts/red_bar")
    database_name: str = "red_bar_strategy.db"
    default_underlying: str = "NIFTY 50"
    default_interval_minutes: int = 1

    @property
    def database_path(self) -> Path:
        return self.artifacts_root / "database" / self.database_name

    @property
    def logs_root(self) -> Path:
        return self.artifacts_root / "logs"

    @property
    def historical_root(self) -> Path:
        return self.artifacts_root / "data" / "historical"

    @property
    def live_root(self) -> Path:
        return self.artifacts_root / "data" / "live"

    @property
    def reports_root(self) -> Path:
        return self.artifacts_root / "reports"

    @property
    def runs_root(self) -> Path:
        return self.artifacts_root / "runs"

    @classmethod
    def from_env(cls) -> "RedBarSettings":
        return cls(
            port=int(os.getenv("RED_BAR_PORT", "8502")),
            artifacts_root=Path(os.getenv("RED_BAR_ARTIFACTS_ROOT", "artifacts/red_bar")),
        )


UNDERLYINGS = {
    "NIFTY 50": "NSE_INDEX|Nifty 50",
    "BANK NIFTY": "NSE_INDEX|Nifty Bank",
}
