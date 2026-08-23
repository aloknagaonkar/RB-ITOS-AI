from __future__ import annotations

import os

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data import (
    PaperMarketDataConfigurationError,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_factory import (
    build_paper_canary_market_data,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness import (
    PaperMarketDataReadinessService,
    SystemClock,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness_models import (
    MarketDataReadinessPolicy,
    MarketDataReadinessStatus,
)
from red_bar_lab.services.red_bar_v2_canonical.paper_market_data_readiness_store import (
    AtomicJsonMarketDataReadinessStore,
    ReadinessStatePersistenceError,
)


def _emit(outcome: str, reason: str, *, provider: str | None = None, ready: int | None = None) -> None:
    parts = [f"readiness outcome={outcome}", f"reason={reason}"]
    if provider is not None: parts.append(f"provider={provider}")
    if ready is not None: parts.append(f"ready={ready}")
    print(" ".join(parts))


def main(argv: list[str] | None = None) -> int:
    settings = RedBarSettings.from_env()
    if not settings.red_bar_v2_market_data_readiness_enabled:
        _emit("DISABLED", "READINESS_DISABLED")
        return 0
    provider = settings.red_bar_v2_market_data_readiness_provider
    if provider == "UNCONFIGURED":
        _emit("CONFIGURATION_INVALID", "MARKET_DATA_PROVIDER_UNCONFIGURED")
        return 2
    if provider == "INVALID":
        _emit("CONFIGURATION_INVALID", "MARKET_DATA_PROVIDER_INVALID")
        return 2
    try:
        market_data = build_paper_canary_market_data(
            settings=settings,
            environment=os.environ,
            provider=provider,
            maximum_quote_age_seconds=settings.red_bar_v2_market_data_readiness_max_quote_age_seconds,
        )
    except PaperMarketDataConfigurationError as exc:
        _emit("CONFIGURATION_INVALID", str(exc))
        return 2
    service = PaperMarketDataReadinessService(
        market_data=market_data,
        policy=MarketDataReadinessPolicy(
            max_quote_age_seconds=settings.red_bar_v2_market_data_readiness_max_quote_age_seconds,
            strike_steps=settings.red_bar_v2_market_data_readiness_strike_steps,
            min_ce_coverage=settings.red_bar_v2_market_data_readiness_min_ce_coverage,
            min_pe_coverage=settings.red_bar_v2_market_data_readiness_min_pe_coverage,
        ),
        clock=SystemClock(),
    )
    report = service.evaluate(underlying=settings.default_underlying)
    try:
        AtomicJsonMarketDataReadinessStore(settings.market_data_readiness_state_path).save(report)
    except ReadinessStatePersistenceError:
        _emit("PERSISTENCE_FAILED", "READINESS_STATE_PERSISTENCE_FAILED", provider=report.provider)
        return 7
    _emit(report.status.value, report.reason_code, provider=report.provider, ready=report.ready_contract_count)
    if report.status in {MarketDataReadinessStatus.READY, MarketDataReadinessStatus.QUOTE_QUALITY_PARTIAL}:
        return 0
    return {
        MarketDataReadinessStatus.CONFIGURATION_INVALID: 2,
        MarketDataReadinessStatus.AUTHENTICATION_FAILED: 3,
        MarketDataReadinessStatus.RATE_LIMITED: 4,
        MarketDataReadinessStatus.PROVIDER_UNAVAILABLE: 5,
        MarketDataReadinessStatus.SPOT_UNAVAILABLE: 5,
        MarketDataReadinessStatus.CHAIN_UNAVAILABLE: 5,
        MarketDataReadinessStatus.QUOTES_UNAVAILABLE: 5,
        MarketDataReadinessStatus.QUOTES_STALE: 5,
        MarketDataReadinessStatus.DATA_CORRUPT: 6,
        MarketDataReadinessStatus.CHAIN_COVERAGE_INCOMPLETE: 6,
    }.get(report.status, 6)


if __name__ == "__main__":
    raise SystemExit(main())
