from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from red_bar_lab.execution.headless_strategy_pipeline import evaluate_sections_4_to_9
from red_bar_lab.execution.shadow_evaluation_journal import append_evaluation_cycle
from red_bar_lab.ui.controlled_paper_activation import build_controlled_paper_activation
from red_bar_lab.ui.strategy_dri_bundle import build_dri_bundle_resolution
from red_bar_lab.ui.strategy_input_preparation import (
    prepare_completed_five_minute,
    prepare_completed_one_minute,
)
from red_bar_lab.ui.strategy_option_context import build_option_behaviour_snapshot
from red_bar_lab.ui.strategy_red_bar_bundle import build_red_bar_bundle_resolution
from red_bar_lab.ui.strategy_red_bar_setup import build_red_bar_owned_setup_state
from red_bar_lab.ui.strategy_setup_detection import build_dri_setup_state, build_rsi_setup_state
from red_bar_lab.ui.strategy_signal_resolution import build_rsi_signal_resolution
from red_bar_lab.ui.strategy_shadow_evidence_registry import record_shadow_evidence
from red_bar_lab.ui.unified_shadow_execution_router import build_unified_shadow_routes


BACKGROUND_ARCHITECTURE_ORCHESTRATOR_VERSION = "BACKGROUND-ARCHITECTURE-ORCHESTRATOR-V3"
IST = ZoneInfo("Asia/Kolkata")
_LOCK = RLock()
_ACTIVE: "BackgroundArchitectureOrchestrator | None" = None

_SECTION_OUTCOME_FIELDS = (
    ("4", "section_4_outcome"),
    ("5A", "section_5a_outcome"),
    ("5B", "section_5b_outcome"),
    ("5C", "section_5c_outcome"),
    ("5D", "section_5d_outcome"),
    ("5E", "section_5e_outcome"),
    ("6", "section_6_outcome"),
    ("7", "section_7_outcome"),
    ("8", "section_8_outcome"),
    ("9", "section_9_outcome"),
    ("10D", "section_10d_outcome"),
    ("10E", "section_10e_outcome"),
)


def _outcome(result: Mapping[str, object] | None, *keys: str) -> str:
    row = dict(result or {})
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return "NOT_EVALUATED"


def _apply_downstream_skips(row: Mapping[str, object]) -> dict[str, object]:
    """Make the audit trail explicit after the first authoritative blocker.

    The blocking section keeps its real outcome and reason. Every later section is
    marked SKIPPED_BLOCKED_AT_<SECTION> so the UI never implies that downstream
    decision logic was independently evaluated after an earlier stop.
    """
    result = dict(row)
    terminal = str(result.get("terminal_section") or "").upper()
    indexes = {section: index for index, (section, _) in enumerate(_SECTION_OUTCOME_FIELDS)}
    if terminal not in indexes:
        return result

    skipped_value = f"SKIPPED_BLOCKED_AT_{terminal}"
    terminal_index = indexes[terminal]
    for _, field in _SECTION_OUTCOME_FIELDS[terminal_index + 1 :]:
        result[field] = skipped_value

    # Compatibility summary mirrors canonical 5E while preserving the new detail fields.
    result["section_5_outcome"] = result.get("section_5e_outcome")
    result["downstream_skip_applied"] = terminal_index < len(_SECTION_OUTCOME_FIELDS) - 1
    result["downstream_skip_reason"] = skipped_value
    return result


def _read_cached_candles(layout, instrument_key: str, trading_date: str):
    path = layout.candle_path("upstox", instrument_key, 1, trading_date)
    if not path.exists():
        return path, pd.DataFrame()
    try:
        return path, pd.read_csv(path)
    except Exception:
        return path, pd.DataFrame()


