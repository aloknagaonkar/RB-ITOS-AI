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
from red_bar_lab.services.market_trend_research.policy import StaticExchangeSessionCalendar


def _holidays() -> frozenset[date]:
    values = [value.strip() for value in os.getenv("MARKET_TREND_RESEARCH_HOLIDAYS", "").split(",") if value.strip()]
    return frozenset(date.fromisoformat(value) for value in values)


def main() -> int:
    settings = RedBarSettings.from_env()
    policy = MarketTrendResearchPolicy()
    repository = MarketTrendResearchRepository(settings.database_path)
    service = MarketTrendResearchService(
        source=OptionParticipationSnapshotSource(settings.database_path),
        repository=repository,
        policy=policy,
        calendar=StaticExchangeSessionCalendar(_holidays()),
        calculator=DualPcrCalculator(policy),
    )
    try:
        snapshot = service.evaluate(underlying=settings.default_underlying, evaluated_at=datetime.now().astimezone())
    except ValueError as exc:
        reason = str(exc) if str(exc).isupper() and len(str(exc)) <= 64 else "RESEARCH_EVALUATION_FAILED"
        print(f"market-trend-research outcome=INCOMPLETE reason={reason} authority=OBSERVATIONAL_ONLY")
        return 2
    print(
        "market-trend-research "
        f"outcome={snapshot.quality.state.value} "
        f"current_pcr={snapshot.current_panel.aggregate.pcr} "
        f"morning_pcr={None if snapshot.morning_panel is None else snapshot.morning_panel.aggregate.pcr} "
        "authority=OBSERVATIONAL_ONLY"
    )
    return 0 if snapshot.quality.state.value in {"READY", "MORNING_ANCHOR_UNAVAILABLE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
