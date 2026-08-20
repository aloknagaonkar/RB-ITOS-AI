from __future__ import annotations

import argparse
import logging
import os
import time

from red_bar_lab.config import RedBarSettings, UNDERLYINGS
from red_bar_lab.execution.attribution_automation import AttributionAwarePaperAutomationService
from red_bar_lab.execution.paper_strategy_authority import PaperStrategyAuthority
from red_bar_lab.execution.underlying_candle_monitoring import assess_monitor_underlying_candles
from red_bar_lab.market.upstox_intelligence import UnifiedUpstoxMarketIntelligenceService
from red_bar_lab.market.paper_adapter import UpstoxPaperMarketAdapter
from red_bar_lab.operations.red_bar_v2_ui_snapshot import read_red_bar_v2_ui_snapshot
from red_bar_lab.services.global_readiness import global_readiness_log_values
from red_bar_lab.services.global_readiness_runtime import build_and_persist_global_readiness
from red_bar_lab.services.nifty_futures_market_data import assess_nifty_futures_market_data, futures_market_log_values
from red_bar_lab.services.nifty_futures_monitoring import NiftyFuturesMonitor, NiftyFuturesMonitorResult, futures_monitor_log_values
from red_bar_lab.services.nifty_futures_positioning_monitor import assess_futures_positioning, futures_positioning_log_values
from red_bar_lab.services.nifty_futures_positioning_strength import assess_nifty_futures_positioning_strength, futures_positioning_strength_log_values
from red_bar_lab.services.nifty_futures_readiness import assess_nifty_futures_readiness, futures_readiness_log_values
from red_bar_lab.services.red_bar_v2_current_session import evaluate_current_session_red_bar_v2
from red_bar_lab.services.red_bar_v2_paper_signal_bridge import publish_v2_snapshot_to_paper_signals
from red_bar_lab.services.red_bar_v2_reversal_exit import execute_confirmed_reversal_exits
from red_bar_lab.services.upstox_instrument_search import UpstoxInstrumentSearchTransport
from red_bar_lab.services.upstox_service import RedBarUpstoxService
from red_bar_lab.storage.database import RedBarDatabase


_OPERATIONAL_WARNING_MESSAGES = frozenset({"Automatic paper entry skipped outside entry market hours."})


def _partition_cycle_messages(report_errors, reversal_errors):
    warnings: list[str] = []
    errors: list[str] = [str(message) for message in reversal_errors]
    for message in report_errors:
        text = str(message)
        if text in _OPERATIONAL_WARNING_MESSAGES:
            warnings.append(text)
        else:
            errors.append(text)
    return errors, warnings


def _candle_diagnostic_log_values(diagnostic):
    readiness = diagnostic.readiness
    volume = diagnostic.volume_authority
    age = readiness.candle_age_seconds
    volume_value = volume.volume
    return (
        readiness.status,
        readiness.reason,
        "NA" if age is None else f"{age:.1f}",
        readiness.latest_timestamp or "NA",
        readiness.expected_completed_timestamp or "NA",
        diagnostic.bridge_alignment,
        diagnostic.fetch_error or "NONE",
        volume.status,
        volume.reason,
        volume.source,
        "NA" if volume_value is None else f"{volume_value:.1f}",
    )


