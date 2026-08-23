from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = int(os.getenv(name, str(default)))
    return min(max(raw, minimum), maximum)


def _canonical_paper_mode() -> str:
    value = os.getenv(
        "RED_BAR_V2_CANONICAL_PAPER_EXECUTION_MODE",
        "OBSERVE_ONLY",
    ).strip().upper()
    return value if value in {"OBSERVE_ONLY", "PAPER_CANARY"} else "INVALID"


@dataclass(frozen=True)
class RedBarSettings:
    app_name: str = "Red Bar Strategy Lab"
    version: str = "RB-1.5.2c"
    port: int = 8502
    artifacts_root: Path = Path("artifacts/red_bar")
    database_name: str = "red_bar_strategy.db"
    default_underlying: str = "NIFTY 50"
    default_interval_minutes: int = 1
    red_bar_v2_canonical_shadow_enabled: bool = False
    red_bar_v2_canonical_reservation_enabled: bool = False
    red_bar_v2_canonical_reservation_lease_seconds: int = 30
    red_bar_v2_canonical_reservation_max_bundle_age_seconds: int = 120
    red_bar_v2_canonical_paper_execution_enabled: bool = False
    red_bar_v2_canonical_paper_execution_mode: str = "OBSERVE_ONLY"

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
            red_bar_v2_canonical_shadow_enabled=_env_bool(
                "RED_BAR_V2_CANONICAL_SHADOW_ENABLED",
                False,
            ),
            red_bar_v2_canonical_reservation_enabled=_env_bool(
                "RED_BAR_V2_CANONICAL_RESERVATION_ENABLED",
                False,
            ),
            red_bar_v2_canonical_reservation_lease_seconds=_bounded_int(
                "RED_BAR_V2_CANONICAL_RESERVATION_LEASE_SECONDS",
                30,
                5,
                300,
            ),
            red_bar_v2_canonical_reservation_max_bundle_age_seconds=_bounded_int(
                "RED_BAR_V2_CANONICAL_RESERVATION_MAX_BUNDLE_AGE_SECONDS",
                120,
                5,
                3600,
            ),
            red_bar_v2_canonical_paper_execution_enabled=_env_bool(
                "RED_BAR_V2_CANONICAL_PAPER_EXECUTION_ENABLED",
                False,
            ),
            red_bar_v2_canonical_paper_execution_mode=_canonical_paper_mode(),
        )


UNDERLYINGS = {
    "NIFTY 50": "NSE_INDEX|Nifty 50",
    "BANK NIFTY": "NSE_INDEX|Nifty Bank",
}
