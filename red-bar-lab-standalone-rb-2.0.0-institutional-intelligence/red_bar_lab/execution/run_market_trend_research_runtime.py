from __future__ import annotations

from datetime import time
import os

from red_bar_lab.brokers.upstox_client import UpstoxClient
from red_bar_lab.config import RedBarSettings
from red_bar_lab.execution.run_market_trend_research import verified_calendar
from red_bar_lab.services.market_trend_research import (
    DualPcrCalculator,
    MarketTrendResearchPolicy,
    MarketTrendResearchRepository,
    MarketTrendResearchRuntime,
    MarketTrendResearchService,
    OptionParticipationSnapshotSource,
    ResearchRuntimeConfig,
    UpstoxResearchChainCollector,
)
from red_bar_lab.services.upstox_service import RedBarUpstoxService, resolve_access_token


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _clock(name: str, default: str) -> time:
    raw = os.getenv(name, default).strip()
    parts = raw.split(":")
    if len(parts) not in {2, 3}:
        raise ValueError(f"{name}_INVALID")
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    return time(hour, minute, second)


def main() -> int:
    enabled = _bool("MARKET_TREND_RESEARCH_RUNTIME_ENABLED", False)
    if not enabled:
        print(
            "market-trend-research-runtime outcome=DISABLED "
            "authority=OBSERVATIONAL_ONLY"
        )
        return 2
    settings = RedBarSettings.from_env()
    calendar = verified_calendar()
    policy = MarketTrendResearchPolicy(
        maximum_source_age_seconds=_float(
            "MARKET_TREND_RESEARCH_MAX_SOURCE_AGE_SECONDS", 30.0
        ),
        hard_deadline_seconds=_float(
            "MARKET_TREND_RESEARCH_HARD_DEADLINE_SECONDS", 2.0
        ),
        reference_start=_clock("MARKET_TREND_RESEARCH_REFERENCE_START", "09:08:00"),
        reference_cutoff=_clock("MARKET_TREND_RESEARCH_REFERENCE_CUTOFF", "09:14:59"),
        oi_baseline_start=_clock("MARKET_TREND_RESEARCH_OI_BASELINE_START", "09:15:00"),
    )
    repository = MarketTrendResearchRepository(settings.database_path)
    provider_name = os.getenv("MARKET_TREND_RESEARCH_PROVIDER", "UPSTOX").strip().upper()
    if provider_name != "UPSTOX":
        raise ValueError("MARKET_TREND_RESEARCH_PROVIDER_UNSUPPORTED")
    request_timeout = _int("MARKET_TREND_RESEARCH_REQUEST_TIMEOUT_SECONDS", 10)
    if not 1 <= request_timeout <= 60:
        raise ValueError("MARKET_TREND_RESEARCH_REQUEST_TIMEOUT_INVALID")
    provider = RedBarUpstoxService(
        resolve_access_token(),
        client_factory=lambda token: UpstoxClient(token, timeout=request_timeout),
    )
    collector = UpstoxResearchChainCollector(
        provider=provider,
        repository=repository,
        policy=policy,
        calendar=calendar,
        underlying=settings.default_underlying,
        instrument_key="NSE_INDEX|Nifty 50",
    )
    service = MarketTrendResearchService(
        source=OptionParticipationSnapshotSource(settings.database_path),
        repository=repository,
        policy=policy,
        calendar=calendar,
        calculator=DualPcrCalculator(policy),
    )
    runtime = MarketTrendResearchRuntime(
        collector=collector,
        service=service,
        repository=repository,
        config=ResearchRuntimeConfig(
            enabled=True,
            refresh_seconds=_float("MARKET_TREND_RESEARCH_REFRESH_SECONDS", 5.0),
            maximum_backoff_seconds=_float(
                "MARKET_TREND_RESEARCH_MAX_BACKOFF_SECONDS", 60.0
            ),
        ),
    )
    print(
        "market-trend-research-runtime outcome=STARTED cadence_seconds="
        f"{runtime.config.refresh_seconds} provider=UPSTOX "
        f"request_timeout_seconds={request_timeout} "
        "authority=OBSERVATIONAL_ONLY"
    )
    try:
        runtime.run_forever()
    except KeyboardInterrupt:
        runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
