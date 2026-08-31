from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from red_bar_lab.config import RedBarSettings, UNDERLYINGS
from red_bar_lab.execution.attribution_automation import AttributionAwarePaperAutomationService
from red_bar_lab.execution.paper_monitor_circuit import (
    PaperMonitorCircuitBreaker,
    critical_market_data_failure,
)
from red_bar_lab.execution.paper_strategy_authority import PaperStrategyAuthority
from red_bar_lab.execution.underlying_candle_monitoring import assess_monitor_underlying_candles
from red_bar_lab.market.paper_adapter import UpstoxPaperMarketAdapter
from red_bar_lab.market.upstox_intelligence import UnifiedUpstoxMarketIntelligenceService
from red_bar_lab.observability.cleanup import maybe_cleanup_process_evidence
from red_bar_lab.observability.evidence import generate_run_id
from red_bar_lab.operations.red_bar_v2_ui_snapshot import read_red_bar_v2_ui_snapshot
from red_bar_lab.services.global_readiness import global_readiness_log_values
from red_bar_lab.services.global_readiness_runtime import build_and_persist_global_readiness
from red_bar_lab.services.nifty_futures_market_data import (
    assess_nifty_futures_market_data,
    futures_market_log_values,
)
from red_bar_lab.services.nifty_futures_monitoring import (
    NiftyFuturesMonitor,
    NiftyFuturesMonitorResult,
    futures_monitor_log_values,
)
from red_bar_lab.services.nifty_futures_positioning_monitor import (
    assess_futures_positioning,
    futures_positioning_log_values,
)
from red_bar_lab.services.nifty_futures_positioning_strength import (
    assess_nifty_futures_positioning_strength,
    futures_positioning_strength_log_values,
)
from red_bar_lab.services.nifty_futures_readiness import (
    assess_nifty_futures_readiness,
    futures_readiness_log_values,
)
from red_bar_lab.services.red_bar_v2_current_session import evaluate_current_session_red_bar_v2
from red_bar_lab.services.red_bar_v2_contract_selection_evidence import (
    persist_contract_selection_evidence,
)
from red_bar_lab.services.red_bar_v2_market_data_evidence import (
    persist_market_data_evidence,
    persist_stage_latency,
)
from red_bar_lab.services.red_bar_v2_paper_signal_bridge import (
    RedBarV2PaperSignalPublishResult,
    publish_v2_snapshot_to_paper_signals,
)
from red_bar_lab.services.red_bar_v2_rsi_exit import execute_rsi_threshold_exits
from red_bar_lab.services.red_bar_v2_structural_exit import execute_structural_stop_exits
from red_bar_lab.services.upstox_instrument_search import UpstoxInstrumentSearchTransport
from red_bar_lab.services.upstox_service import RedBarUpstoxService
from red_bar_lab.storage.database import RedBarDatabase


_OPERATIONAL_WARNING_MESSAGES = frozenset(
    {"Automatic paper entry skipped outside entry market hours."}
)

_IST = ZoneInfo("Asia/Kolkata")

# A diagnostic row older than this no longer describes the current cycle:
# when no new signals arrive, the newest row can be hours old (e.g. a
# pre-open admission block) and echoing it misrepresents the monitor state.
_STALE_DIAGNOSTIC_MAX_AGE_SECONDS = 900


def _diagnostic_recorded_recently(
    latest: Any,
    *,
    now: datetime,
    max_age_seconds: int = _STALE_DIAGNOSTIC_MAX_AGE_SECONDS,
) -> bool:
    """True when the row's timestamp is within the window; unparseable fails open."""
    raw = None
    if isinstance(latest, dict):
        raw = latest.get("timestamp")
    if not raw:
        return True
    try:
        stamp = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_IST)
    reference = now if now.tzinfo is not None else now.replace(tzinfo=_IST)
    return (reference - stamp).total_seconds() <= float(max_age_seconds)