def _parser():
    parser = argparse.ArgumentParser(description="Refresh Red Bar virtual option positions using Upstox market quotes. This process never sends broker orders.")
    parser.add_argument("--interval-seconds", type=int, default=5)
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument("--underlying", choices=("NIFTY 50", "BANK NIFTY"), default="NIFTY 50")
    parser.add_argument("--lots", type=int, default=1)
    parser.add_argument("--minimum-score", type=float, default=65.0)
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.interval_seconds < 2:
        raise SystemExit("Use an interval of at least 2 seconds to stay comfortably within Zerodha quote API rate limits.")
    access_token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not access_token:
        raise SystemExit("UPSTOX_ACCESS_TOKEN is required.")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = RedBarSettings.from_env()
    database = RedBarDatabase(settings.database_path)
    database.initialize()
    authority = PaperStrategyAuthority.from_env()
    authority_ready, authority_reason = authority.validate()
    if not authority_ready:
        raise SystemExit(f"Paper strategy authority is blocked: {authority_reason}")
    database.execution_source_enabled = authority.source_enabled

    upstox = RedBarUpstoxService(access_token)
    futures_monitor = NiftyFuturesMonitor(UpstoxInstrumentSearchTransport(access_token))
    intelligence = UnifiedUpstoxMarketIntelligenceService(upstox, cache_ttl_seconds=2.0)
    adapter = UpstoxPaperMarketAdapter(intelligence, args.underlying, UNDERLYINGS[args.underlying])
    automation = AttributionAwarePaperAutomationService(
        zerodha=adapter,
        database=database,
        settings=settings,
        underlying_name=args.underlying,
        initial_capital=args.capital,
        minimum_candidate_score=args.minimum_score,
    )

    health = upstox.connection_health()
    if not health.get("ok"):
        logging.warning("Upstox connection health check: %s", health.get("message"))
    status = authority.status_payload()
    logging.info(
        "Upstox market-data provider initialized. Execution mode=PAPER; primary_red_bar=%s; v2_paper_authority=%s; legacy_v1=%s; dri=%s; rsi_reversal=%s; live broker orders=%s.",
        status["primary_red_bar_engine"], status["red_bar_v2_paper_authority"], status["legacy_red_bar_v1"], status["dri_strategy"], status["rsi_extreme_reversal"], status["broker_execution"],
    )

    from datetime import datetime
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")
    started_at = datetime.now(ist).isoformat()
    totals = {"signals_seen": 0, "signals_qualified": 0, "candidates_scored": 0, "orders_opened": 0, "orders_closed": 0, "signals_skipped": 0}
    database.upsert_paper_monitor_status({
        "monitor_id": "PAPER-MONITOR", "status": "RUNNING", "heartbeat_at": started_at,
        "last_scan_at": None, "started_at": started_at, "underlying_name": args.underlying,
        **totals, "current_state": "STARTING", "last_signal_id": None,
        "last_decision": "STARTED",
        "last_reason": "Red Bar V2 paper authority enabled; Legacy V1, DRI and RSI Extreme Reversal disabled; broker execution disabled.",
        "last_error": None,
    })

    while True:
        try:
            cycle_started = datetime.now(ist)
            trading_date = cycle_started.date().isoformat()
            live_v2 = evaluate_current_session_red_bar_v2(upstox=upstox, database=database, settings=settings, instrument_key=UNDERLYINGS[args.underlying])
            reversal_exit = execute_confirmed_reversal_exits(
                snapshot=read_red_bar_v2_ui_snapshot(settings.artifacts_root),
                open_orders=database.read_open_paper_execution_orders("PAPER-STD"),
                close_position=lambda order_id, reason: automation.engine.close_position(zerodha=adapter, order_id=order_id, exit_reason=reason),
            )
            if reversal_exit.exited_orders:
                totals["orders_closed"] += int(reversal_exit.exited_orders)
                live_v2 = evaluate_current_session_red_bar_v2(upstox=upstox, database=database, settings=settings, instrument_key=UNDERLYINGS[args.underlying])

            bridge = publish_v2_snapshot_to_paper_signals(
                database_path=settings.database_path,
                artifacts_root=settings.artifacts_root,
                instrument_key=UNDERLYINGS[args.underlying],
                authority=authority,
                now=cycle_started,
            )
            candle_diagnostic = assess_monitor_underlying_candles(upstox, instrument_key=UNDERLYINGS[args.underlying], now=cycle_started, bridge_reason=bridge.reason)
            candle_log_values = _candle_diagnostic_log_values(candle_diagnostic)
            if args.underlying == "NIFTY 50":
                futures_result = futures_monitor.resolve(as_of_date=cycle_started.date())
            else:
                futures_result = NiftyFuturesMonitorResult(status="NOT_APPLICABLE", reason="NIFTY futures discovery is only used for NIFTY 50.")
            futures_log_values = futures_monitor_log_values(futures_result)
            futures_market_result = assess_nifty_futures_market_data(upstox, contract=futures_result, now=cycle_started)
            futures_market_values = futures_market_log_values(futures_market_result)
            futures_positioning_result = assess_futures_positioning(futures_market_result)
            futures_positioning_values = futures_positioning_log_values(futures_positioning_result)
            futures_strength_result = assess_nifty_futures_positioning_strength(futures_positioning_result)
            futures_strength_values = futures_positioning_strength_log_values(futures_strength_result)
            futures_readiness_result = assess_nifty_futures_readiness(
                contract=futures_result,
                market=futures_market_result,
                positioning=futures_positioning_result,
                applicable=args.underlying == "NIFTY 50",
            )
            futures_readiness_values = futures_readiness_log_values(futures_readiness_result)

            report = automation.run_cycle(trading_date=trading_date, lots=max(1, int(args.lots)), monitor_positions=False)
            totals["signals_seen"] += int(report.signals_seen)
            totals["candidates_scored"] += int(report.candidates_scored)
            totals["orders_opened"] += int(report.paper_orders_opened)
            totals["orders_closed"] += int(report.paper_orders_closed)
            totals["signals_skipped"] += int(report.skipped)

            recent_diagnostics = database.read_paper_signal_diagnostics(limit=1)
            latest = recent_diagnostics[0] if recent_diagnostics else {}
            global_readiness_result = build_and_persist_global_readiness(
                database_path=settings.database_path,
                observed_at=cycle_started,
                underlying_name=args.underlying,
                instrument_key=UNDERLYINGS[args.underlying],
                candle_diagnostic=candle_diagnostic,
                futures_readiness=futures_readiness_result,
                futures_strength=futures_strength_result,
                bridge=bridge,
                authority=authority,
                latest_signal_diagnostic=latest,
                report=report,
            )
            global_readiness_values = global_readiness_log_values(global_readiness_result)

            last_decision = latest.get("final_decision") or ("MONITORING" if database.read_open_paper_execution_orders("PAPER-STD") else bridge.status)
            if latest.get("final_decision") == "OPENED":
                totals["signals_qualified"] += 1
            elif latest.get("score_ok") and latest.get("market_hours_ok") and latest.get("duplicate_free"):
                totals["signals_qualified"] += 1

            heartbeat = datetime.now(ist).isoformat()
            current_state = "MONITORING_POSITION" if database.read_open_paper_execution_orders("PAPER-STD") else "WAITING_FOR_V2_SIGNAL"
            cycle_errors, cycle_warnings = _partition_cycle_messages(report.errors, reversal_exit.errors)
            database.upsert_paper_monitor_status({
                "monitor_id": "PAPER-MONITOR", "status": "RUNNING", "heartbeat_at": heartbeat,
                "last_scan_at": heartbeat, "started_at": started_at, "underlying_name": args.underlying,
                **totals, "current_state": current_state,
                "last_signal_id": latest.get("signal_id") or bridge.signal_id,
                "last_decision": last_decision,
                "last_reason": latest.get("reason") or bridge.reason,
                "last_error": " | ".join(cycle_errors[:3]) if cycle_errors else None,
            })

            logging.info(
                "v2_live=%s live_reason=%s reversal_exit=%s reversal_direction=%s reversal_closed=%s v2_bridge=%s bridge_reason=%s underlying_candle=%s candle_reason=%s candle_age_seconds=%s candle_latest=%s candle_expected=%s candle_bridge_alignment=%s candle_fetch_error=%s underlying_volume=%s volume_reason=%s volume_source=%s volume_value=%s nifty_future=%s futures_reason=%s futures_key=%s futures_symbol=%s futures_expiry=%s futures_records=%s futures_error=%s futures_market=%s futures_market_reason=%s futures_candle=%s futures_volume=%s futures_close=%s futures_volume_value=%s futures_oi=%s futures_timestamp=%s futures_candle_count=%s futures_market_error=%s futures_positioning=%s futures_positioning_reason=%s futures_state=%s futures_price_change=%s futures_price_change_pct=%s futures_oi_change=%s futures_oi_change_pct=%s futures_relative_volume=%s futures_baseline_volume=%s futures_baseline_samples=%s futures_strength_status=%s futures_strength_reason=%s futures_strength=%s futures_strength_state=%s futures_strength_price_pct=%s futures_strength_oi_pct=%s futures_strength_rvol=%s futures_readiness=%s futures_readiness_reason=%s futures_contract_status=%s futures_market_status=%s futures_candle_status=%s futures_volume_status=%s futures_oi_status=%s futures_positioning_status=%s futures_positioning_state=%s futures_blocking_reasons=%s futures_advisory_reasons=%s global_readiness=%s global_readiness_reason=%s global_underlying_status=%s global_option_chain_status=%s global_option_quote_status=%s global_pcr_status=%s global_futures_status=%s global_futures_strength=%s global_v2_alignment_status=%s global_execution_source_status=%s global_market_hours_status=%s global_blocking_reasons=%s global_advisory_reasons=%s global_execution_reasons=%s global_authority=%s signals=%s scored=%s opened=%s closed=%s skipped=%s errors=%s warnings=%s decision=%s reason=%s",
                live_v2.status, live_v2.reason, reversal_exit.status, reversal_exit.confirmed_direction,
                reversal_exit.exited_orders, bridge.status, bridge.reason,
                *candle_log_values, *futures_log_values, *futures_market_values,
                *futures_positioning_values, *futures_strength_values, *futures_readiness_values,
                *global_readiness_values,
                report.signals_seen, report.candidates_scored, report.paper_orders_opened,
                report.paper_orders_closed + reversal_exit.exited_orders, report.skipped,
                len(cycle_errors), len(cycle_warnings), last_decision, latest.get("reason") or bridge.reason,
            )
            for warning in cycle_warnings:
                logging.info("paper automation skip: %s", warning)
            for error in cycle_errors:
                logging.warning("paper automation: %s", error)
        except Exception as exc:
            logging.exception("paper automation cycle failed")
            heartbeat = datetime.now(ist).isoformat()
            database.upsert_paper_monitor_status({
                "monitor_id": "PAPER-MONITOR", "status": "ERROR", "heartbeat_at": heartbeat,
                "last_scan_at": heartbeat, "started_at": started_at, "underlying_name": args.underlying,
                **totals, "current_state": "ERROR", "last_signal_id": None,
                "last_decision": "ERROR", "last_reason": "Paper automation cycle failed.",
                "last_error": str(exc)[:500],
            })

        if args.once:
            break
        time.sleep(max(2, args.interval_seconds))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
