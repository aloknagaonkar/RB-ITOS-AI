from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Callable, Iterable, Mapping

import pandas as pd

from red_bar_lab.execution.directional_regime_background import (
    _completed_five_minute,
    _normalize_one_minute,
)
from red_bar_lab.execution.early_directional_entry import (
    EarlyOneMinuteDirectionalEntryEngine,
)
from red_bar_lab.execution.rsi_extreme_reversal import RsiExtremeReversalEngine
from red_bar_lab.intelligence.stateful_multitimeframe_regime import (
    StatefulMultiTimeframeRegimeEngine,
)
from red_bar_lab.strategy.models import ReferenceLevel
from red_bar_lab.strategy.signal_engine import scan_reference_levels


IST = "Asia/Kolkata"
SOURCE_VERSION = "INDEPENDENT-STRATEGY-SHADOW-WORKER-V3"
EVALUATION_SOURCE = "INDEPENDENT_STRATEGY_SHADOW_WORKER"


@dataclass(frozen=True)
class ShadowStrategyScanResult:
    status: str
    reason: str
    scan_identity: str | None
    instrument_key: str
    evaluated_at: str
    latest_completed_candle: str | None
    red_bar: dict[str, object]
    directional_regime: dict[str, object]
    rsi_reversal: dict[str, object]
    journal_written: bool = False

    def as_record(self) -> dict[str, object]:
        return {
            **self.__dict__,
            "source_version": SOURCE_VERSION,
            "evaluation_source": EVALUATION_SOURCE,
            "shadow_only": True,
            "production_persistence": False,
            "capital_reserved": False,
            "bundle_consumed": False,
            "order_submitted": False,
        }


def _as_ist(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(IST)
    return timestamp.tz_convert(IST)


def _safe_instrument(value: str) -> str:
    safe = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in str(value)
    )
    return safe.strip("_") or "UNKNOWN"


def _attempt_record(attempt) -> dict[str, object]:
    direction = getattr(attempt.direction, "value", attempt.direction)
    state = getattr(attempt.state, "value", attempt.state)
    return {
        "state": str(state),
        "direction": str(direction),
        "level_type": attempt.level_type,
        "level_value": attempt.level_value,
        "cross_timestamp": (
            attempt.cross_timestamp.isoformat()
            if attempt.cross_timestamp is not None
            else None
        ),
        "confirmation_timestamp": (
            attempt.confirmation_timestamp.isoformat()
            if attempt.confirmation_timestamp is not None
            else None
        ),
        "underlying_entry": attempt.underlying_entry,
    }


def _latest_attempt(records: list[dict[str, object]]) -> dict[str, object] | None:
    if not records:
        return None
    return max(
        records,
        key=lambda row: str(
            row.get("confirmation_timestamp")
            or row.get("cross_timestamp")
            or ""
        ),
    )


def _freshness(
    *,
    detected_at: object,
    fresh_until: object,
    evaluated_at: pd.Timestamp,
) -> dict[str, object]:
    try:
        detected = _as_ist(detected_at)
        expiry = _as_ist(fresh_until)
    except (TypeError, ValueError):
        return {
            "freshness_state": "UNAVAILABLE",
            "fresh": False,
            "age_seconds": None,
            "current_action": "OBSERVE_ONLY",
        }

    age_seconds = (evaluated_at - detected).total_seconds()
    if evaluated_at < detected:
        state = "FUTURE_TIMESTAMP"
        fresh = False
    elif evaluated_at <= expiry:
        state = "FRESH"
        fresh = True
    else:
        state = "STALE"
        fresh = False
    return {
        "freshness_state": state,
        "fresh": fresh,
        "age_seconds": max(0.0, age_seconds),
        "current_action": "SHADOW_CANDIDATE" if fresh else "OBSERVE_ONLY",
    }


