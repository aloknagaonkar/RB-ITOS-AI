"""Typed platform configuration with environment variable loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes")


def _env_int(key: str, default: int, lo: int = 0, hi: int = 999999) -> int:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
        return max(lo, min(hi, val))
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float, lo: float = 0.0, hi: float = 999999.0) -> float:
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
        return max(lo, min(hi, val))
    except (ValueError, TypeError):
        return default


def _env_path(key: str, default: str) -> Path:
    raw = os.getenv(key, "").strip()
    return Path(raw) if raw else Path(default)


@dataclass(frozen=True)
class PlatformConfig:
    """Immutable configuration for the platform supervisor."""

    underlying: str = field(default_factory=lambda: os.getenv("RED_BAR_UNDERLYING", "NIFTY 50"))
    collector_interval_seconds: int = field(default_factory=lambda: _env_int("RED_BAR_COLLECTOR_INTERVAL_SECONDS", 60, 60, 3600))
    paper_monitor_interval_seconds: int = field(default_factory=lambda: _env_int("RED_BAR_PAPER_MONITOR_INTERVAL_SECONDS", 5, 2, 3600))
    position_monitor_interval_seconds: int = field(default_factory=lambda: _env_int("RED_BAR_POSITION_MONITOR_INTERVAL_SECONDS", 5, 2, 60))
    ui_port: int = field(default_factory=lambda: _env_int("RED_BAR_UI_PORT", 8502, 1024, 65535))
    capital: float = field(default_factory=lambda: _env_float("RED_BAR_CAPITAL", 100000.0, 10000.0, 10000000.0))
    lots: int = field(default_factory=lambda: _env_int("RED_BAR_LOTS", 1, 1, 20))
    minimum_score: float = field(default_factory=lambda: _env_float("RED_BAR_MINIMUM_SCORE", 65.0, 0.0, 100.0))
    artifacts_root: Path = field(default_factory=lambda: _env_path("RED_BAR_ARTIFACTS_ROOT", "artifacts/red_bar"))
    start_market_research: bool = field(default_factory=lambda: _env_bool("RED_BAR_START_MARKET_RESEARCH", True))
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent.parent)

    def validate(self) -> list[str]:
        """Return list of validation error messages. Empty means valid."""
        errors: list[str] = []

        if not os.getenv("UPSTOX_ACCESS_TOKEN", "").strip():
            errors.append("UPSTOX_ACCESS_TOKEN is not set")

        if self.underlying not in ("NIFTY 50", "BANK NIFTY"):
            errors.append(f"Invalid underlying: {self.underlying}")

        db_parent = self.project_root / self.artifacts_root / "database"
        try:
            db_parent.mkdir(parents=True, exist_ok=True)
            test_file = db_parent / ".platform_write_test"
            test_file.write_text("ok")
            test_file.unlink()
        except OSError as exc:
            errors.append(f"Database directory not writable: {db_parent} ({exc})")

        return errors
