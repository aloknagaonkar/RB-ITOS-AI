from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd


INDIA_TZ = ZoneInfo("Asia/Kolkata")
EXPECTED_INDEX_ROWS = 375
EXPECTED_SESSION_START = time(9, 15)
EXPECTED_SESSION_END = time(15, 29)
RESEARCH_EXIT_START = time(9, 30)
RESEARCH_EXIT_END = time(15, 25)
RESEARCH_EXIT_INTERVAL_MINUTES = 5


@dataclass(frozen=True)
class SessionRegimeDiagnostics:
    regime: str
    reason: str
    session_open: float | None
    session_close: float | None
    session_high: float | None
    session_low: float | None
    net_points: float | None
    net_return_pct: float | None
    travelled_points: float | None
    directional_efficiency: float | None
    intraday_range_pct: float | None


@dataclass(frozen=True)
class SessionCompleteness:
    status: str
    reason: str
    observed_rows: int
    expected_rows: int
    coverage_pct: float
    first_timestamp: datetime | None
    last_timestamp: datetime | None


def _normalise(candles: pd.DataFrame) -> pd.DataFrame:
    if candles is None or candles.empty:
        return pd.DataFrame()
    frame = candles.copy()
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
        frame = frame.dropna(subset=["timestamp"]).set_index("timestamp")
    if not isinstance(frame.index, pd.DatetimeIndex):
        return pd.DataFrame()
    index = frame.index
    if index.tz is None:
        index = index.tz_localize(INDIA_TZ)
    else:
        index = index.tz_convert(INDIA_TZ)
    frame.index = index
    return frame.sort_index()


def diagnose_session_regime(index_candles: pd.DataFrame) -> SessionRegimeDiagnostics:
    frame = _normalise(index_candles)
    if frame.empty or "close" not in frame.columns:
        return SessionRegimeDiagnostics(
            regime="UNAVAILABLE",
            reason="NO_VALID_CLOSE_SERIES",
            session_open=None,
            session_close=None,
            session_high=None,
            session_low=None,
            net_points=None,
            net_return_pct=None,
            travelled_points=None,
            directional_efficiency=None,
            intraday_range_pct=None,
        )

    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(close) < 2 or float(close.iloc[0]) == 0:
        return SessionRegimeDiagnostics(
            regime="UNAVAILABLE",
            reason="INSUFFICIENT_CLOSE_SERIES",
            session_open=None,
            session_close=None,
            session_high=None,
            session_low=None,
            net_points=None,
            net_return_pct=None,
            travelled_points=None,
            directional_efficiency=None,
            intraday_range_pct=None,
        )

    open_value = float(close.iloc[0])
    close_value = float(close.iloc[-1])
    high_series = pd.to_numeric(frame.get("high", close), errors="coerce").dropna()
    low_series = pd.to_numeric(frame.get("low", close), errors="coerce").dropna()
    high_value = float(high_series.max()) if not high_series.empty else float(close.max())
    low_value = float(low_series.min()) if not low_series.empty else float(close.min())
    signed_net_points = close_value - open_value
    net_return_pct = signed_net_points / open_value * 100.0
    travelled_points = float(close.diff().abs().sum())
    directional_efficiency = (
        abs(signed_net_points) / travelled_points if travelled_points > 0 else 0.0
    )
    intraday_range_pct = (high_value - low_value) / open_value * 100.0

    if net_return_pct >= 0.35 and directional_efficiency >= 0.25:
        regime = "TREND_UP"
        reason = "POSITIVE_DISPLACEMENT_AND_EFFICIENCY"
    elif net_return_pct <= -0.35 and directional_efficiency >= 0.25:
        regime = "TREND_DOWN"
        reason = "NEGATIVE_DISPLACEMENT_AND_EFFICIENCY"
    elif abs(net_return_pct) < 0.35:
        regime = "RANGE"
        reason = "NET_DISPLACEMENT_BELOW_THRESHOLD"
    else:
        regime = "RANGE"
        reason = "DIRECTIONAL_EFFICIENCY_BELOW_THRESHOLD"

    return SessionRegimeDiagnostics(
        regime=regime,
        reason=reason,
        session_open=open_value,
        session_close=close_value,
        session_high=high_value,
        session_low=low_value,
        net_points=signed_net_points,
        net_return_pct=net_return_pct,
        travelled_points=travelled_points,
        directional_efficiency=directional_efficiency,
        intraday_range_pct=intraday_range_pct,
    )


