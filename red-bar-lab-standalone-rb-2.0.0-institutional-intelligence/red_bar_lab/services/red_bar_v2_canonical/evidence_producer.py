from __future__ import annotations

from typing import Mapping

from .exceptions import LegacyMappingError
from .models import LegacyV2DecisionEvidence


def _required(source: object, name: str) -> object:
    value = getattr(source, name, None)
    if value is None:
        raise LegacyMappingError(f"authoritative source is missing {name}")
    return value


def _optional_number(source: object, name: str) -> float | None:
    """Read an informational numeric field that is legitimately absent.

    Used for RSI, which is NaN for the whole Wilder RSI(14) warm-up and does
    not gate admission. ``_required`` would abort the evidence build instead.
    """
    value = getattr(source, name, None)
    return None if value is None else float(value)


def build_legacy_v2_decision_evidence(
    *,
    underlying_instrument_key: str,
    futures_instrument_key: str,
    direction_decision: object,
    reference: object,
    index_context: object,
    futures_context: object,
    bullish_rsi_threshold: float = 55.0,
    bearish_rsi_threshold: float = 45.0,
) -> LegacyV2DecisionEvidence:
    """Expose the exact values already used by the futures-aware V2 decision."""
    timeframe = str(_required(futures_context, "timeframe")).upper()
    evaluation_timeframe = "1m" if timeframe == "1M" else "5m" if timeframe == "5M" else None
    if evaluation_timeframe is None:
        raise LegacyMappingError(f"unsupported legacy evidence timeframe: {timeframe!r}")

    snapshot_underlying = str(_required(futures_context, "instrument_key"))
    snapshot_futures = str(_required(futures_context, "vwap_source_instrument_key"))
    if snapshot_underlying != underlying_instrument_key:
        raise LegacyMappingError("futures snapshot underlying instrument disagrees with requested underlying")
    if snapshot_futures != futures_instrument_key:
        raise LegacyMappingError("futures snapshot VWAP source disagrees with requested futures instrument")

    return LegacyV2DecisionEvidence(
        underlying_instrument_key=underlying_instrument_key,
        futures_instrument_key=futures_instrument_key,
        evaluation_timestamp=_required(direction_decision, "context_timestamp"),
        evaluation_timeframe=evaluation_timeframe,
        index_close=float(_required(index_context, "candle_close")),
        rsi_value=_optional_number(direction_decision, "rsi_value"),
        bullish_rsi_threshold=bullish_rsi_threshold,
        bearish_rsi_threshold=bearish_rsi_threshold,
        futures_comparison_price=float(_required(futures_context, "vwap_comparison_price")),
        futures_vwap=float(_required(direction_decision, "vwap_value")),
        futures_volume=float(_required(futures_context, "vwap_source_volume")),
        futures_fresh=bool(_required(direction_decision, "context_fresh")),
        index_context_timestamp=_required(index_context, "candle_timestamp"),
        futures_source_timestamp=_required(futures_context, "vwap_source_timestamp"),
        reference_id=(
            f"RBV2-REF-{_required(reference, 'trading_date')}-"
            f"{_required(reference, 'reference_timestamp').isoformat()}"
        ),
        reference_timestamp=_required(reference, "reference_timestamp"),
        reference_high=float(_required(reference, "reference_high")),
        reference_low=float(_required(reference, "reference_low")),
        reference_midpoint=float(_required(reference, "midpoint")),
        reference_source=str(getattr(reference, "level_type", "NEXT_RED_CANDLE")),
    )


def evidence_to_event_details(evidence: LegacyV2DecisionEvidence) -> dict[str, object]:
    """Return JSON-friendly evidence fields for ReplayEvent.details."""
    return {
        "underlying_instrument_key": evidence.underlying_instrument_key,
        "futures_instrument_key": evidence.futures_instrument_key,
        "evaluation_timeframe": evidence.evaluation_timeframe,
        "index_close": evidence.index_close,
        "rsi_value": evidence.rsi_value,
        "bullish_rsi_threshold": evidence.bullish_rsi_threshold,
        "bearish_rsi_threshold": evidence.bearish_rsi_threshold,
        "futures_comparison_price": evidence.futures_comparison_price,
        "futures_vwap": evidence.futures_vwap,
        "futures_volume": evidence.futures_volume,
        "futures_fresh": evidence.futures_fresh,
        "index_context_timestamp": evidence.index_context_timestamp.isoformat(),
        "futures_source_timestamp": evidence.futures_source_timestamp.isoformat(),
        "reference_id": evidence.reference_id,
        "reference_timestamp": evidence.reference_timestamp.isoformat(),
        "reference_high": evidence.reference_high,
        "reference_low": evidence.reference_low,
        "reference_midpoint": evidence.reference_midpoint,
        "reference_source": evidence.reference_source,
    }


def evidence_from_event_details(details: Mapping[str, object]) -> LegacyV2DecisionEvidence:
    """Reconstruct strict evidence from a real ReplayEvent.details mapping."""
    from datetime import datetime

    def text(name: str) -> str:
        value = details.get(name)
        if not isinstance(value, str) or not value.strip():
            raise LegacyMappingError(f"event evidence {name} must be a non-empty string")
        return value

    def timestamp(name: str) -> datetime:
        try:
            value = datetime.fromisoformat(text(name).replace("Z", "+00:00"))
        except ValueError as exc:
            raise LegacyMappingError(f"event evidence {name} must be an ISO datetime") from exc
        if value.tzinfo is None or value.utcoffset() is None:
            raise LegacyMappingError(f"event evidence {name} must be timezone-aware")
        return value

    def number(name: str) -> float:
        value = details.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise LegacyMappingError(f"event evidence {name} must be numeric")
        return float(value)

    def optional_number(name: str) -> float | None:
        """Accept an absent or explicitly null informational reading."""
        if details.get(name) is None:
            return None
        return number(name)

    fresh = details.get("futures_fresh")
    if not isinstance(fresh, bool):
        raise LegacyMappingError("event evidence futures_fresh must be a bool")
    return LegacyV2DecisionEvidence(
        underlying_instrument_key=text("underlying_instrument_key"),
        futures_instrument_key=text("futures_instrument_key"),
        evaluation_timestamp=timestamp("context_timestamp") if "context_timestamp" in details else timestamp("futures_source_timestamp"),
        evaluation_timeframe=text("evaluation_timeframe"),
        index_close=number("index_close"),
        rsi_value=optional_number("rsi_value"),
        bullish_rsi_threshold=number("bullish_rsi_threshold"),
        bearish_rsi_threshold=number("bearish_rsi_threshold"),
        futures_comparison_price=number("futures_comparison_price"),
        futures_vwap=number("futures_vwap"),
        futures_volume=number("futures_volume"),
        futures_fresh=fresh,
        index_context_timestamp=timestamp("index_context_timestamp"),
        futures_source_timestamp=timestamp("futures_source_timestamp"),
        reference_id=text("reference_id"),
        reference_timestamp=timestamp("reference_timestamp"),
        reference_high=number("reference_high"),
        reference_low=number("reference_low"),
        reference_midpoint=number("reference_midpoint"),
        reference_source=text("reference_source"),
    )