def evaluate_shadow_strategy_cycle(
    candles: pd.DataFrame,
    *,
    reference_levels: Iterable[ReferenceLevel],
    instrument_key: str,
    now: object | None = None,
    previous_regime: Mapping[str, object] | None = None,
) -> ShadowStrategyScanResult:
    """Evaluate Red Bar, DRI and RSI without invoking any production writer."""
    evaluated = _as_ist(now or pd.Timestamp.now(tz=IST))
    one = _normalize_one_minute([candles], evaluated)
    five = _completed_five_minute(one, evaluated)
    evaluated_at = evaluated.isoformat()

    if one.empty:
        return ShadowStrategyScanResult(
            status="UNAVAILABLE",
            reason="NO_COMPLETED_1M_CANDLES",
            scan_identity=None,
            instrument_key=instrument_key,
            evaluated_at=evaluated_at,
            latest_completed_candle=None,
            red_bar={"status": "NOT_EVALUATED", "attempt_count": 0},
            directional_regime={"status": "NOT_EVALUATED"},
            rsi_reversal={"status": "NOT_EVALUATED", "historical_signal_count": 0},
        )

    latest = _as_ist(one.iloc[-1]["timestamp"])
    latest_text = latest.isoformat()
    scan_identity = f"{instrument_key}|1M|{latest_text}"

    levels = tuple(reference_levels)
    if levels:
        red_bar_scan = scan_reference_levels(one, levels)
        red_bar_attempts = [_attempt_record(item) for item in red_bar_scan.attempts]
        latest_red_bar = _latest_attempt(red_bar_attempts)
        red_bar = {
            "status": "SIGNAL_AVAILABLE" if latest_red_bar else "NO_SIGNAL",
            "input_state": "READY",
            "reference_level_count": len(levels),
            "attempt_count": len(red_bar_attempts),
            "active_count": len(red_bar_scan.active),
            "awaiting_count": len(red_bar_scan.awaiting),
            "failed_count": len(red_bar_scan.failed),
            "latest_attempt": latest_red_bar,
            "current_action": "OBSERVE_ONLY",
            "production_persisted": False,
        }
    else:
        red_bar = {
            "status": "INPUT_UNAVAILABLE",
            "input_state": "REFERENCE_LEVELS_UNAVAILABLE",
            "reference_level_count": 0,
            "attempt_count": 0,
            "active_count": 0,
            "awaiting_count": 0,
            "failed_count": 0,
            "latest_attempt": None,
            "current_action": "WAIT_FOR_REFERENCE_LEVELS",
            "production_persisted": False,
        }

    if len(one) >= 35 and len(five) >= 35:
        snapshot = StatefulMultiTimeframeRegimeEngine().evaluate(
            one,
            five,
            previous_state=dict(previous_regime or {}),
        ).as_record()
        five_regime = str(snapshot.get("five_minute_regime") or "SIDEWAYS")
        early = EarlyOneMinuteDirectionalEntryEngine().evaluate(
            one,
            five_minute_regime=five_regime,
            instrument_key=instrument_key,
        )
        preview = dict(early.bundle or {})
        original_source = preview.get("source")
        freshness = (
            _freshness(
                detected_at=preview.get("detected_at"),
                fresh_until=preview.get("fresh_until"),
                evaluated_at=evaluated,
            )
            if preview
            else {
                "freshness_state": "UNAVAILABLE",
                "fresh": False,
                "age_seconds": None,
                "current_action": "OBSERVE_ONLY",
            }
        )
        directional = {
            "detection_status": early.status,
            "status": (
                "FRESH_SIGNAL"
                if freshness["fresh"]
                else "HISTORICAL_SIGNAL"
                if preview
                else early.status
            ),
            "reason": early.reason,
            "current_regime": snapshot.get("current_regime"),
            "five_minute_regime": snapshot.get("five_minute_regime"),
            "bullish_score": snapshot.get("bullish_score"),
            "bearish_score": snapshot.get("bearish_score"),
            "early_direction": early.direction,
            "early_bundle_preview": preview,
            "original_source": original_source,
            "evaluation_source": EVALUATION_SOURCE,
            **freshness,
            "production_persisted": False,
        }
    else:
        directional = {
            "status": "UNAVAILABLE",
            "detection_status": "UNAVAILABLE",
            "reason": f"INSUFFICIENT_COMPLETED_CANDLES:1M={len(one)};5M={len(five)}",
            "early_bundle_preview": {},
            "freshness_state": "UNAVAILABLE",
            "fresh": False,
            "age_seconds": None,
            "current_action": "OBSERVE_ONLY",
            "evaluation_source": EVALUATION_SOURCE,
            "production_persisted": False,
        }

    rsi_signals = [
        signal.as_record()
        for signal in RsiExtremeReversalEngine().detect(
            one,
            instrument_key=instrument_key,
        )
    ]
    latest_historical = rsi_signals[-1] if rsi_signals else None
    fresh_rsi = []
    for signal in rsi_signals:
        freshness = _freshness(
            detected_at=signal.get("detected_at"),
            fresh_until=signal.get("fresh_until"),
            evaluated_at=evaluated,
        )
        if freshness["fresh"]:
            fresh_rsi.append(signal)
    latest_fresh = fresh_rsi[-1] if fresh_rsi else None
    latest_freshness = (
        _freshness(
            detected_at=latest_historical.get("detected_at"),
            fresh_until=latest_historical.get("fresh_until"),
            evaluated_at=evaluated,
        )
        if latest_historical
        else {
            "freshness_state": "UNAVAILABLE",
            "fresh": False,
            "age_seconds": None,
            "current_action": "OBSERVE_ONLY",
        }
    )
    rsi = {
        "status": (
            "FRESH_SIGNAL_AVAILABLE"
            if latest_fresh
            else "HISTORICAL_SIGNALS_ONLY"
            if latest_historical
            else "NO_SIGNAL"
        ),
        "historical_signal_count": len(rsi_signals),
        "fresh_signal_count": len(fresh_rsi),
        "latest_historical_signal": latest_historical,
        "latest_fresh_signal": latest_fresh,
        "original_source": (
            latest_historical.get("source") if latest_historical else None
        ),
        "evaluation_source": EVALUATION_SOURCE,
        **latest_freshness,
        "current_action": "SHADOW_CANDIDATE" if latest_fresh else "OBSERVE_ONLY",
        "production_persisted": False,
    }

    return ShadowStrategyScanResult(
        status="READY",
        reason="SHADOW_STRATEGIES_EVALUATED",
        scan_identity=scan_identity,
        instrument_key=instrument_key,
        evaluated_at=evaluated_at,
        latest_completed_candle=latest_text,
        red_bar=red_bar,
        directional_regime=directional,
        rsi_reversal=rsi,
    )


