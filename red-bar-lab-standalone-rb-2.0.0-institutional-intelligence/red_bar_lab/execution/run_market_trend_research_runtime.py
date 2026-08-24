from __future__ import annotations

from datetime import datetime, time, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import signal

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
from red_bar_lab.services.red_bar_v2_canonical.upstox_paper_market_data import UpstoxPaperCanaryMarketData
from red_bar_lab.services.upstox_service import RedBarUpstoxService, resolve_access_token

AUTHORITY = "OBSERVATIONAL_ONLY"


class _UnderlyingSpotAdapter:
    def __init__(self, market: UpstoxPaperCanaryMarketData) -> None:
        self.market = market

    def spot(self, *, underlying: str, evaluated_at: datetime) -> tuple[float, datetime]:
        quote = self.market.underlying_quote(
            underlying=underlying,
            evaluated_at=evaluated_at,
        )
        return quote.last_price, quote.quote_timestamp


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


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
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
        return time(hour, minute, second)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}_INVALID") from exc


def _safe_reason(value: object) -> str:
    text = str(value).strip().upper()
    if text and len(text) <= 64 and all(
        character.isalnum() or character in "_-" for character in text
    ):
        return text
    return type(value).__name__.upper()[:64]


def _worker_logger(settings: RedBarSettings) -> logging.Logger:
    log_path = settings.artifacts_root / "market_trend_research" / "logs" / "worker.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("market_trend_research_worker")
    for handler in tuple(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def _log(logger: logging.Logger, event: str, **fields: object) -> None:
    logger.info(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "authority": AUTHORITY,
        **fields,
    }, sort_keys=True))


def build_runtime() -> tuple[MarketTrendResearchRuntime, int]:
    settings = RedBarSettings.from_env()
    calendar = verified_calendar()
    unattended = _bool("MARKET_TREND_RESEARCH_UNATTENDED", False)
    if unattended and not calendar.verified:
        raise ValueError("CALENDAR_UNVERIFIED")
    policy = MarketTrendResearchPolicy(
        maximum_source_age_seconds=_float("MARKET_TREND_RESEARCH_MAX_SOURCE_AGE_SECONDS", 30.0),
        hard_deadline_seconds=_float("MARKET_TREND_RESEARCH_HARD_DEADLINE_SECONDS", 2.0),
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
    token = resolve_access_token()
    client = UpstoxClient(token, timeout=request_timeout)
    provider = RedBarUpstoxService(token, client_factory=lambda _token: client)
    spot_market = UpstoxPaperCanaryMarketData(
        client,
        underlying_keys={settings.default_underlying: "NSE_INDEX|Nifty 50"},
        maximum_quote_age_seconds=policy.maximum_source_age_seconds,
    )
    collector = UpstoxResearchChainCollector(
        provider=provider,
        repository=repository,
        policy=policy,
        calendar=calendar,
        underlying=settings.default_underlying,
        instrument_key="NSE_INDEX|Nifty 50",
        spot_provider=_UnderlyingSpotAdapter(spot_market),
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
            maximum_backoff_seconds=_float("MARKET_TREND_RESEARCH_MAX_BACKOFF_SECONDS", 60.0),
            maximum_consecutive_failures=_int("MARKET_TREND_RESEARCH_MAX_CONSECUTIVE_FAILURES", 5),
            failure_cooldown_seconds=_float("MARKET_TREND_RESEARCH_FAILURE_COOLDOWN_SECONDS", 60.0),
            session_start=_clock("MARKET_TREND_RESEARCH_SESSION_START", "09:08:00"),
            session_end=_clock("MARKET_TREND_RESEARCH_SESSION_END", "15:30:00"),
            unattended=unattended,
        ),
    )
    return runtime, request_timeout


def _install_signal_handlers(runtime: MarketTrendResearchRuntime) -> None:
    """Route supported process-stop signals through the runtime stop event."""

    def _stop(_signum, _frame) -> None:
        runtime.stop()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _stop)


def main() -> int:
    settings = RedBarSettings.from_env()
    logger = _worker_logger(settings)
    if not _bool("MARKET_TREND_RESEARCH_RUNTIME_ENABLED", False):
        _log(logger, "RUNTIME_DISABLED", safe_reason="MARKET_TREND_RESEARCH_RUNTIME_DISABLED")
        print(f"market-trend-research-runtime outcome=DISABLED authority={AUTHORITY}")
        return 2
    try:
        runtime, request_timeout = build_runtime()
    except Exception as exc:
        reason = _safe_reason(exc)
        _log(logger, "RUNTIME_CONFIGURATION_ERROR", safe_reason=reason)
        print(
            "market-trend-research-runtime outcome=CONFIGURATION_ERROR "
            f"reason={reason} authority={AUTHORITY}"
        )
        return 2

    _install_signal_handlers(runtime)
    _log(
        logger,
        "RUNTIME_STARTED",
        cadence_seconds=runtime.config.refresh_seconds,
        provider="UPSTOX",
        request_timeout_seconds=request_timeout,
    )
    print(
        "market-trend-research-runtime outcome=STARTED cadence_seconds="
        f"{runtime.config.refresh_seconds} provider=UPSTOX "
        f"request_timeout_seconds={request_timeout} authority={AUTHORITY}"
    )
    try:
        runtime.run_forever()
    except KeyboardInterrupt:
        runtime.stop()
    finally:
        _log(logger, "RUNTIME_STOPPED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
