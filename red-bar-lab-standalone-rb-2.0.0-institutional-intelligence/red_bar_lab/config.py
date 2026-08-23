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
    try:
        raw = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        raw = default
    return min(max(raw, minimum), maximum)


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        raw = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        raw = default
    return min(max(raw, minimum), maximum)


def _canonical_paper_mode() -> str:
    value = os.getenv("RED_BAR_V2_CANONICAL_PAPER_EXECUTION_MODE", "OBSERVE_ONLY").strip().upper()
    return value if value in {"OBSERVE_ONLY", "PAPER_CANARY"} else "INVALID"


def _provider(name: str) -> str:
    value = os.getenv(name, "UNCONFIGURED").strip().upper()
    return value if value in {"ZERODHA", "UPSTOX", "UNCONFIGURED"} else "INVALID"


def _paper_canary_market_data_provider() -> str:
    return _provider("RED_BAR_V2_PAPER_CANARY_MARKET_DATA_PROVIDER")


def _readiness_provider() -> str:
    return _provider("RED_BAR_V2_MARKET_DATA_READINESS_PROVIDER")


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
    red_bar_v2_paper_canary_worker_enabled: bool = False
    red_bar_v2_paper_canary_market_data_provider: str = "UNCONFIGURED"
    red_bar_v2_paper_canary_poll_seconds: float = 5.0
    red_bar_v2_paper_canary_max_actions_per_cycle: int = 1
    red_bar_v2_paper_canary_max_actions_per_day: int = 10
    red_bar_v2_paper_canary_max_bundle_age_seconds: float = 120.0
    red_bar_v2_paper_canary_failure_threshold: int = 3
    red_bar_v2_paper_canary_required_probe_cycles: int = 1
    red_bar_v2_market_data_readiness_enabled: bool = False
    red_bar_v2_market_data_readiness_provider: str = "UNCONFIGURED"
    red_bar_v2_market_data_readiness_max_quote_age_seconds: float = 30.0
    red_bar_v2_market_data_readiness_strike_steps: int = 4
    red_bar_v2_market_data_readiness_min_ce_coverage: int = 9
    red_bar_v2_market_data_readiness_min_pe_coverage: int = 9

    @property
    def database_path(self) -> Path:
        return self.artifacts_root / "database" / self.database_name

    @property
    def paper_canary_state_path(self) -> Path:
        return self.artifacts_root / "red_bar_v2_paper_canary_state.json"

    @property
    def market_data_readiness_state_path(self) -> Path:
        return self.artifacts_root / "red_bar_v2_market_data_readiness.json"

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
            red_bar_v2_canonical_shadow_enabled=_env_bool("RED_BAR_V2_CANONICAL_SHADOW_ENABLED", False),
            red_bar_v2_canonical_reservation_enabled=_env_bool("RED_BAR_V2_CANONICAL_RESERVATION_ENABLED", False),
            red_bar_v2_canonical_reservation_lease_seconds=_bounded_int("RED_BAR_V2_CANONICAL_RESERVATION_LEASE_SECONDS", 30, 5, 300),
            red_bar_v2_canonical_reservation_max_bundle_age_seconds=_bounded_int("RED_BAR_V2_CANONICAL_RESERVATION_MAX_BUNDLE_AGE_SECONDS", 120, 5, 3600),
            red_bar_v2_canonical_paper_execution_enabled=_env_bool("RED_BAR_V2_CANONICAL_PAPER_EXECUTION_ENABLED", False),
            red_bar_v2_canonical_paper_execution_mode=_canonical_paper_mode(),
            red_bar_v2_paper_canary_worker_enabled=_env_bool("RED_BAR_V2_PAPER_CANARY_WORKER_ENABLED", False),
            red_bar_v2_paper_canary_market_data_provider=_paper_canary_market_data_provider(),
            red_bar_v2_paper_canary_poll_seconds=_bounded_float("RED_BAR_V2_PAPER_CANARY_POLL_SECONDS", 5.0, 2.0, 60.0),
            red_bar_v2_paper_canary_max_actions_per_cycle=_bounded_int("RED_BAR_V2_PAPER_CANARY_MAX_ACTIONS_PER_CYCLE", 1, 1, 2),
            red_bar_v2_paper_canary_max_actions_per_day=_bounded_int("RED_BAR_V2_PAPER_CANARY_MAX_ACTIONS_PER_DAY", 10, 1, 50),
            red_bar_v2_paper_canary_max_bundle_age_seconds=_bounded_float("RED_BAR_V2_PAPER_CANARY_MAX_BUNDLE_AGE_SECONDS", 120.0, 15.0, 300.0),
            red_bar_v2_paper_canary_failure_threshold=_bounded_int("RED_BAR_V2_PAPER_CANARY_FAILURE_THRESHOLD", 3, 1, 10),
            red_bar_v2_paper_canary_required_probe_cycles=_bounded_int("RED_BAR_V2_PAPER_CANARY_REQUIRED_PROBE_CYCLES", 1, 1, 5),
            red_bar_v2_market_data_readiness_enabled=_env_bool("RED_BAR_V2_MARKET_DATA_READINESS_ENABLED", False),
            red_bar_v2_market_data_readiness_provider=_readiness_provider(),
            red_bar_v2_market_data_readiness_max_quote_age_seconds=_bounded_float("RED_BAR_V2_MARKET_DATA_READINESS_MAX_QUOTE_AGE_SECONDS", 30.0, 1.0, 300.0),
            red_bar_v2_market_data_readiness_strike_steps=_bounded_int("RED_BAR_V2_MARKET_DATA_READINESS_STRIKE_STEPS", 4, 1, 10),
            red_bar_v2_market_data_readiness_min_ce_coverage=_bounded_int("RED_BAR_V2_MARKET_DATA_READINESS_MIN_CE_COVERAGE", 9, 1, 21),
            red_bar_v2_market_data_readiness_min_pe_coverage=_bounded_int("RED_BAR_V2_MARKET_DATA_READINESS_MIN_PE_COVERAGE", 9, 1, 21),
        )


UNDERLYINGS = {
    "NIFTY 50": "NSE_INDEX|Nifty 50",
    "BANK NIFTY": "NSE_INDEX|Nifty Bank",
}
