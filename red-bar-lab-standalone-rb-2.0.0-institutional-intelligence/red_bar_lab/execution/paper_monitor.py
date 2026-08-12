from __future__ import annotations

import argparse
import logging
import os
import time

from red_bar_lab.config import RedBarSettings, UNDERLYINGS
from red_bar_lab.execution.automation import RedBarPaperAutomationService
from red_bar_lab.market.upstox_intelligence import UnifiedUpstoxMarketIntelligenceService
from red_bar_lab.market.paper_adapter import UpstoxPaperMarketAdapter
from red_bar_lab.services.upstox_service import RedBarUpstoxService
from red_bar_lab.storage.database import RedBarDatabase


def _parser():
    parser = argparse.ArgumentParser(
        description=(
            "Refresh Red Bar virtual option positions using Upstox market "
            "quotes. This process never sends broker orders."
        )
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100000.0,
    )
    parser.add_argument(
        "--underlying",
        choices=("NIFTY 50", "BANK NIFTY"),
        default="NIFTY 50",
    )
    parser.add_argument(
        "--lots",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--minimum-score",
        type=float,
        default=65.0,
    )
    parser.add_argument(
        "--once",
        action="store_true",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.interval_seconds < 2:
        raise SystemExit(
            "Use an interval of at least 2 seconds to stay comfortably "
            "within Zerodha quote API rate limits."
        )

    access_token = os.getenv(
        "UPSTOX_ACCESS_TOKEN", ""
    ).strip()
    if not access_token:
        raise SystemExit(
            "UPSTOX_ACCESS_TOKEN is required."
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

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
        args.underlying,
        UNDERLYINGS[args.underlying],
    )
    automation = RedBarPaperAutomationService(
        zerodha=adapter,
        database=database,
        settings=settings,
        underlying_name=args.underlying,
        initial_capital=args.capital,
        minimum_candidate_score=args.minimum_score,
    )

    health = upstox.connection_health()
    if not health.get("ok"):
        logging.warning(
            "Upstox connection health check: %s",
            health.get("message"),
        )
    logging.info(
        "Upstox market-data provider initialized. "
        "Execution mode=PAPER; live broker orders=DISABLED."
    )

    from datetime import datetime
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")
    started_at = datetime.now(ist).isoformat()
    totals = {
        "signals_seen": 0,
        "signals_qualified": 0,
        "candidates_scored": 0,
        "orders_opened": 0,
        "orders_closed": 0,
        "signals_skipped": 0,
    }
    database.upsert_paper_monitor_status(
        {
            "monitor_id": "PAPER-MONITOR",
            "status": "RUNNING",
            "heartbeat_at": started_at,
            "last_scan_at": None,
            "started_at": started_at,
            "underlying_name": args.underlying,
            **totals,
            "current_state": "STARTING",
            "last_signal_id": None,
            "last_decision": "STARTED",
            "last_reason": "Paper monitor initialized.",
            "last_error": None,
        }
    )

    while True:
        try:
            cycle_started = datetime.now(ist)
            trading_date = cycle_started.date().isoformat()
            report = automation.run_cycle(
                trading_date=trading_date,
                lots=max(1, int(args.lots)),
            )

            totals["signals_seen"] += int(report.signals_seen)
            totals["candidates_scored"] += int(
                report.candidates_scored
            )
            totals["orders_opened"] += int(
                report.paper_orders_opened
            )
            totals["orders_closed"] += int(
                report.paper_orders_closed
            )
            totals["signals_skipped"] += int(report.skipped)

            recent_diagnostics = (
                database.read_paper_signal_diagnostics(limit=1)
            )
            latest = recent_diagnostics[0] if recent_diagnostics else {}
            last_decision = (
                latest.get("final_decision")
                or (
                    "MONITORING"
                    if database.read_open_paper_execution_orders(
                        "PAPER-STD"
                    )
                    else "WAITING"
                )
            )
            if latest.get("final_decision") == "OPENED":
                totals["signals_qualified"] += 1
            elif (
                latest.get("score_ok")
                and latest.get("market_hours_ok")
                and latest.get("duplicate_free")
            ):
                totals["signals_qualified"] += 1

            heartbeat = datetime.now(ist).isoformat()
            current_state = (
                "MONITORING_POSITION"
                if database.read_open_paper_execution_orders(
                    "PAPER-STD"
                )
                else "WAITING_FOR_SIGNAL"
            )
            database.upsert_paper_monitor_status(
                {
                    "monitor_id": "PAPER-MONITOR",
                    "status": "RUNNING",
                    "heartbeat_at": heartbeat,
                    "last_scan_at": heartbeat,
                    "started_at": started_at,
                    "underlying_name": args.underlying,
                    **totals,
                    "current_state": current_state,
                    "last_signal_id": latest.get("signal_id"),
                    "last_decision": last_decision,
                    "last_reason": latest.get("reason"),
                    "last_error": (
                        " | ".join(report.errors[:3])
                        if report.errors else None
                    ),
                }
            )

            logging.info(
                "paper automation signals=%s scored=%s opened=%s "
                "closed=%s skipped=%s errors=%s decision=%s reason=%s",
                report.signals_seen,
                report.candidates_scored,
                report.paper_orders_opened,
                report.paper_orders_closed,
                report.skipped,
                len(report.errors),
                last_decision,
                latest.get("reason"),
            )
            for error in report.errors:
                logging.warning("paper automation: %s", error)
        except Exception as exc:
            logging.exception("paper automation cycle failed")
            heartbeat = datetime.now(ist).isoformat()
            database.upsert_paper_monitor_status(
                {
                    "monitor_id": "PAPER-MONITOR",
                    "status": "ERROR",
                    "heartbeat_at": heartbeat,
                    "last_scan_at": heartbeat,
                    "started_at": started_at,
                    "underlying_name": args.underlying,
                    **totals,
                    "current_state": "ERROR",
                    "last_signal_id": None,
                    "last_decision": "ERROR",
                    "last_reason": "Paper automation cycle failed.",
                    "last_error": str(exc)[:500],
                }
            )

        if args.once:
            break
        time.sleep(max(2, args.interval_seconds))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