class IndependentStrategyShadowWorker:
    """Completed-candle shadow loop; never writes strategy production state."""

    def __init__(
        self,
        *,
        candle_loader: Callable[[], pd.DataFrame],
        reference_level_loader: Callable[[], Iterable[ReferenceLevel]],
        instrument_key: str,
        runs_root: str | Path,
        now_provider: Callable[[], object] | None = None,
        previous_regime_loader: Callable[[], Mapping[str, object] | None] | None = None,
        poll_seconds: int = 5,
    ):
        self.candle_loader = candle_loader
        self.reference_level_loader = reference_level_loader
        self.instrument_key = instrument_key
        self.runs_root = Path(runs_root)
        self.now_provider = now_provider
        self.previous_regime_loader = previous_regime_loader
        self.poll_seconds = max(1, int(poll_seconds))
        safe = _safe_instrument(instrument_key)
        self.shadow_root = self.runs_root / "independent_strategy_shadow_v1"
        self.journal_path = self.shadow_root / f"{safe}.jsonl"
        self.status_path = self.shadow_root / f"{safe}.status.json"
        self._last_scan_identity: str | None = None

    def _now(self) -> object:
        return self.now_provider() if self.now_provider else pd.Timestamp.now(tz=IST)

    def _journal_contains(self, scan_identity: str) -> bool:
        if not self.journal_path.exists():
            return False
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if str(row.get("scan_identity") or "") == scan_identity:
                return True
        return False

    def _append_once(self, result: ShadowStrategyScanResult) -> bool:
        if not result.scan_identity or self._journal_contains(result.scan_identity):
            return False
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(result.as_record(), separators=(",", ":"), default=str)
                + "\n"
            )
        return True

    def _write_status(self, result: ShadowStrategyScanResult) -> None:
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.status_path.with_suffix(self.status_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(result.as_record(), indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(self.status_path)

    def run_once(self) -> ShadowStrategyScanResult:
        result = evaluate_shadow_strategy_cycle(
            self.candle_loader(),
            reference_levels=tuple(self.reference_level_loader()),
            instrument_key=self.instrument_key,
            now=self._now(),
            previous_regime=(
                self.previous_regime_loader()
                if self.previous_regime_loader is not None
                else None
            ),
        )
        if result.scan_identity == self._last_scan_identity:
            duplicate = ShadowStrategyScanResult(
                **{**result.__dict__, "reason": "COMPLETED_CANDLE_ALREADY_SCANNED"}
            )
            self._write_status(duplicate)
            return duplicate
        written = self._append_once(result)
        self._last_scan_identity = result.scan_identity
        completed = ShadowStrategyScanResult(
            **{**result.__dict__, "journal_written": written}
        )
        self._write_status(completed)
        return completed

    def write_error_status(self, exc: Exception) -> None:
        evaluated_at = _as_ist(self._now()).isoformat()
        result = ShadowStrategyScanResult(
            status="ERROR",
            reason=f"{type(exc).__name__}:{exc}",
            scan_identity=self._last_scan_identity,
            instrument_key=self.instrument_key,
            evaluated_at=evaluated_at,
            latest_completed_candle=None,
            red_bar={"status": "NOT_EVALUATED"},
            directional_regime={"status": "NOT_EVALUATED"},
            rsi_reversal={"status": "NOT_EVALUATED"},
        )
        self._write_status(result)

    def run_forever(self, *, stop_requested: Callable[[], bool] | None = None) -> None:
        while not (stop_requested and stop_requested()):
            try:
                self.run_once()
            except Exception as exc:
                self.write_error_status(exc)
            time.sleep(self.poll_seconds)


__all__ = [
    "SOURCE_VERSION",
    "ShadowStrategyScanResult",
    "evaluate_shadow_strategy_cycle",
    "IndependentStrategyShadowWorker",
]