def _persist_latency_snapshot(
    artifacts_root: Path,
    *,
    cycle_started_at: str,
    cycle_completed_at: str,
    timings_ms: dict[str, float],
    slowest_stage: str,
) -> None:
    """Publish bounded post-cycle timing evidence without affecting execution."""
    target = artifacts_root / "paper_monitor_latency.json"
    temporary = target.with_suffix(".tmp")
    payload = {
        "schema_version": "RED_BAR_V2_MONITOR_LATENCY_V1",
        "cycle_started_at": cycle_started_at,
        "cycle_completed_at": cycle_completed_at,
        "slowest_stage": slowest_stage,
        "timings_ms": {key: round(value, 3) for key, value in timings_ms.items()},
    }
    try:
        artifacts_root.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(target)
    except OSError:
        logging.warning("paper_monitor_latency_persistence_failed", exc_info=True)


def _legacy_stage_latency_rows(cycle_timings_ms, report, live_v2):
    automation = dict(getattr(report, "stage_timings_ms", ()) or ())
    pull_ms = sum(item.duration_ms for item in live_v2.market_data_evidence)
    strategy_ms = max(0.0, cycle_timings_ms["v2_evaluation"] - pull_ms)

    def row(stage_id, status, duration_ms, detail):
        return {
            "stage_id": stage_id,
            "status": status,
            "duration_ms": (
                round(float(duration_ms), 3) if duration_ms is not None else None
            ),
            "detail": detail,
        }

    return [
        row("INPUT_READINESS", "MEASURED", pull_ms, "Existing index and futures candle pulls"),
        row("STRATEGY_DECISION", "MEASURED", strategy_ms, "V2 evaluation excluding measured provider pull time"),
        row("SIGNAL_BUNDLE", "MEASURED", cycle_timings_ms["signal_publication"], "Legacy signal publication bridge"),
        row("ARCHITECTURE_PARITY", "NOT_APPLICABLE", None, "Canonical shadow owns parity"),
        row("PERSISTENCE_INTEGRITY", "COUPLED", None, "Included in signal publication persistence"),
        row("RECENT_OBSERVATIONS", "MEASURED", cycle_timings_ms["global_readiness"], "Post-decision readiness projection"),
        row("PROCESS_EXPLANATION", "UI_ONLY", None, "Read-only UI projection"),
        row("OPPORTUNITY_QUEUE", "MEASURED", automation.get("opportunity_queue"), "Candidate scoring, committee and queue decision"),
        row("RESERVATION_BOUNDARY", "COUPLED", None, "Legacy duplicate and entry-cap checks occur inside queue processing"),
        row("PAPER_EXECUTION", "MEASURED", automation.get("paper_execution"), "Approved queue consumption and paper order creation"),
        row("RUNTIME_HEALTH", "MEASURED", cycle_timings_ms["total"], "Complete paper-monitor cycle"),
        row("PROVIDER_READINESS", "MEASURED", cycle_timings_ms["readiness"], "Underlying and futures readiness assessment"),
    ]


def _partition_cycle_messages(report_errors, exit_errors):
    warnings: list[str] = []
    errors: list[str] = [str(message) for message in exit_errors]
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
    return (
        readiness.status,
        readiness.reason,
        "NA" if readiness.candle_age_seconds is None else f"{readiness.candle_age_seconds:.1f}",
        readiness.latest_timestamp or "NA",
        readiness.expected_completed_timestamp or "NA",
        diagnostic.bridge_alignment,
        diagnostic.fetch_error or "NONE",
        volume.status,
        volume.reason,
        volume.source,
        "NA" if volume.volume is None else f"{volume.volume:.1f}",
    )


def _suspended_report(reason: str):
    """Return a report-shaped value without running entry automation."""
    return SimpleNamespace(
        signals_seen=0,
        candidates_scored=0,
        paper_orders_opened=0,
        paper_orders_closed=0,
        skipped=1,
        errors=(reason,),
    )


