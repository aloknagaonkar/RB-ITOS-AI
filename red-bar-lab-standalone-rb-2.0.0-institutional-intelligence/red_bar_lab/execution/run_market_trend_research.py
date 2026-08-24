from __future__ import annotations

from datetime import date, datetime
import os

from red_bar_lab.config import RedBarSettings
from red_bar_lab.services.market_trend_research import (
    DualPcrCalculator,
    MarketTrendResearchPolicy,
    MarketTrendResearchRepository,
    MarketTrendResearchService,
    OptionParticipationSnapshotSource,
)
from red_bar_lab.services.market_trend_research.policy import (
    StaticExchangeSessionCalendar,
)


def _calendar() -> StaticExchangeSessionCalendar:
    verified = os.getenv(
        "MARKET_TREND_RESEARCH_CALENDAR_VERIFIED",
        "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    raw = os.getenv("MARKET_TREND_RESEARCH_HOLIDAYS")
    if not verified:
        return StaticExchangeSessionCalendar(
            holidays=frozenset(),
            source_name="UNVERIFIED_WEEKDAY_ONLY",
            verified=False,
        )
    values = [
        value.strip()
        for value in (raw or "").split(",")
        if value.strip()
    ]
    holidays = frozenset(date.fromisoformat(value) for value in values)
    source_name = (
        "MARKET_TREND_RESEARCH_HOLIDAYS_VERIFIED"
        if holidays
        else "MARKET_TREND_RESEARCH_NO_HOLIDAYS_VERIFIED"
    )
    return StaticExchangeSessionCalendar(
        holidays=holidays,
        source_name=source_name,
        verified=True,
    )


def main() -> int:
    settings = RedBarSettings.from_env()
    policy = MarketTrendResearchPolicy()
    repository = MarketTrendResearchRepository(settings.database_path)
    service = MarketTrendResearchService(
        source=OptionParticipationSnapshotSource(settings.database_path),
        repository=repository,
        policy=policy,
        calendar=_calendar(),
        calculator=DualPcrCalculator(policy),
    )
    try:
        snapshot = service.evaluate(
            underlying=settings.default_underlying,
            evaluated_at=datetime.now().astimezone(),
        )
    except ValueError as exc:
        reason = (
            str(exc)
            if str(exc).isupper() and len(str(exc)) <= 64
            else "RESEARCH_EVALUATION_FAILED"
        )
        print(
            "market-trend-research "
            f"outcome=INCOMPLETE reason={reason} "
            "runtime=ONE_SHOT automatic_refresh=NOT_CONNECTED "
            "authority=OBSERVATIONAL_ONLY"
        )
        return 2
    print(
        "market-trend-research "
        f"outcome={snapshot.quality.state.value} "
        f"current_pcr={snapshot.current_panel.aggregate.pcr} "
        f"morning_pcr={None if snapshot.morning_panel is None else snapshot.morning_panel.aggregate.pcr} "
        f"calendar_source={snapshot.calendar_source} "
        "runtime=ONE_SHOT automatic_refresh=NOT_CONNECTED "
        "authority=OBSERVATIONAL_ONLY"
    )
    return (
        0
        if snapshot.quality.state.value
        in {"READY", "MORNING_ANCHOR_UNAVAILABLE"}
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