def _red_bar_resolution(*, settings, layout, database, instrument_key, trading_date):
    path, candles = _read_cached_candles(layout, instrument_key, trading_date)
    prepared = prepare_completed_one_minute(candles, trading_date)
    levels = database.read_reference_levels(instrument_key, trading_date)
    option_context = build_option_behaviour_snapshot(database, instrument_key, trading_date)
    references = [row for row in levels if str(row.get("level_type") or "") == "NEXT_RED_CANDLE"]
    reference = references[-1] if references else {}
    setup = build_red_bar_owned_setup_state(
        database, instrument_key, trading_date, reference=reference,
        option_bias=option_context.get("directional_bias"),
    )
    resolution = build_red_bar_bundle_resolution(
        database=database, instrument_key=instrument_key,
        trading_date=trading_date, reference=reference,
    )
    return {
        "page": "Red Bar Strategy", "strategy_id": "RED_BAR",
        "candle_path": str(path), "raw_candle_count": len(candles),
        "prepared_candle_count": len(prepared),
        "section_1_outcome": "READY" if len(prepared) and reference else "NOT_READY",
        "section_2_outcome": _outcome(setup, "status"), "setup": setup,
        "option_context": option_context, "resolution": resolution,
    }


def _dri_resolution(*, settings, layout, database, instrument_key, trading_date):
    path, candles = _read_cached_candles(layout, instrument_key, trading_date)
    one_minute = prepare_completed_one_minute(candles, trading_date)
    five_minute = prepare_completed_five_minute(one_minute, trading_date)
    option_context = build_option_behaviour_snapshot(database, instrument_key, trading_date)
    setup = build_dri_setup_state(
        settings.runs_root, instrument_key, trading_date,
        option_bias=option_context.get("directional_bias"),
    )
    resolution = build_dri_bundle_resolution(
        database=database, runs_root=settings.runs_root,
        instrument_key=instrument_key, trading_date=trading_date,
    )
    return {
        "page": "Directional Regime Intelligence",
        "strategy_id": "DIRECTIONAL_REGIME_INTELLIGENCE",
        "candle_path": str(path), "raw_candle_count": len(candles),
        "prepared_candle_count": len(one_minute),
        "five_minute_candle_count": len(five_minute),
        "section_1_outcome": "READY" if len(one_minute) >= 35 and len(five_minute) >= 35 else "PARTIAL",
        "section_2_outcome": _outcome(setup, "status"), "setup": setup,
        "option_context": option_context, "resolution": resolution,
    }


def _rsi_resolution(*, settings, layout, database, instrument_key, trading_date):
    path, candles = _read_cached_candles(layout, instrument_key, trading_date)
    prepared = prepare_completed_one_minute(candles, trading_date)
    option_context = build_option_behaviour_snapshot(database, instrument_key, trading_date)
    setup = build_rsi_setup_state(prepared, instrument_key, option_bias=option_context.get("directional_bias"))
    resolution = build_rsi_signal_resolution(
        candles=prepared, database=database, settings=settings,
        instrument_key=instrument_key, trading_date=trading_date,
    )
    return {
        "page": "RSI Extreme Reversal", "strategy_id": "RSI_EXTREME_REVERSAL",
        "candle_path": str(path), "raw_candle_count": len(candles),
        "prepared_candle_count": len(prepared),
        "section_1_outcome": "READY" if len(prepared) >= 2 else "NOT_READY",
        "section_2_outcome": _outcome(setup, "status"), "setup": setup,
        "option_context": option_context, "resolution": resolution,
    }