def _record_paper_cycle_stage_evidence(
    database: Any,
    *,
    run_id: str,
    cycle_timings_ms: dict[str, float],
) -> None:
    """Write one ``process_evidence`` row per non-total stage key.

    Best-effort: any DB error here is swallowed because the cycle
    itself has already succeeded. We don't want evidence-writing to
    mask a healthy run.
    """
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    for stage_name, duration_ms in sorted(cycle_timings_ms.items()):
        if stage_name == "total":
            continue
        if not isinstance(duration_ms, (int, float)):
            continue
        try:
            step_id = database.write_step_evidence(
                process_name="paper_monitor",
                run_id=run_id,
                step_name=f"stage:{stage_name}",
                parent_step="paper_cycle",
                started_at=now_iso,
                status="OK",
                artifacts={"duration_ms": float(duration_ms)},
            )
            database.update_step_evidence(
                step_id=step_id,
                completed_at=now_iso,
                status="OK",
                duration_ms=float(duration_ms),
            )
        except Exception:  # noqa: BLE001
            # Best-effort: if the DB is unavailable, the cycle still
            # succeeded and we don't want to raise.
            continue


def _read_recent_collector_run_id(
    database: Any, *, max_age_seconds: float = 60.0
) -> str | None:
    """Return the most-recent market_collector run_id, if it's recent
    enough that the paper cycle is plausibly part of the same logical
    cycle. Used to correlate the paper cycle's evidence with the
    upstream collector tick."""
    try:
        row = database.read_process_run_correlation(
            process_name="market_collector"
        )
    except Exception:  # noqa: BLE001
        return None
    if not row:
        return None
    started_at = row.get("started_at")
    if not isinstance(started_at, str):
        return None
    try:
        from datetime import datetime, timezone

        parsed = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - parsed).total_seconds()
    except (TypeError, ValueError):
        return None
    if age > max_age_seconds:
        return None
    return str(row.get("run_id") or "") or None


def _write_paper_correlation(
    database: Any,
    *,
    cycle_run_id: str,
    correlated_collector_run_id: str | None,
    trading_date: str,
) -> None:
    """Best-effort: record the paper monitor's most-recent run_id so
    the UI can correlate. The ``correlated_collector_run_id`` artifact
    is what makes the cross-process link."""
    from datetime import datetime, timezone

    try:
        database.write_process_run_correlation(
            process_name="paper_monitor",
            run_id=cycle_run_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            artifacts={
                "trading_date": trading_date,
                "correlated_collector_run_id": correlated_collector_run_id,
            },
        )
    except Exception:  # noqa: BLE001
        pass


