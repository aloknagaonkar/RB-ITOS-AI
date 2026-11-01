import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

from .domain import (
    IST,
    Quote,
    Snapshot,
    StrikePositioningClassification,
    StrikePositioningConfig,
    StrikePositioningResult,
)

POSITIONING_HORIZONS_SECONDS = (300, 900, 1800)


@dataclass(frozen=True)
class PositioningBaselineCandidate:
    observation_id: int
    received_at: datetime
    provider: str
    underlying: str
    expiry: date


def positioning_baseline_window(current: Snapshot, horizon_seconds: int, config: StrikePositioningConfig):
    if horizon_seconds not in POSITIONING_HORIZONS_SECONDS:
        raise ValueError("horizon_seconds must be 300, 900 or 1800")
    target = current.received_at - timedelta(seconds=horizon_seconds)
    return target - timedelta(seconds=config.baseline_tolerance_seconds), target


def select_positioning_baseline(
    current: Snapshot,
    candidates: Iterable[PositioningBaselineCandidate],
    horizon_seconds: int,
    config: StrikePositioningConfig,
) -> PositioningBaselineCandidate | None:
    earliest, target = positioning_baseline_window(current, horizon_seconds, config)
    session_date = current.received_at.astimezone(IST).date()
    eligible = [candidate for candidate in candidates
        if (candidate.provider, candidate.underlying, candidate.expiry)
        == (current.provider, current.underlying, current.expiry)
        and candidate.received_at.astimezone(IST).date() == session_date
        and earliest <= candidate.received_at <= target]
    return max(eligible, key=lambda item: (item.received_at, item.observation_id)) if eligible else None


def positioning_candidate(observation_id: int, snapshot: Snapshot) -> PositioningBaselineCandidate:
    return PositioningBaselineCandidate(
        observation_id, snapshot.received_at, snapshot.provider, snapshot.underlying, snapshot.expiry
    )


def select_strike_window(catalog, center_strike: float, wings: int) -> tuple[float, ...]:
    if type(wings) is not int or wings < 0:
        raise ValueError("wings must be a non-negative integer")
    strikes = sorted({contract.strike for contract in catalog})
    if center_strike not in strikes:
        raise ValueError("center_strike is not present in the current catalog")
    center = strikes.index(center_strike)
    return tuple(strikes[max(0, center - wings):center + wings + 1])


def _usable_number(value, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    if positive and value <= 0:
        return None
    return value


def _raw_ltps(snapshot: Snapshot) -> dict[str, float]:
    result = {}
    chain = snapshot.raw.get("chain") if isinstance(snapshot.raw, dict) else None
    rows = chain.get("data") if isinstance(chain, dict) else None
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        for field in ("call_options", "put_options"):
            option = row.get(field)
            if not isinstance(option, dict) or not isinstance(option.get("market_data"), dict):
                continue
            key = option.get("instrument_key")
            ltp = _usable_number(option["market_data"].get("ltp"), positive=True)
            if isinstance(key, str) and ltp is not None:
                result[key] = float(ltp)
    return result


def quote_ltp(snapshot: Snapshot, quote: Quote, raw_ltps: dict[str, float] | None = None) -> float | None:
    if quote.ltp is not None:
        normalized = _usable_number(quote.ltp, positive=True)
        return float(normalized) if normalized is not None else None
    return (raw_ltps if raw_ltps is not None else _raw_ltps(snapshot)).get(quote.key)


def _classification(price_pct, oi_pct, config):
    if price_pct is None or oi_pct is None:
        return StrikePositioningClassification.UNAVAILABLE
    price_up = price_pct >= config.min_price_change_pct
    price_down = price_pct <= -config.min_price_change_pct
    oi_up = oi_pct >= config.min_oi_change_pct
    oi_down = oi_pct <= -config.min_oi_change_pct
    if price_up and oi_up:
        return StrikePositioningClassification.LONG_BUILDUP
    if price_down and oi_up:
        return StrikePositioningClassification.SHORT_BUILDUP
    if price_down and oi_down:
        return StrikePositioningClassification.LONG_UNWINDING
    if price_up and oi_down:
        return StrikePositioningClassification.SHORT_COVERING
    return StrikePositioningClassification.NEUTRAL


def calculate_strike_positioning(
    observation_id: int,
    configuration_version: int,
    current: Snapshot,
    history: Iterable[tuple[int, Snapshot]],
    horizon_seconds: int,
    config: StrikePositioningConfig,
    selected_strikes: set[float] | None = None,
) -> list[StrikePositioningResult]:
    entries = [(positioning_candidate(identifier, snapshot), snapshot) for identifier, snapshot in history]
    selected = select_positioning_baseline(current, (item[0] for item in entries), horizon_seconds, config)
    baseline = next((item for item in entries if item[0] == selected), None)
    contracts = {
        contract.key: contract for contract in current.catalog
        if selected_strikes is None or contract.strike in selected_strikes
    }
    current_quotes = {quote.key: quote for quote in current.quotes}
    baseline_quotes = {quote.key: quote for quote in baseline[1].quotes} if baseline else {}
    current_raw_ltps = _raw_ltps(current) if any(quote.ltp is None for quote in current.quotes) else {}
    baseline_raw_ltps = _raw_ltps(baseline[1]) if baseline and any(quote.ltp is None for quote in baseline[1].quotes) else {}
    results = []
    for key in sorted(contracts):
        contract = contracts[key]
        current_quote = current_quotes.get(key)
        baseline_quote = baseline_quotes.get(key)
        current_ltp = quote_ltp(current, current_quote, current_raw_ltps) if current_quote else None
        baseline_ltp = quote_ltp(baseline[1], baseline_quote, baseline_raw_ltps) if baseline and baseline_quote else None
        current_oi = current_quote.oi if current_quote else None
        baseline_oi = baseline_quote.oi if baseline_quote else None
        price_change = current_ltp - baseline_ltp if current_ltp is not None and baseline_ltp is not None else None
        price_pct = price_change / baseline_ltp * 100 if price_change is not None and baseline_ltp else None
        oi_change = current_oi - baseline_oi if current_oi is not None and baseline_oi is not None else None
        oi_pct = oi_change / baseline_oi * 100 if oi_change is not None and baseline_oi else None
        classification = _classification(price_pct, oi_pct, config)
        available = baseline is not None and classification != StrikePositioningClassification.UNAVAILABLE
        results.append(StrikePositioningResult(
            observation_id=observation_id,
            configuration_version=configuration_version,
            received_at=current.received_at,
            instrument_key=key,
            strike=contract.strike,
            side=contract.side,
            horizon_seconds=horizon_seconds,
            current_ltp=current_ltp,
            baseline_ltp=baseline_ltp,
            price_change=price_change,
            price_change_pct=price_pct,
            current_oi=current_oi,
            baseline_oi=baseline_oi,
            observed_oi_change=oi_change,
            observed_oi_change_pct=oi_pct,
            baseline_received_at=baseline[1].received_at if baseline else None,
            actual_elapsed_seconds=(current.received_at - baseline[1].received_at).total_seconds() if baseline else None,
            classification=classification,
            status="AVAILABLE" if available else "UNAVAILABLE",
        ))
    return results