def evaluate_session_completeness(
    index_candles: pd.DataFrame,
    *,
    expected_rows: int = EXPECTED_INDEX_ROWS,
) -> SessionCompleteness:
    frame = _normalise(index_candles)
    observed = len(frame)
    coverage = observed / expected_rows * 100.0 if expected_rows > 0 else 0.0
    first = frame.index[0].to_pydatetime() if observed else None
    last = frame.index[-1].to_pydatetime() if observed else None

    if observed == 0:
        return SessionCompleteness(
            status="MISSING",
            reason="NO_INDEX_ROWS",
            observed_rows=0,
            expected_rows=expected_rows,
            coverage_pct=0.0,
            first_timestamp=None,
            last_timestamp=None,
        )

    first_time = first.astimezone(INDIA_TZ).time().replace(tzinfo=None) if first else None
    last_time = last.astimezone(INDIA_TZ).time().replace(tzinfo=None) if last else None
    if (
        observed >= expected_rows
        and first_time is not None
        and first_time <= EXPECTED_SESSION_START
        and last_time is not None
        and last_time >= EXPECTED_SESSION_END
    ):
        status = "COMPLETE"
        reason = "FULL_EXPECTED_INDEX_SESSION"
    else:
        status = "PARTIAL"
        reasons: list[str] = []
        if observed < expected_rows:
            reasons.append("ROW_COUNT_BELOW_EXPECTED")
        if first_time is None or first_time > EXPECTED_SESSION_START:
            reasons.append("LATE_SESSION_START")
        if last_time is None or last_time < EXPECTED_SESSION_END:
            reasons.append("EARLY_SESSION_END")
        reason = "+".join(reasons) or "SESSION_BOUNDARY_MISMATCH"

    return SessionCompleteness(
        status=status,
        reason=reason,
        observed_rows=observed,
        expected_rows=expected_rows,
        coverage_pct=coverage,
        first_timestamp=first,
        last_timestamp=last,
    )


def _default_research_exit_times() -> tuple[time, ...]:
    anchor = datetime.combine(date(2000, 1, 1), RESEARCH_EXIT_START)
    end = datetime.combine(date(2000, 1, 1), RESEARCH_EXIT_END)
    values: list[time] = []
    while anchor <= end:
        values.append(anchor.time())
        anchor += timedelta(minutes=RESEARCH_EXIT_INTERVAL_MINUTES)
    return tuple(values)


def deterministic_research_exit_timestamps(
    trading_date: str | date,
    *,
    local_times: Iterable[time] | None = None,
) -> tuple[pd.Timestamp, ...]:
    """A fixed grid of exit times for one session: a clock, not a policy.

    Every five minutes from 09:30 to 15:25 IST, unrelated to price. It exists so
    a replay can be handed *some* exits and made to produce more than one trade
    per day, and it is a legitimate fixture for that -- but a block count or an
    R-multiple measured against it is a property of this grid, not of the
    strategy. Research that wants the strategy's own exits should use
    ``resolve_red_bar_v2_derived_exits``, which runs the stop, trail, structure
    and session-flat rules and reports the moments they actually closed on.
    """
    session_date = (
        trading_date if isinstance(trading_date, date) else date.fromisoformat(trading_date)
    )
    times = tuple(local_times) if local_times is not None else _default_research_exit_times()
    return tuple(
        pd.Timestamp(datetime.combine(session_date, value, tzinfo=INDIA_TZ)).tz_convert("UTC")
        for value in times
    )