def _parser():
    parser = argparse.ArgumentParser(
        description=(
            "Refresh Red Bar virtual option positions using Upstox market quotes. "
            "This process never sends broker orders."
        )
    )
    parser.add_argument("--interval-seconds", type=int, default=5)
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument(
        "--underlying",
        choices=("NIFTY 50", "BANK NIFTY"),
        default="NIFTY 50",
    )
    parser.add_argument("--lots", type=int, default=1)
    parser.add_argument("--minimum-score", type=float, default=65.0)
    parser.add_argument("--failure-threshold", type=int, default=3)
    parser.add_argument("--maximum-backoff-seconds", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.interval_seconds < 2:
        raise SystemExit(
            "Use an interval of at least 2 seconds to stay comfortably within "
            "Upstox quote API rate limits."
        )
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
        raise SystemExit(f"Paper strategy authority is blocked: {authority_reason}")
    database.execution_source_enabled = authority.source_enabled

    upstox = RedBarUpstoxService(access_token)
    futures_monitor = NiftyFuturesMonitor(UpstoxInstrumentSearchTransport(access_token))
    intelligence = UnifiedUpstoxMarketIntelligenceService(upstox, cache_ttl_seconds=2.0)
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
        enable_opportunity_extension=False,
    )
    circuit = PaperMonitorCircuitBreaker(
        failure_threshold=args.failure_threshold,
        base_delay_seconds=max(2, args.interval_seconds),
        maximum_delay_seconds=args.maximum_backoff_seconds,
        state_path=settings.artifacts_root / "paper_monitor_circuit.json",
    )

    health = upstox.connection_health()
    if not health.get("ok"):
        logging.warning("Upstox connection health check: %s", health.get("message"))
    status = authority.status_payload()
    logging.info(
        "Upstox market-data provider initialized. Execution mode=PAPER; "
        "primary_red_bar=%s; v2_paper_authority=%s; legacy_v1=%s; dri=%s; "
        "rsi_reversal=%s; live broker orders=%s.",
        status["primary_red_bar_engine"],
        status["red_bar_v2_paper_authority"],
        status["legacy_red_bar_v1"],
        status["dri_strategy"],
        status["rsi_extreme_reversal"],
        status["broker_execution"],
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
            "last_reason": (
                "Red Bar V2 paper authority enabled; Legacy V1, DRI and RSI "
                "Extreme Reversal disabled; broker execution disabled."
            ),
            "last_error": None,
        }
    )

    next_delay = max(2, args.interval_seconds)
    while True:
        cycle_gate = circuit.begin_cycle()
        try:
            cycle_perf_started = perf_counter()
            stage_perf_started = cycle_perf_started
            cycle_timings_ms: dict[str, float] = {}
            cycle_started = datetime.now(ist)
            trading_date = cycle_started.date().isoformat()
            cycle_run_id = generate_run_id("paper_monitor")
            # Best-effort: keep the process_evidence table from growing
            # unbounded. Self-throttles to once per day.
            maybe_cleanup_process_evidence(database)
            # Cross-process correlation: link this paper cycle to the
            # most-recent market_collector run, if it's recent enough
            # that the two are plausibly part of the same logical cycle.
            correlated_collector_run_id = _read_recent_collector_run_id(
                database, max_age_seconds=60.0
            )
            # Per-stage evidence is written at the end of the happy path
            # via _record_paper_cycle_stage_evidence. The paper_cycle
            # step is wrapped separately if/when the cycle body is
            # extracted — for now we don't wrap the whole cycle in a
            # single with-block because that would require re-indenting
            # ~200 lines.
            _write_paper_correlation(
                database,
                cycle_run_id=cycle_run_id,
                correlated_collector_run_id=correlated_collector_run_id,
                trading_date=trading_date,
            )
            futures_applicable = args.underlying == "NIFTY 50"
            if futures_applicable:
                futures_result = futures_monitor.resolve(as_of_date=cycle_started.date())
            else:
                futures_result = NiftyFuturesMonitorResult(
                    status="NOT_APPLICABLE",
                    reason="NIFTY futures discovery is only used for NIFTY 50.",
                )
            cycle_timings_ms["futures_resolution"] = (
                perf_counter() - stage_perf_started
            ) * 1000.0
            stage_perf_started = perf_counter()
            live_v2 = evaluate_current_session_red_bar_v2(
                upstox=upstox,
                database=database,
                settings=settings,
                instrument_key=UNDERLYINGS[args.underlying],
                futures_instrument_key=futures_result.instrument_key,
                futures_symbol=futures_result.trading_symbol,
                futures_expiry=futures_result.expiry,
                require_resolved_futures=futures_applicable,
                run_id=cycle_run_id,
            )
            cycle_timings_ms["v2_evaluation"] = (
                perf_counter() - stage_perf_started
            ) * 1000.0
            stage_perf_started = perf_counter()

            v2_snapshot = read_red_bar_v2_ui_snapshot(settings.artifacts_root)
            structural_exit = execute_structural_stop_exits(
                snapshot=v2_snapshot,
                completed_1m_close=live_v2.completed_1m_close,
                completed_1m_timestamp=live_v2.completed_1m_timestamp,
                open_orders=database.read_open_paper_execution_orders("PAPER-STD"),
                close_position=lambda order_id, reason: automation.engine.close_position(
                    zerodha=adapter,
                    order_id=order_id,
                    exit_reason=reason,
                ),
            )
            if structural_exit.exited_orders:
                totals["orders_closed"] += int(structural_exit.exited_orders)

            rsi_exit = execute_rsi_threshold_exits(
                completed_1m_rsi=live_v2.completed_1m_rsi,
                completed_1m_timestamp=live_v2.completed_1m_timestamp,
                open_orders=database.read_open_paper_execution_orders("PAPER-STD"),
                close_position=lambda order_id, reason: automation.engine.close_position(
                    zerodha=adapter,
                    order_id=order_id,
                    exit_reason=reason,
                ),
            )
            if rsi_exit.exited_orders:
                totals["orders_closed"] += int(rsi_exit.exited_orders)

            if structural_exit.exited_orders or rsi_exit.exited_orders:
                live_v2 = evaluate_current_session_red_bar_v2(
                    upstox=upstox,
                    database=database,
                    settings=settings,
                    instrument_key=UNDERLYINGS[args.underlying],
                    run_id=cycle_run_id,
                )
                v2_snapshot = read_red_bar_v2_ui_snapshot(settings.artifacts_root)
            cycle_timings_ms["exit_management"] = (
                perf_counter() - stage_perf_started
            ) * 1000.0
            stage_perf_started = perf_counter()

            if cycle_gate.entry_suspended:
                bridge = RedBarV2PaperSignalPublishResult(
                    "SUSPENDED",
                    "ENTRY_CIRCUIT_OPEN_SIGNAL_PUBLICATION_SKIPPED",
                )
            else:
                bridge = publish_v2_snapshot_to_paper_signals(
                    database_path=settings.database_path,
                    artifacts_root=settings.artifacts_root,
                    instrument_key=UNDERLYINGS[args.underlying],
                    authority=authority,
                    now=cycle_started,
                )
            cycle_timings_ms["signal_publication"] = (
                perf_counter() - stage_perf_started
            ) * 1000.0
            stage_perf_started = perf_counter()
            candle_diagnostic = assess_monitor_underlying_candles(
                upstox,
                instrument_key=UNDERLYINGS[args.underlying],
                now=cycle_started,
                bridge_reason=bridge.reason,
            )
            candle_log_values = _candle_diagnostic_log_values(candle_diagnostic)

            futures_log_values = futures_monitor_log_values(futures_result)
            futures_market_result = assess_nifty_futures_market_data(
                upstox,
                contract=futures_result,
                now=cycle_started,
            )
            futures_market_values = futures_market_log_values(futures_market_result)
            futures_positioning_result = assess_futures_positioning(futures_market_result)
            futures_positioning_values = futures_positioning_log_values(
                futures_positioning_result
            )
            futures_strength_result = assess_nifty_futures_positioning_strength(
                futures_positioning_result
            )
            futures_strength_values = futures_positioning_strength_log_values(
                futures_strength_result
            )
            futures_readiness_result = assess_nifty_futures_readiness(
                contract=futures_result,
                market=futures_market_result,
                positioning=futures_positioning_result,
                applicable=args.underlying == "NIFTY 50",
            )
            futures_readiness_values = futures_readiness_log_values(
                futures_readiness_result
            )
            cycle_timings_ms["readiness"] = (
                perf_counter() - stage_perf_started
            ) * 1000.0
            stage_perf_started = perf_counter()

            feed_failure = critical_market_data_failure(
                underlying_status=candle_diagnostic.readiness.status,
                futures_status=futures_market_result.status,
                futures_applicable=futures_applicable,
            )
            recovered = False
            if feed_failure:
                circuit_decision = circuit.record_failure(feed_failure)
                report = _suspended_report(
                    f"ENTRY_SUSPENDED:{circuit_decision.reason}"
                )
            elif cycle_gate.entry_suspended:
                circuit_decision, recovered = circuit.record_success()
                report = _suspended_report(
                    "ENTRY_RECOVERY_CONFIRMED_RESUME_NEXT_CYCLE"
                )
            else:
                circuit_decision, recovered = circuit.record_success()
                report = automation.run_cycle(
                    trading_date=trading_date,
                    lots=max(1, int(args.lots)),
                    monitor_positions=False,
                    run_id=cycle_run_id,
                )
            cycle_timings_ms["automation"] = (
                perf_counter() - stage_perf_started
            ) * 1000.0
            stage_perf_started = perf_counter()

            next_delay = (
                circuit_decision.delay_seconds
                if feed_failure
                else max(2, args.interval_seconds)
            )
            if recovered:
                logging.warning(
                    "PAPER_MONITOR_ENTRY_FEED_RECOVERED entries resume next cycle"
                )

            totals["signals_seen"] += int(report.signals_seen)
            totals["candidates_scored"] += int(report.candidates_scored)
            totals["orders_opened"] += int(report.paper_orders_opened)
            totals["orders_closed"] += int(report.paper_orders_closed)
            totals["signals_skipped"] += int(report.skipped)

            recent_diagnostics = database.read_paper_signal_diagnostics(limit=1)
            latest = recent_diagnostics[0] if recent_diagnostics else {}
            option_snapshot = database.read_latest_option_chain_snapshot(
                UNDERLYINGS[args.underlying], trading_date
            )
            if option_snapshot:
                latest.setdefault(
                    "option_chain_timestamp",
                    option_snapshot.get("snapshot_timestamp"),
                )
                latest.setdefault("option_expiry", option_snapshot.get("expiry"))
                latest.setdefault("atm_strike", option_snapshot.get("atm_strike"))
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
                option_chain_snapshot=option_snapshot,
            )
            global_readiness_values = global_readiness_log_values(
                global_readiness_result
            )
            cycle_timings_ms["global_readiness"] = (
                perf_counter() - stage_perf_started
            ) * 1000.0

            open_orders = database.read_open_paper_execution_orders("PAPER-STD")
            if circuit_decision.entry_suspended or cycle_gate.entry_suspended:
                last_decision = "ENTRY_SUSPENDED"
                current_state = "POSITION_MANAGEMENT_ONLY"
                last_reason = circuit_decision.reason
            else:
                current_state = (
                    "MONITORING_POSITION" if open_orders else "WAITING_FOR_V2_SIGNAL"
                )
                if _diagnostic_recorded_recently(latest, now=cycle_started):
                    last_decision = latest.get("final_decision") or (
                        "MONITORING" if open_orders else bridge.status
                    )
                    last_reason = latest.get("reason") or bridge.reason
                else:
                    last_decision = "MONITORING"
                    last_reason = (
                        "NO_NEW_SIGNALS_SINCE "
                        f"{latest.get('timestamp') or 'session start'}"
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
            cycle_errors, cycle_warnings = _partition_cycle_messages(
                report.errors,
                tuple(structural_exit.errors) + tuple(rsi_exit.errors),
            )
            database.upsert_paper_monitor_status(
                {
                    "monitor_id": "PAPER-MONITOR",
                    "status": (
                        "DEGRADED"
                        if circuit_decision.entry_suspended
                        or cycle_gate.entry_suspended
                        else "RUNNING"
                    ),
                    "heartbeat_at": heartbeat,
                    "last_scan_at": heartbeat,
                    "started_at": started_at,
                    "underlying_name": args.underlying,
                    **totals,
                    "current_state": current_state,
                    "last_signal_id": latest.get("signal_id") or bridge.signal_id,
                    "last_decision": last_decision,
                    "last_reason": last_reason,
                    "last_error": (
                        " | ".join(cycle_errors[:3]) if cycle_errors else None
                    ),
                }
            )
            if (
                not feed_failure
                and not cycle_gate.entry_suspended
                and not circuit_decision.entry_suspended
            ):
                # Per-stage evidence: one row per cycle_timings_ms key
                # except "total" (which is the cycle as a whole). Each
                # row carries the stage's duration so the cadence
                # panel can render a per-stage timeline.
                _record_paper_cycle_stage_evidence(
                    database,
                    run_id=cycle_run_id,
                    cycle_timings_ms=cycle_timings_ms,
                )
                cycle_total_ms = (
                    cycle_timings_ms.get("total")
                    if isinstance(cycle_timings_ms.get("total"), (int, float))
                    else None
                )
                try:
                    database.record_paper_monitor_success(
                        "PAPER-MONITOR",
                        success_at=heartbeat,
                        decision=last_decision,
                        signal_id=(
                            latest.get("signal_id") or bridge.signal_id
                            if latest
                            else bridge.signal_id
                        ),
                        total_ms=cycle_total_ms,
                        stages={
                            stage: float(value)
                            for stage, value in cycle_timings_ms.items()
                            if isinstance(value, (int, float))
                        },
                        underlying_status=str(
                            getattr(
                                getattr(candle_diagnostic, "readiness", None),
                                "status",
                                None,
                            )
                            or ""
                        )
                        or None,
                        readiness_reason=str(
                            getattr(
                                getattr(candle_diagnostic, "readiness", None),
                                "reason",
                                None,
                            )
                            or ""
                        )
                        or None,
                        readiness_ms=(
                            float(cycle_timings_ms.get("readiness", 0.0))
                            if isinstance(
                                cycle_timings_ms.get("readiness"), (int, float)
                            )
                            else None
                        ),
                        futures_status=str(
                            getattr(futures_market_result, "status", None) or ""
                        )
                        or None,
                        candle_timestamp=str(
                            getattr(
                                getattr(candle_diagnostic, "readiness", None),
                                "latest_timestamp",
                                None,
                            )
                            or ""
                        )
                        or None,
                        candle_age_seconds=(
                            float(
                                getattr(
                                    getattr(
                                        candle_diagnostic, "readiness", None
                                    ),
                                    "candle_age_seconds",
                                    None,
                                )
                            )
                            if getattr(
                                getattr(candle_diagnostic, "readiness", None),
                                "candle_age_seconds",
                                None,
                            )
                            is not None
                            else None
                        ),
                        bridge_alignment=str(
                            getattr(candle_diagnostic, "bridge_alignment", None)
                            or ""
                        )
                        or None,
                    )
                except Exception as exc:  # noqa: BLE001
                    logging.warning(
                        "paper_monitor_success_write_failed err=%s", exc
                    )

            logging.info(
                "paper_monitor circuit=%s failures=%s entry_suspended=%s "
                "delay_seconds=%s v2_live=%s bridge=%s underlying=%s "
                "futures=%s global_readiness=%s signals=%s scored=%s "
                "opened=%s closed=%s skipped=%s decision=%s reason=%s",
                circuit_decision.state,
                circuit_decision.consecutive_failures,
                circuit_decision.entry_suspended or cycle_gate.entry_suspended,
                next_delay,
                live_v2.status,
                bridge.status,
                candle_log_values[0],
                futures_market_values[0],
                global_readiness_values[0],
                report.signals_seen,
                report.candidates_scored,
                report.paper_orders_opened,
                report.paper_orders_closed
                + structural_exit.exited_orders
                + rsi_exit.exited_orders,
                report.skipped,
                last_decision,
                last_reason,
            )
            cycle_timings_ms["total"] = (
                perf_counter() - cycle_perf_started
            ) * 1000.0
            slowest_stage, slowest_ms = max(
                (
                    (name, elapsed)
                    for name, elapsed in cycle_timings_ms.items()
                    if name != "total"
                ),
                key=lambda item: item[1],
            )
            logging.info(
                "paper_monitor_latency total_ms=%.1f slowest_stage=%s "
                "slowest_ms=%.1f futures_resolution_ms=%.1f "
                "v2_evaluation_ms=%.1f exit_management_ms=%.1f "
                "signal_publication_ms=%.1f readiness_ms=%.1f "
                "automation_ms=%.1f global_readiness_ms=%.1f",
                cycle_timings_ms["total"],
                slowest_stage,
                slowest_ms,
                cycle_timings_ms["futures_resolution"],
                cycle_timings_ms["v2_evaluation"],
                cycle_timings_ms["exit_management"],
                cycle_timings_ms["signal_publication"],
                cycle_timings_ms["readiness"],
                cycle_timings_ms["automation"],
                cycle_timings_ms["global_readiness"],
            )
            _persist_latency_snapshot(
                settings.artifacts_root,
                cycle_started_at=cycle_started.isoformat(),
                cycle_completed_at=datetime.now(ist).isoformat(),
                timings_ms=cycle_timings_ms,
                slowest_stage=slowest_stage,
            )
            if live_v2.market_data_evidence and not persist_market_data_evidence(
                settings.artifacts_root,
                live_v2.market_data_evidence,
                correlation_id=(
                    v2_snapshot.correlation_id if v2_snapshot is not None else None
                ),
                recorded_at=datetime.now(ist),
            ):
                logging.warning("red_bar_v2_market_data_evidence_persistence_failed")
            if not persist_stage_latency(
                settings.artifacts_root,
                architecture="legacy",
                correlation_id=(
                    v2_snapshot.correlation_id if v2_snapshot is not None else None
                ),
                stages=_legacy_stage_latency_rows(
                    cycle_timings_ms,
                    report,
                    live_v2,
                ),
                recorded_at=datetime.now(ist),
            ):
                logging.warning("red_bar_v2_legacy_stage_latency_persistence_failed")
            contract_evidence = tuple(
                getattr(report, "contract_selection_evidence", ())
            )
            if contract_evidence and not persist_contract_selection_evidence(
                settings.artifacts_root,
                contract_evidence,
                recorded_at=datetime.now(ist),
            ):
                logging.warning("red_bar_v2_contract_selection_evidence_persistence_failed")
            logging.debug(
                "futures_market=%s futures_market_reason=%s futures_candle=%s "
                "futures_volume=%s futures_close=%s futures_volume_value=%s "
                "futures_oi=%s futures_timestamp=%s futures_candle_count=%s "
                "futures_market_error=%s futures_strength_status=%s "
                "futures_strength_reason=%s futures_strength=%s "
                "futures_strength_state=%s futures_strength_price_pct=%s "
                "futures_strength_oi_pct=%s futures_strength_rvol=%s "
                "global_readiness=%s global_readiness_reason=%s "
                "global_underlying_status=%s global_option_chain_status=%s "
                "global_option_quote_status=%s global_pcr_status=%s "
                "global_futures_status=%s global_futures_strength=%s "
                "global_v2_alignment_status=%s global_execution_source_status=%s "
                "global_market_hours_status=%s global_blocking_reasons=%s "
                "global_advisory_reasons=%s global_execution_reasons=%s "
                "global_authority=%s",
                *futures_market_values,
                *futures_strength_values,
                *global_readiness_values,
            )
            logging.debug(
                "paper_monitor futures_monitor=%s futures_positioning=%s "
                "futures_strength=%s futures_readiness=%s",
                futures_log_values,
                futures_positioning_values,
                futures_strength_values,
                futures_readiness_values,
            )
            for warning in cycle_warnings:
                logging.info("paper automation skip: %s", warning)
            for error in cycle_errors:
                logging.warning("paper automation: %s", error)
        except Exception as exc:
            circuit_decision = circuit.record_failure(
                f"PAPER_MONITOR_CYCLE_FAILED:{type(exc).__name__}"
            )
            next_delay = circuit_decision.delay_seconds
            logging.exception(
                "paper automation cycle failed; circuit=%s failures=%s "
                "entry_suspended=%s delay_seconds=%s",
                circuit_decision.state,
                circuit_decision.consecutive_failures,
                circuit_decision.entry_suspended,
                circuit_decision.delay_seconds,
            )
            heartbeat = datetime.now(ist).isoformat()
            database.upsert_paper_monitor_status(
                {
                    "monitor_id": "PAPER-MONITOR",
                    "status": "DEGRADED",
                    "heartbeat_at": heartbeat,
                    "last_scan_at": heartbeat,
                    "started_at": started_at,
                    "underlying_name": args.underlying,
                    **totals,
                    "current_state": "POSITION_MANAGEMENT_ONLY",
                    "last_signal_id": None,
                    "last_decision": "ENTRY_SUSPENDED",
                    "last_reason": circuit_decision.reason,
                    "last_error": str(exc)[:500],
                }
            )

        if args.once:
            break
        time.sleep(max(2, next_delay))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
