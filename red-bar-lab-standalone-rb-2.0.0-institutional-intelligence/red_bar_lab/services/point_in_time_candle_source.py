from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Callable, Iterable, Mapping

import pandas as pd

CANDLE_SOURCE_POLICY_VERSION = "point-in-time-candle-source-v1"


@dataclass(frozen=True)
class CandleSelectionResult:
    status: str
    selected_source: str | None
    requested_cutoff: str
    latest_candle_timestamp: str | None
    row_count: int
    no_lookahead_passed: bool
    reason_code: str | None = None
    reason: str | None = None
    fallback_used: bool = False
    policy_version: str = CANDLE_SOURCE_POLICY_VERSION
    rows: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _timestamp(value: object) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if result.tzinfo is None:
        result = result.tz_localize("Asia/Kolkata")
    else:
        result = result.tz_convert("Asia/Kolkata")
    return result


def _row_timestamp(row: Mapping[str, Any]) -> pd.Timestamp | None:
    for key in (
        "timestamp",
        "candle_timestamp",
        "market_timestamp",
        "datetime",
        "time",
    ):
        value = _timestamp(row.get(key))
        if value is not None:
            return value
    return None


def _normalize_rows(
    rows: Iterable[Mapping[str, Any]] | None,
    *,
    cutoff: pd.Timestamp,
) -> tuple[tuple[dict[str, Any], ...], bool]:
    accepted: list[tuple[pd.Timestamp, dict[str, Any]]] = []
    saw_future = False
    for original in rows or ():
        row = dict(original)
        stamp = _row_timestamp(row)
        if stamp is None:
            continue
        if stamp > cutoff:
            saw_future = True
            continue
        accepted.append((stamp, row))
    accepted.sort(key=lambda item: item[0])
    return tuple(row for _, row in accepted), saw_future


def _result_for_rows(
    *,
    source: str,
    rows: Iterable[Mapping[str, Any]] | None,
    cutoff: pd.Timestamp,
    fallback_used: bool,
) -> CandleSelectionResult:
    normalized, saw_future = _normalize_rows(rows, cutoff=cutoff)
    latest = _row_timestamp(normalized[-1]) if normalized else None
    if normalized:
        return CandleSelectionResult(
            status="READY",
            selected_source=source,
            requested_cutoff=cutoff.isoformat(),
            latest_candle_timestamp=latest.isoformat() if latest is not None else None,
            row_count=len(normalized),
            no_lookahead_passed=not saw_future,
            fallback_used=fallback_used,
            rows=normalized,
        )
    return CandleSelectionResult(
        status="MISSING",
        selected_source=source,
        requested_cutoff=cutoff.isoformat(),
        latest_candle_timestamp=None,
        row_count=0,
        no_lookahead_passed=not saw_future,
        reason_code=(
            "ONLY_FUTURE_CANDLES_AVAILABLE" if saw_future else "COMPLETED_CANDLES_MISSING"
        ),
        reason=(
            "Source returned candles only after the requested cutoff."
            if saw_future
            else "Source returned no completed candles at or before the requested cutoff."
        ),
        fallback_used=fallback_used,
    )


def select_point_in_time_completed_candles(
    *,
    instrument_key: str,
    timeframe: str,
    cutoff_timestamp: object,
    live_reader: Callable[..., Iterable[Mapping[str, Any]] | None] | None = None,
    historical_reader: Callable[..., Iterable[Mapping[str, Any]] | None] | None = None,
    allow_historical_fallback: bool = True,
    current_date: date | None = None,
) -> CandleSelectionResult:
    """Select completed candles without allowing observations after the cutoff.

    Live persisted candles are preferred for a current-session cutoff. Historical
    data is used directly for older sessions and may be used as an explicit
    fallback for the current session when enabled.
    """

    cutoff = _timestamp(cutoff_timestamp)
    if cutoff is None:
        return CandleSelectionResult(
            status="FAILED",
            selected_source=None,
            requested_cutoff=str(cutoff_timestamp),
            latest_candle_timestamp=None,
            row_count=0,
            no_lookahead_passed=False,
            reason_code="CUTOFF_TIMESTAMP_INVALID",
            reason="The candle cutoff timestamp could not be parsed.",
        )

    session_date = current_date or datetime.now(cutoff.tzinfo).date()
    is_current_session = cutoff.date() == session_date

    def read(reader, source: str, fallback_used: bool) -> CandleSelectionResult:
        if reader is None:
            return CandleSelectionResult(
                status="MISSING",
                selected_source=source,
                requested_cutoff=cutoff.isoformat(),
                latest_candle_timestamp=None,
                row_count=0,
                no_lookahead_passed=True,
                reason_code=f"{source}_READER_UNAVAILABLE",
                reason=f"{source} reader is not configured.",
                fallback_used=fallback_used,
            )
        try:
            rows = reader(
                instrument_key=instrument_key,
                timeframe=timeframe,
                cutoff_timestamp=cutoff.isoformat(),
            )
        except Exception as exc:  # diagnostics must not mask the original pipeline
            return CandleSelectionResult(
                status="FAILED",
                selected_source=source,
                requested_cutoff=cutoff.isoformat(),
                latest_candle_timestamp=None,
                row_count=0,
                no_lookahead_passed=False,
                reason_code=f"{source}_READ_FAILED",
                reason=f"{type(exc).__name__}: {exc}",
                fallback_used=fallback_used,
            )
        return _result_for_rows(
            source=source,
            rows=rows,
            cutoff=cutoff,
            fallback_used=fallback_used,
        )

    if is_current_session:
        live = read(live_reader, "LIVE_PERSISTED", False)
        if live.status == "READY":
            return live
        if not allow_historical_fallback:
            return live
        historical = read(historical_reader, "HISTORICAL_REPOSITORY", True)
        if historical.status == "READY":
            return historical
        return CandleSelectionResult(
            status="FAILED" if "FAILED" in {live.status, historical.status} else "MISSING",
            selected_source=historical.selected_source,
            requested_cutoff=cutoff.isoformat(),
            latest_candle_timestamp=None,
            row_count=0,
            no_lookahead_passed=(
                live.no_lookahead_passed and historical.no_lookahead_passed
            ),
            reason_code="LIVE_AND_HISTORICAL_CANDLES_UNAVAILABLE",
            reason=f"Live: {live.reason_code}; Historical: {historical.reason_code}",
            fallback_used=True,
        )

    return read(historical_reader, "HISTORICAL_REPOSITORY", False)


__all__ = [
    "CANDLE_SOURCE_POLICY_VERSION",
    "CandleSelectionResult",
    "select_point_in_time_completed_candles",
]