class BackgroundArchitectureOrchestrator:
    """Continuously evaluate Sections 1-10E without execution authority."""

    def __init__(self, *, settings, layout, database, instrument_key: str, interval_seconds: int = 60):
        self.settings = settings
        self.layout = layout
        self.database = database
        self.instrument_key = str(instrument_key)
        self.interval_seconds = max(15, int(interval_seconds))
        self._stop = Event()
        self._thread: Thread | None = None
        self.last_cycle_at: str | None = None
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="new-architecture-shadow-orchestrator", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_cycle()
                self.last_error = None
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
            self._stop.wait(self.interval_seconds)

    def run_cycle(self) -> list[dict[str, object]]:
        now = datetime.now(IST)
        trading_date = now.date().isoformat()
        cycle_id = f"ARCH-{now.strftime('%Y%m%dT%H%M%S%f%z')}"
        builders = (_red_bar_resolution, _dri_resolution, _rsi_resolution)
        rows: list[dict[str, object]] = []

        for builder in builders:
            started = datetime.now(IST)
            base: dict[str, object] = {}
            try:
                base = builder(
                    settings=self.settings, layout=self.layout, database=self.database,
                    instrument_key=self.instrument_key, trading_date=trading_date,
                )
                resolution = dict(base.get("resolution") or {})
                pipeline = evaluate_sections_4_to_9(
                    page=str(base["page"]), resolution=resolution,
                    database=self.database, instrument_key=self.instrument_key,
                    evaluation_timestamp=now.isoformat(),
                )
                shadow_rehearsal = dict(pipeline.get("shadow_rehearsal") or {})
                evidence_capture = record_shadow_evidence(
                    page=str(base["page"]), strategy_id=str(base["strategy_id"]),
                    gate=dict(pipeline.get("gate") or {}),
                    readiness=dict(pipeline.get("readiness_5a") or {}),
                    final_admission=dict(pipeline.get("final_admission") or {}),
                    committee_result=dict(pipeline.get("committee") or {}),
                    shadow_rehearsal=shadow_rehearsal,
                    evaluation_timestamp=now.isoformat(),
                )
                evidence_rows = list(shadow_rehearsal.get("rows") or [])
                router = build_unified_shadow_routes(evidence_rows)
                activation = build_controlled_paper_activation(router)

                row = {
                    "orchestration_cycle_id": cycle_id,
                    "orchestrator_version": BACKGROUND_ARCHITECTURE_ORCHESTRATOR_VERSION,
                    "strategy_id": base["strategy_id"], "page": base["page"],
                    "instrument_key": self.instrument_key, "trading_date": trading_date,
                    "started_at": started.isoformat(), "completed_at": datetime.now(IST).isoformat(),
                    "candle_path": base.get("candle_path"),
                    "raw_candle_count": base.get("raw_candle_count", 0),
                    "prepared_candle_count": base.get("prepared_candle_count", 0),
                    "five_minute_candle_count": base.get("five_minute_candle_count"),
                    "signal_id": resolution.get("signal_id"), "bundle_id": resolution.get("bundle_id"),
                    "section_1_outcome": base.get("section_1_outcome"),
                    "section_2_outcome": base.get("section_2_outcome"),
                    "section_3_outcome": resolution.get("final_outcome"),
                    "section_4_outcome": _outcome(pipeline.get("gate"), "final_outcome"),
                    "section_5a_outcome": _outcome(pipeline.get("readiness_5a"), "outcome"),
                    "section_5b_outcome": _outcome(pipeline.get("market_context_5b"), "market_context_status"),
                    "section_5c_outcome": _outcome(pipeline.get("metadata_context_5c"), "metadata_context_status"),
                    "section_5d_outcome": _outcome(pipeline.get("safeguarded"), "outcome"),
                    "section_5e_outcome": _outcome(pipeline.get("ranking"), "outcome"),
                    "section_5_outcome": _outcome(pipeline.get("ranking"), "outcome"),
                    "section_6_outcome": _outcome(pipeline.get("candidate"), "outcome"),
                    "section_7_outcome": _outcome(pipeline.get("opportunity"), "outcome"),
                    "section_8_outcome": _outcome(pipeline.get("final_admission"), "outcome", "decision"),
                    "section_9_outcome": _outcome(shadow_rehearsal, "outcome"),
                    "section_10d_outcome": router.get("outcome"),
                    "section_10e_outcome": activation.get("outcome"),
                    "terminal_section": pipeline.get("terminal_section"),
                    "terminal_reason": pipeline.get("terminal_reason"),
                    "candidate_count": len(dict(pipeline.get("candidate") or {}).get("candidates") or []),
                    "shadow_evidence_captured": evidence_capture.get("captured_count", 0),
                    "shadow_route_count": router.get("routed_count", 0),
                    "source_read_only": True, "execution_allowed": False,
                }
                row = _apply_downstream_skips(row)
            except Exception as exc:
                row = {
                    "orchestration_cycle_id": cycle_id,
                    "orchestrator_version": BACKGROUND_ARCHITECTURE_ORCHESTRATOR_VERSION,
                    "strategy_id": base.get("strategy_id") or getattr(builder, "__name__", "UNKNOWN"),
                    "page": base.get("page"), "instrument_key": self.instrument_key,
                    "trading_date": trading_date, "started_at": started.isoformat(),
                    "completed_at": datetime.now(IST).isoformat(),
                    "section_1_outcome": base.get("section_1_outcome", "ERROR"),
                    "section_2_outcome": base.get("section_2_outcome", "NOT_EVALUATED"),
                    "section_3_outcome": "NOT_EVALUATED", "section_4_outcome": "NOT_EVALUATED",
                    "section_5a_outcome": "NOT_EVALUATED", "section_5b_outcome": "NOT_EVALUATED",
                    "section_5c_outcome": "NOT_EVALUATED", "section_5d_outcome": "NOT_EVALUATED",
                    "section_5e_outcome": "NOT_EVALUATED", "section_5_outcome": "NOT_EVALUATED",
                    "section_6_outcome": "NOT_EVALUATED", "section_7_outcome": "NOT_EVALUATED",
                    "section_8_outcome": "NOT_EVALUATED", "section_9_outcome": "NOT_EVALUATED",
                    "section_10d_outcome": "NOT_EVALUATED", "section_10e_outcome": "NOT_EVALUATED",
                    "terminal_section": "ORCHESTRATOR",
                    "terminal_reason": f"{type(exc).__name__}: {exc}",
                    "source_read_only": True, "execution_allowed": False,
                }
            rows.append(append_evaluation_cycle(self.settings.runs_root, row))

        self.last_cycle_at = datetime.now(IST).isoformat()
        return rows

    def status(self) -> dict[str, object]:
        return {
            "version": BACKGROUND_ARCHITECTURE_ORCHESTRATOR_VERSION,
            "running": self.running, "interval_seconds": self.interval_seconds,
            "instrument_key": self.instrument_key, "last_cycle_at": self.last_cycle_at,
            "last_error": self.last_error, "execution_allowed": False,
        }


