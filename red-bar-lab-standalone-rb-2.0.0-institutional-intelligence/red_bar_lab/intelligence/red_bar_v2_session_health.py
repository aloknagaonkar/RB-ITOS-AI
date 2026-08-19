from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from red_bar_lab.intelligence.market_context import aggregate_completed_5m, completed_candles


@dataclass(frozen=True)
class RedBarV2SessionVwapHealth:
    status: str
    reason: str
    price_source_instrument: str
    rsi_source_instrument: str
    vwap_source_instrument: str
    timeframe: str
    index_rows: int
    futures_rows: int
    aligned_rows: int
    alignment_coverage_pct: float
    positive_volume_rows: int
    index_timestamp: datetime | None
    futures_timestamp: datetime | None
    last_aligned_timestamp: datetime | None
    completed_5m_index_rows: int
    completed_5m_futures_rows: int
    completed_5m_aligned_rows: int
    completed_5m_alignment_coverage_pct: float
    completed_5m_last_aligned_timestamp: datetime | None
    execution_scope: str = "HISTORICAL_REPLAY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "price_source_instrument": self.price_source_instrument,
            "rsi_source_instrument": self.rsi_source_instrument,
            "vwap_source_instrument": self.vwap_source_instrument,
            "timeframe": self.timeframe,
            "index_rows": self.index_rows,
            "futures_rows": self.futures_rows,
            "aligned_rows": self.aligned_rows,
            "alignment_coverage_pct": self.alignment_coverage_pct,
            "positive_volume_rows": self.positive_volume_rows,
            "index_timestamp": self.index_timestamp.isoformat() if self.index_timestamp else None,
            "futures_timestamp": self.futures_timestamp.isoformat() if self.futures_timestamp else None,
            "last_aligned_timestamp": (
                self.last_aligned_timestamp.isoformat() if self.last_aligned_timestamp else None
            ),
            "completed_5m_index_rows": self.completed_5m_index_rows,
            "completed_5m_futures_rows": self.completed_5m_futures_rows,
            "completed_5m_aligned_rows": self.completed_5m_aligned_rows,
            "completed_5m_alignment_coverage_pct": self.completed_5m_alignment_coverage_pct,
            "completed_5m_last_aligned_timestamp": (
                self.completed_5m_last_aligned_timestamp.isoformat()
                if self.completed_5m_last_aligned_timestamp else None
            ),
            "execution_scope": self.execution_scope,
        }


def _last_timestamp(frame: pd.DataFrame) -> datetime | None:
    if frame.empty:
        return None
    return pd.Timestamp(frame.index[-1]).to_pydatetime()


def _latest_source_timestamp(candles: pd.DataFrame | None) -> pd.Timestamp | None:
    if candles is None or candles.empty:
        return None
    values = pd.to_datetime(
        candles["timestamp"] if "timestamp" in candles.columns else candles.index,
        errors="coerce",
    )
    valid = values[~pd.isna(values)]
    return pd.Timestamp(valid.max()) if len(valid) else None


def build_session_vwap_source_health(
    index_candles: pd.DataFrame,
    futures_candles: pd.DataFrame,
    *,
    instrument_key: str,
    vwap_instrument_key: str,
) -> RedBarV2SessionVwapHealth:
    """Measure the full completed session at both one- and five-minute levels."""
    latest_candidates = [
        value
        for value in (
            _latest_source_timestamp(index_candles),
            _latest_source_timestamp(futures_candles),
        )
        if value is not None
    ]
    evaluation_time = (
        max(latest_candidates) + pd.Timedelta(minutes=1)
        if latest_candidates
        else pd.Timestamp.now(tz="UTC")
    )

    index_1m = completed_candles(
        index_candles, evaluation_time=evaluation_time, interval_minutes=1
    ) if index_candles is not None and not index_candles.empty else pd.DataFrame()
    futures_1m = completed_candles(
        futures_candles, evaluation_time=evaluation_time, interval_minutes=1
    ) if futures_candles is not None and not futures_candles.empty else pd.DataFrame()

    common_1m = index_1m.index.intersection(futures_1m.index)
    index_rows = len(index_1m)
    futures_rows = len(futures_1m)
    aligned_rows = len(common_1m)
    coverage_1m = round(aligned_rows / index_rows * 100.0, 2) if index_rows else 0.0
    positive_volume_rows = (
        int((pd.to_numeric(futures_1m["volume"], errors="coerce") > 0).sum())
        if futures_rows else 0
    )

    index_5m = aggregate_completed_5m(index_1m) if index_rows else pd.DataFrame()
    futures_5m = aggregate_completed_5m(futures_1m) if futures_rows else pd.DataFrame()
    common_5m = index_5m.index.intersection(futures_5m.index)
    coverage_5m = (
        round(len(common_5m) / len(index_5m) * 100.0, 2) if len(index_5m) else 0.0
    )

    if not index_rows:
        status, reason = "BLOCKED", "INDEX_CONTEXT_UNAVAILABLE"
    elif not futures_rows:
        status, reason = "BLOCKED", "FUTURES_CONTEXT_UNAVAILABLE"
    elif positive_volume_rows == 0:
        status, reason = "BLOCKED", "FUTURES_VOLUME_UNAVAILABLE"
    elif aligned_rows != index_rows:
        status, reason = "BLOCKED", "INCOMPLETE_1M_TIMESTAMP_ALIGNMENT"
    elif len(common_5m) != len(index_5m):
        status, reason = "BLOCKED", "INCOMPLETE_5M_TIMESTAMP_ALIGNMENT"
    else:
        status, reason = "READY", "FULL_SESSION_TIMESTAMP_ALIGNMENT"

    return RedBarV2SessionVwapHealth(
        status=status,
        reason=reason,
        price_source_instrument=instrument_key,
        rsi_source_instrument=instrument_key,
        vwap_source_instrument=vwap_instrument_key,
        timeframe="SESSION_1M_5M",
        index_rows=index_rows,
        futures_rows=futures_rows,
        aligned_rows=aligned_rows,
        alignment_coverage_pct=coverage_1m,
        positive_volume_rows=positive_volume_rows,
        index_timestamp=_last_timestamp(index_1m),
        futures_timestamp=_last_timestamp(futures_1m),
        last_aligned_timestamp=(
            pd.Timestamp(common_1m[-1]).to_pydatetime() if len(common_1m) else None
        ),
        completed_5m_index_rows=len(index_5m),
        completed_5m_futures_rows=len(futures_5m),
        completed_5m_aligned_rows=len(common_5m),
        completed_5m_alignment_coverage_pct=coverage_5m,
        completed_5m_last_aligned_timestamp=(
            pd.Timestamp(common_5m[-1]).to_pydatetime() if len(common_5m) else None
        ),
    )
