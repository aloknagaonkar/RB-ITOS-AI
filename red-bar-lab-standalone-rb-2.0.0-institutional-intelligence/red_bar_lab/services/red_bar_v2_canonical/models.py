from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from red_bar_lab.domain.red_bar_v2 import (
    ContextStatus,
    Direction,
    EntryType,
    OptionSide,
    RedBarV2Decision,
    RedBarV2InputReadiness,
    RedBarV2SignalBundle,
    TrendStrength,
)


@dataclass(frozen=True, slots=True)
class LegacyV2MarketMetadata:
    """Event-time market metadata already produced by the legacy V2 flow."""

    strategy_version: str
    trading_date: date
    evaluated_at: datetime
    source_name: str
    source_version: str
    context_status: ContextStatus
    maximum_age_seconds: int
    latest_index_1m: datetime | None
    latest_index_5m: datetime | None
    latest_futures_1m: datetime | None
    latest_futures_5m: datetime | None
    underlying_instrument_key: str
    futures_instrument_key: str | None
    futures_expiry: date | None
    futures_volume_available: bool
    futures_vwap_available: bool
    reason_code: str
    reason: str
    reference_id: str | None = None
    reference_timestamp: datetime | None = None
    reference_high: float | None = None
    reference_low: float | None = None
    reference_midpoint: float | None = None
    reference_source: str | None = None


@dataclass(frozen=True, slots=True)
class LegacyV2DecisionEvidence:
    """Complete numeric evidence used by one authoritative legacy decision."""

    underlying_instrument_key: str
    futures_instrument_key: str
    evaluation_timestamp: datetime
    evaluation_timeframe: str
    index_close: float
    # RSI is informational under the futures gates, and Wilder RSI(14) is NaN
    # for the first 15 completed candles. A required float here would make the
    # whole evidence bundle unbuildable during the warm-up and take the
    # decision down with it, so a warm-up reading is carried as None.
    rsi_value: float | None
    bullish_rsi_threshold: float
    bearish_rsi_threshold: float
    futures_comparison_price: float
    # None on a working-reference entry. That path is judged against the deputy
    # candle governing the space outside the red bar's band and consults no VWAP,
    # so a required float here would make every working entry unbuildable -- the
    # same failure mode the RSI warm-up had above.
    futures_vwap: float | None
    futures_volume: float
    futures_fresh: bool
    index_context_timestamp: datetime
    futures_source_timestamp: datetime
    reference_id: str
    reference_timestamp: datetime
    reference_high: float
    reference_low: float
    reference_midpoint: float
    reference_source: str


@dataclass(frozen=True, slots=True)
class RedBarV2CanonicalResolution:
    """In-memory canonical representation of one legacy V2 resolution."""

    section_1: RedBarV2InputReadiness
    section_2: RedBarV2Decision
    section_3: RedBarV2SignalBundle | None
    source_replay_id: str
    resolved_at: datetime


@dataclass(frozen=True, slots=True)
class RedBarV2ParityResult:
    """Read-only comparison between legacy and canonical outcomes."""

    matches: bool
    mismatches: tuple[str, ...]
    legacy_direction: str | None
    canonical_direction: Direction | None
    legacy_option_side: str | None
    canonical_option_side: OptionSide | None
    legacy_allowed: bool | None
    canonical_allowed: bool
    legacy_entry_type: str | None
    canonical_entry_type: EntryType | None
    legacy_timeframe: str | None
    canonical_timeframe: str
    legacy_trend_strength: str | None
    canonical_trend_strength: TrendStrength | None
    legacy_admission_code: str | None
    canonical_admission_code: str
