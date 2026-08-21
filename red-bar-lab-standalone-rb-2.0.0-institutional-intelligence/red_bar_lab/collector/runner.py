from __future__ import annotations

import argparse
import logging
import time as time_module
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from red_bar_lab.collector.service import (
    RedBarDualMarketCollector,
    market_session_phase,
)
from red_bar_lab.config import RedBarSettings, UNDERLYINGS
from red_bar_lab.execution.live_reference_worker import run_cycle
from red_bar_lab.pipeline.orchestrator import RedBarIntelligencePipelineOrchestrator
from red_bar_lab.services.historical_service import RedBarHistoricalService
from red_bar_lab.services.live_service import RedBarLiveService
from red_bar_lab.services.upstox_service import (
    RedBarUpstoxService,
    resolve_access_token,
)
from red_bar_lab.storage.artifacts import ArtifactLayout
from red_bar_lab.storage.database import RedBarDatabase

IST = ZoneInfo("Asia/Kolkata")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Red Bar dual options collector. Online mode stores option-chain "
            "snapshots, refreshes current-session NIFTY candles/reference levels, "
            "and synchronizes intelligence every interval."
        )
    )
    parser.add_argument(
        "--underlying",
        default="NIFTY 50",
        choices=tuple(UNDERLYINGS),
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=60,
    )
    parser.add_argument(
        "--expiry",
        default="",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one tick and exit.",
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "online", "offline"),
        default="auto",
    )
    parser.add_argument(
        "--skip-live-reference-refresh",
        action="store_true",
        help=(
            "Do not refresh current-session NIFTY candles/reference levels from "
            "the collector. Intended only when a separate live-reference worker "
            "is deliberately managed."
        ),
    )
    return parser


def _refresh_live_reference(
    service: RedBarLiveService,
    *,
    settings: RedBarSettings,
    instrument_key: str,
    underlying_name: str,
    now: datetime,
):
    """Refresh underlying candles/levels without interrupting option collection."""

    status_path = Path(settings.database_path).parent / "live_reference_worker_status.json"
    return run_cycle(
        service,
        instrument_key=instrument_key,
        underlying_name=underlying_name,
        status_path=status_path,
        now=now,
        force=True,
    )


def main() -> int:
    args = _parser().parse_args()
    if args.interval_seconds < 60:
        raise SystemExit("Minimum collector interval is 60 seconds.")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    settings = RedBarSettings.from_env()
    database = RedBarDatabase(settings.database_path)
    database.initialize()

    token = resolve_access_token("")
    provider = RedBarUpstoxService(token)
    collector = RedBarDualMarketCollector(
        provider,
        database,
        settings,
    )
    layout = ArtifactLayout(settings)
    layout.ensure()

    live_historical = RedBarHistoricalService(provider, layout)
    live_reference_service = RedBarLiveService(
        live_historical,
        layout,
        database,
    )

    historical_cache = RedBarHistoricalService(
        RedBarUpstoxService("cache-only"),
        layout,
    )
    orchestrator = RedBarIntelligencePipelineOrchestrator(
        historical=historical_cache,
        database=database,
        settings=settings,
        options_collector=collector,
    )
    instrument_key = UNDERLYINGS[args.underlying]
    expiry = args.expiry.strip() or None

    offline_done_for_date: set[str] = set()

    while True:
        now = datetime.now(IST)
        mode = args.mode
        if mode == "auto":
            phase = market_session_phase(now)
            if phase == "OPEN":
                mode = "online"
            elif phase == "POSTCLOSE":
                mode = "offline"
            else:
                mode = "waiting"
        else:
            phase = market_session_phase(now)

        try:
            if mode == "waiting":
                logging.info(
                    "collector waiting phase=%s; no market/EOD request made",
                    phase,
                )
                database.update_collector_status(
                    "DUAL_OPTIONS",
                    "WAITING",
                    "WAITING",
                    f"Market phase: {phase}",
                    None,
                )
            elif mode == "online":
                if not args.skip_live_reference_refresh:
                    _refresh_live_reference(
                        live_reference_service,
                        settings=settings,
                        instrument_key=instrument_key,
                        underlying_name=args.underlying,
                        now=now,
                    )

                report = collector.online_tick(
                    instrument_key=instrument_key,
                    expiry=expiry,
                    now=now,
                )
                logging.info(
                    "collector mode=%s status=%s snapshot_id=%s "
                    "linked=%s message=%s",
                    report.mode,
                    report.status,
                    report.snapshot_id,
                    report.signals_linked,
                    report.message,
                )
                pipeline_report = orchestrator.sync_day(
                    instrument_key=instrument_key,
                    trading_date=now.date().isoformat(),
                    link_window_seconds=120,
                )
                logging.info(
                    "pipeline confirmed=%s core=%s hybrid=%s errors=%s",
                    pipeline_report.confirmed_signals,
                    pipeline_report.core_eligible,
                    pipeline_report.hybrid_eligible,
                    len(pipeline_report.errors),
                )
            else:
                today = now.date().isoformat()
                online_history = database.read_option_chain_history(
                    instrument_key,
                    today,
                    today,
                    limit=10,
                )
                has_online_today = any(
                    row.get("collector_mode") == "ONLINE"
                    for row in online_history
                )
                auto_eod_allowed = args.mode != "auto" or has_online_today
                if not auto_eod_allowed:
                    logging.info(
                        "EOD capture skipped: no ONLINE snapshots exist "
                        "for %s (holiday/no-session protection)",
                        today,
                    )
                    database.update_collector_status(
                        "DUAL_OPTIONS",
                        "WAITING",
                        "WAITING",
                        "No online session detected for EOD capture.",
                        None,
                    )
                elif args.once or today not in offline_done_for_date:
                    report = collector.offline_eod_tick(
                        instrument_key=instrument_key,
                        expiry=expiry,
                        trading_date=today,
                        now=now,
                    )
                    offline_done_for_date.add(today)
                    logging.info(
                        "collector mode=%s status=%s snapshot_id=%s "
                        "message=%s",
                        report.mode,
                        report.status,
                        report.snapshot_id,
                        report.message,
                    )
                    orchestrator.sync_day(
                        instrument_key=instrument_key,
                        trading_date=today,
                        link_window_seconds=120,
                    )
                    validation = orchestrator.validate_eod(
                        instrument_key=instrument_key,
                        trading_date=today,
                    )
                    logging.info(
                        "EOD validation status=%s core=%.1f%% hybrid=%.1f%%",
                        validation["status"],
                        validation["core_completeness_pct"],
                        validation["hybrid_completeness_pct"],
                    )
                else:
                    logging.info(
                        "offline EOD snapshot already attempted for %s",
                        today,
                    )
        except Exception as exc:
            logging.exception("collector tick failed: %s", exc)
            database.update_collector_status(
                "DUAL_OPTIONS",
                mode.upper(),
                "ERROR",
                str(exc)[:500],
                None,
            )

        if args.once:
            break

        time_module.sleep(max(60, args.interval_seconds))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["_refresh_live_reference", "main"]