def ensure_background_architecture_orchestrator(*, settings, layout, database, instrument_key: str, interval_seconds: int = 60) -> BackgroundArchitectureOrchestrator:
    global _ACTIVE
    with _LOCK:
        if _ACTIVE is None or _ACTIVE.instrument_key != str(instrument_key) or Path(_ACTIVE.settings.runs_root) != Path(settings.runs_root):
            if _ACTIVE is not None:
                _ACTIVE.stop()
            _ACTIVE = BackgroundArchitectureOrchestrator(
                settings=settings, layout=layout, database=database,
                instrument_key=str(instrument_key), interval_seconds=interval_seconds,
            )
            _ACTIVE.start()
        return _ACTIVE


def current_background_architecture_status() -> dict[str, object]:
    with _LOCK:
        if _ACTIVE is None:
            return {
                "version": BACKGROUND_ARCHITECTURE_ORCHESTRATOR_VERSION,
                "running": False, "last_cycle_at": None, "last_error": None,
                "execution_allowed": False,
            }
        return _ACTIVE.status()


__all__ = [
    "BACKGROUND_ARCHITECTURE_ORCHESTRATOR_VERSION",
    "BackgroundArchitectureOrchestrator",
    "ensure_background_architecture_orchestrator",
    "current_background_architecture_status",
]
