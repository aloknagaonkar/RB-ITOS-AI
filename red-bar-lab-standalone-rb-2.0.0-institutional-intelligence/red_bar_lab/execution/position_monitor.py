from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from red_bar_lab.config import RedBarSettings, UNDERLYINGS
from red_bar_lab.execution.attribution_automation import (
    AttributionAwarePaperAutomationService,
)
from red_bar_lab.execution.paper_strategy_authority import PaperStrategyAuthority
from red_bar_lab.market.paper_adapter import UpstoxPaperMarketAdapter
from red_bar_lab.market.upstox_intelligence import (
    UnifiedUpstoxMarketIntelligenceService,
)
from red_bar_lab.services.upstox_service import RedBarUpstoxService
from red_bar_lab.storage.database import RedBarDatabase


IST = ZoneInfo("Asia/Kolkata")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fast paper-position price, protection and exit monitor. "
            "This process never scans strategies or sends broker orders."
        )
    )
    parser.add_argument("--interval-seconds", type=int, default=5)
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument(
        "--underlying",
        choices=("NIFTY 50", "BANK NIFTY"),
        default="NIFTY 50",
    )
    parser.add_argument("--minimum-score", type=float, default=65.0)
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()

    if args.interval_seconds < 2:
        raise SystemExit("Use an interval of at least 2 seconds.")

    access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not access_token:
        raise SystemExit("UPSTOX_ACCESS_TOKEN is required.")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    settings = RedBarSettings.from_env()
    database = RedBarDatabase(settings.database_path)
    database.initialize()

    authority = PaperStrategyAuthority.from_env()
    authority_ready, authority_reason = authority.validate()
    if not authority_ready:
        raise SystemExit(
            f"Paper strategy authority is blocked: {authority_reason}"
        )

    database.execution_source_enabled = authority.source_enabled

    upstox = RedBarUpstoxService(access_token)
    intelligence = UnifiedUpstoxMarketIntelligenceService(
        upstox,
        cache_ttl_seconds=2.0,
    )
    adapter = UpstoxPaperMarketAdapter(
        intelligence,
        args.underlying,
        UNDERLYINGS[args.underlying],
    )

    automation = AttributionAwarePaperAutomationService(
        zerodha=adapter,
        database=database,
        settings=settings,
        underlying_name=args.underlying,
        initial_capital=args.capital,
        minimum_candidate_score=args.minimum_score,
    )

    logging.info(
        "Fast paper-position monitor started. "
        "Underlying=%s interval=%ss mode=PAPER_ONLY",
        args.underlying,
        args.interval_seconds,
    )

    while True:
        cycle_started = time.perf_counter()

        try:
            open_before = database.read_open_paper_execution_orders("PAPER-STD")

            if open_before:
                closed, errors = automation.monitor_and_exit()
                open_after = database.read_open_paper_execution_orders("PAPER-STD")
            else:
                closed, errors = 0, []
                open_after = []

            elapsed_ms = (time.perf_counter() - cycle_started) * 1000.0

            logging.info(
                "position_cycle=%s open_before=%s open_after=%s "
                "closed=%s errors=%s duration_ms=%.1f",
                datetime.now(IST).isoformat(),
                len(open_before),
                len(open_after),
                closed,
                len(errors),
                elapsed_ms,
            )

            for error in errors:
                logging.warning("position monitor: %s", error)

        except Exception:
            logging.exception("Fast position-monitor cycle failed")

        if args.once:
            break

        elapsed = time.perf_counter() - cycle_started
        delay = max(
            0.25,
            float(args.interval_seconds) - elapsed,
        )
        time.sleep(delay)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
