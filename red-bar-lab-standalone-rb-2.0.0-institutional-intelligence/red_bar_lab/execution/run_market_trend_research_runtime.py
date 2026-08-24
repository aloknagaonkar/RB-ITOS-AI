from __future__ import annotations

import os

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
    )
    repository = MarketTrendResearchRepository(settings.database_path)
    provider_name = os.getenv("MARKET_TREND_RESEARCH_PROVIDER", "UPSTOX").strip().upper()
    if provider_name != "UPSTOX":
        raise ValueError("MARKET_TREND_RESEARCH_PROVIDER_UNSUPPORTED")
    provider = RedBarUpstoxService(resolve_access_token())
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
        "authority=OBSERVATIONAL_ONLY"
    )
    try:
        runtime.run_forever()
    except KeyboardInterrupt:
        runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
