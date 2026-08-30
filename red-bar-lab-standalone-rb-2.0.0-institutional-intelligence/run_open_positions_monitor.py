from __future__ import annotations

import logging
import os
import time

from red_bar_lab.config import RedBarSettings, UNDERLYINGS
from red_bar_lab.execution.attribution_automation import (
    AttributionAwarePaperAutomationService,
)
from red_bar_lab.market.paper_adapter import UpstoxPaperMarketAdapter
from red_bar_lab.market.upstox_intelligence import (
    UnifiedUpstoxMarketIntelligenceService,
)
from red_bar_lab.services.upstox_service import RedBarUpstoxService
from red_bar_lab.storage.database import RedBarDatabase


INTERVAL_SECONDS = 5
UNDERLYING = "NIFTY 50"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not access_token:
        raise SystemExit("UPSTOX_ACCESS_TOKEN is required.")

    settings = RedBarSettings.from_env()
    database = RedBarDatabase(settings.database_path)
    database.initialize()

    upstox = RedBarUpstoxService(access_token)
    intelligence = UnifiedUpstoxMarketIntelligenceService(
        upstox,
        cache_ttl_seconds=2.0,
    )
    adapter = UpstoxPaperMarketAdapter(
        intelligence,
        UNDERLYING,
        UNDERLYINGS[UNDERLYING],
    )

    automation = AttributionAwarePaperAutomationService(
        zerodha=adapter,
        database=database,
        settings=settings,
        underlying_name=UNDERLYING,
        initial_capital=100000.0,
        minimum_candidate_score=65.0,
    )

    logging.info(
        "Dedicated open-position monitor started; interval=%ss",
        INTERVAL_SECONDS,
    )

    while True:
        started = time.monotonic()

        try:
            closed, errors = automation.monitor_and_exit()

            open_orders = database.read_open_paper_execution_orders(
                "PAPER-STD"
            )

            logging.info(
                "position refresh complete: open=%s closed=%s errors=%s",
                len(open_orders),
                closed,
                len(errors),
            )

            for error in errors:
                logging.warning("position monitor: %s", error)

        except Exception:
            logging.exception("position refresh failed")

        elapsed = time.monotonic() - started
        time.sleep(max(1.0, INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    raise SystemExit(main())
