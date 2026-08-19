from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from red_bar_lab.intelligence.market_context import (
    MarketIndicatorSnapshot,
    Timeframe,
    add_market_indicators,
    aggregate_completed_5m,
    completed_candles,
    session_vwap,
)


@dataclass(frozen=True)
class RedBarV2VwapSourceHealth:
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
                self.last_aligned_timestamp.isoformat()
                if self.last_aligned_timestamp else None
            ),
            "execution_scope": self.execution_scope,
        }


@dataclass(frozen=True)
class RedBarV2FuturesSnapshot(MarketIndicatorSnapshot):
    vwap_comparison_price: float
    vwap_source_instrument_key: str
    vwap_source_timestamp: datetime
    vwap_source_type: str = "NIFTY_FUTURES"


def _context_frame(
    candles: pd.DataFrame,
    *,
    timeframe: Timeframe,
    evaluation_time: datetime | pd.Timestamp,
) -> pd.DataFrame:
    completed = completed_candles(
        candles,
        evaluation_time=evaluation_time,
        interval_minutes=1,
    )
    if timeframe == "1M":
        return completed
    if timeframe == "5M":
        return aggregate_completed_5m(completed) if not completed.empty else completed
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def _normalise_expected(
    timestamp: pd.Timestamp,
    expected_timestamp: datetime | pd.Timestamp | None,
) -> pd.Timestamp | None:
    if expected_timestamp is None:
        return None
    expected = pd.Timestamp(expected_timestamp)
    if timestamp.tzinfo is not None and expected.tzinfo is None:
        expected = expected.tz_localize(timestamp.tzinfo)
    elif timestamp.tzinfo is None and expected.tzinfo is not None:
        expected = expected.tz_localize(None)
    return expected


def build_red_bar_v2_futures_snapshot(
    index_candles: pd.DataFrame,
    futures_candles: pd.DataFrame,
    *,
    instrument_key: str,
    vwap_instrument_key: str,
    timeframe: Timeframe,
    evaluation_time: datetime | pd.Timestamp,
    expected_timestamp: datetime | pd.Timestamp | None = None,
    rsi_period: int = 14,
    bullish_threshold: float = 55.0,
    bearish_threshold: float = 45.0,
) -> tuple[RedBarV2FuturesSnapshot | None, RedBarV2VwapSourceHealth]:
    """Build aligned index-RSI and futures-VWAP context without lookahead."""
    index_frame = _context_frame(
        index_candles,
        timeframe=timeframe,
        evaluation_time=evaluation_time,
    )
    futures_frame = _context_frame(
        futures_candles,
        timeframe=timeframe,
        evaluation_time=evaluation_time,
    )

    index_rows = len(index_frame)
    futures_rows = len(futures_frame)
    index_timestamp = (
        pd.Timestamp(index_frame.index[-1]).to_pydatetime()
        if index_rows else None
    )
    futures_timestamp = (
        pd.Timestamp(futures_frame.index[-1]).to_pydatetime()
        if futures_rows else None
    )
    common = index_frame.index.intersection(futures_frame.index)
    aligned_rows = len(common)
    coverage = round(aligned_rows / index_rows * 100.0, 2) if index_rows else 0.0
    positive_volume_rows = (
        int((pd.to_numeric(futures_frame["volume"], errors="coerce") > 0).sum())
        if futures_rows else 0
    )
    last_aligned = (
        pd.Timestamp(common[-1]).to_pydatetime() if aligned_rows else None
    )

    def health(status: str, reason: str) -> RedBarV2VwapSourceHealth:
        return RedBarV2VwapSourceHealth(
            status=status,
            reason=reason,
            price_source_instrument=instrument_key,
            rsi_source_instrument=instrument_key,
            vwap_source_instrument=vwap_instrument_key,
            timeframe=timeframe,
            index_rows=index_rows,
            futures_rows=futures_rows,
            aligned_rows=aligned_rows,
            alignment_coverage_pct=coverage,
            positive_volume_rows=positive_volume_rows,
            index_timestamp=index_timestamp,
            futures_timestamp=futures_timestamp,
            last_aligned_timestamp=last_aligned,
        )

    if index_frame.empty:
        return None, health("BLOCKED", "INDEX_CONTEXT_UNAVAILABLE")
    if futures_frame.empty:
        return None, health("BLOCKED", "FUTURES_CONTEXT_UNAVAILABLE")
    if positive_volume_rows == 0:
        return None, health("BLOCKED", "FUTURES_VOLUME_UNAVAILABLE")

    index_latest = pd.Timestamp(index_frame.index[-1])
    futures_latest = pd.Timestamp(futures_frame.index[-1])
    if index_latest != futures_latest:
        return None, health("BLOCKED", "FUTURES_TIMESTAMP_MISMATCH")

    expected = _normalise_expected(index_latest, expected_timestamp)
    if expected is not None and index_latest != expected:
        return None, health("BLOCKED", "STALE_CONTEXT")

    index_enriched = add_market_indicators(index_frame, rsi_period=rsi_period)
    futures_vwap = session_vwap(futures_frame)
    index_latest_row = index_enriched.iloc[-1]
    futures_latest_row = futures_frame.iloc[-1]

    rsi_raw = index_latest_row["rsi"]
    vwap_raw = futures_vwap.iloc[-1]
    if pd.isna(rsi_raw):
        return None, health("BLOCKED", "RSI_HISTORY_INSUFFICIENT")
    if pd.isna(vwap_raw):
        return None, health("BLOCKED", "FUTURES_VWAP_UNAVAILABLE")

    rsi_value = float(rsi_raw)
    vwap_value = float(vwap_raw)
    index_close = float(index_latest_row["close"])
    futures_close = float(futures_latest_row["close"])
    if futures_close > vwap_value:
        price_vs_vwap = "ABOVE"
    elif futures_close < vwap_value:
        price_vs_vwap = "BELOW"
    else:
        price_vs_vwap = "AT"

    bullish = rsi_value > bullish_threshold and futures_close > vwap_value
    bearish = rsi_value < bearish_threshold and futures_close < vwap_value
    timestamp = index_latest.to_pydatetime()
    snapshot = RedBarV2FuturesSnapshot(
        instrument_key=instrument_key,
        trading_date=timestamp.date().isoformat(),
        timeframe=timeframe,
        candle_timestamp=timestamp,
        candle_open=float(index_latest_row["open"]),
        candle_high=float(index_latest_row["high"]),
        candle_low=float(index_latest_row["low"]),
        candle_close=index_close,
        candle_volume=float(index_latest_row["volume"]),
        rsi_period=rsi_period,
        rsi_value=rsi_value,
        vwap_value=vwap_value,
        price_vs_vwap=price_vs_vwap,
        bullish_context=bool(bullish),
        bearish_context=bool(bearish),
        source="RED_BAR_V2_INDEX_RSI_FUTURES_VWAP_V1",
        data_quality="VALID",
        fresh=True,
        vwap_comparison_price=futures_close,
        vwap_source_instrument_key=vwap_instrument_key,
        vwap_source_timestamp=futures_latest.to_pydatetime(),
    )
    return snapshot, health("READY", "FULL_TIMESTAMP_ALIGNMENT")
