from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Callable, Iterable, Mapping

import pandas as pd

from red_bar_lab.execution.directional_regime_background import _normalize_one_minute
from red_bar_lab.strategy.models import ReferenceLevel
from red_bar_lab.strategy.signal_engine import scan_reference_levels


IST = "Asia/Kolkata"
SOURCE_VERSION = "INDEPENDENT-STRATEGY-SHADOW-WORKER-V4"
EVALUATION_SOURCE = "INDEPENDENT_STRATEGY_SHADOW_WORKER"
RETIRED_DRI_REASON = "STANDALONE_DRI_RETIRED"
RETIRED_RSI_REASON = "STANDALONE_RSI_REVERSAL_RETIRED"


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


def _retired_directional_regime() -> dict[str, object]:
    return {
        "status": "INACTIVE_STRATEGY",
        "detection_status": "INACTIVE_STRATEGY",
        "reason": RETIRED_DRI_REASON,
        "early_bundle_preview": {},
        "freshness_state": "INACTIVE",
        "fresh": False,
        "age_seconds": None,
        "current_action": "NONE",
        "evaluation_source": EVALUATION_SOURCE,
        "production_persisted": False,
    }


def _retired_rsi_reversal() -> dict[str, object]:
    return {
        "status": "INACTIVE_STRATEGY",
        "reason": RETIRED_RSI_REASON,
        "historical_signal_count": 0,
        "fresh_signal_count": 0,
        "latest_historical_signal": None,
        "latest_fresh_signal": None,
        "freshness_state": "INACTIVE",
        "fresh": False,
        "age_seconds": None,
        "current_action": "NONE",
        "evaluation_source": EVALUATION_SOURCE,
        "production_persisted": False,
    }


def evaluate_shadow_strategy_cycle(
    candles: pd.DataFrame,
    *,
    reference_levels: Iterable[ReferenceLevel],
    instrument_key: str,
    now: object | None = None,
    previous_regime: Mapping[str, object] | None = None,
) -> ShadowStrategyScanResult:
    """Evaluate Red Bar only while preserving retired-strategy compatibility fields."""
    del previous_regime
    evaluated = _as_ist(now or pd.Timestamp.now(tz=IST))
    one = _normalize_one_minute([candles], evaluated)
    evaluated_at = evaluated.isoformat()
    directional = _retired_directional_regime()
    rsi = _retired_rsi_reversal()

    if one.empty:
        return ShadowStrategyScanResult(
            status="UNAVAILABLE",
            reason="NO_COMPLETED_1M_CANDLES",
            scan_identity=None,
            instrument_key=instrument_key,
            evaluated_at=evaluated_at,
            latest_completed_candle=None,
            red_bar={"status": "NOT_EVALUATED", "attempt_count": 0},
            directional_regime=directional,
            rsi_reversal=rsi,
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

    return ShadowStrategyScanResult(
        status="READY",
        reason="RED_BAR_SHADOW_EVALUATED",
        scan_identity=scan_identity,
        instrument_key=instrument_key,
        evaluated_at=evaluated_at,
        latest_completed_candle=latest_text,
        red_bar=red_bar,
        directional_regime=directional,
        rsi_reversal=rsi,
    )


class IndependentStrategyShadowWorker:
    """Completed-candle Red Bar shadow loop; never writes production strategy state."""

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
            directional_regime=_retired_directional_regime(),
            rsi_reversal=_retired_rsi_reversal(),
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
