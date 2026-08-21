from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

import math

OPTION_RESEARCH_POLICY_VERSION = "option-research-features-v1"


@dataclass(frozen=True)
class LiquidityEligibility:
    eligible: bool
    reason_codes: tuple[str, ...]
    spread_pct: float | None
    open_interest: float
    volume: float
    policy_version: str = OPTION_RESEARCH_POLICY_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _optional_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def assess_option_liquidity(
    row: Mapping[str, Any],
    *,
    min_open_interest: float = 1000.0,
    min_volume: float = 100.0,
    max_spread_pct: float = 5.0,
) -> LiquidityEligibility:
    bid = _optional_number(row.get("bid") or row.get("best_bid"))
    ask = _optional_number(row.get("ask") or row.get("best_ask"))
    ltp = _optional_number(row.get("ltp") or row.get("last_price"))
    oi = _number(row.get("open_interest") or row.get("oi"))
    volume = _number(row.get("volume") or row.get("traded_volume"))

    spread_pct = None
    if bid is not None and ask is not None and ask >= bid and (bid + ask) > 0:
        spread_pct = (ask - bid) / ((ask + bid) / 2.0) * 100.0
    elif ltp is None or ltp <= 0:
        spread_pct = None

    reasons: list[str] = []
    if oi < min_open_interest:
        reasons.append("OPEN_INTEREST_BELOW_MINIMUM")
    if volume < min_volume:
        reasons.append("VOLUME_BELOW_MINIMUM")
    if spread_pct is None:
        reasons.append("SPREAD_UNAVAILABLE")
    elif spread_pct > max_spread_pct:
        reasons.append("SPREAD_TOO_WIDE")

    return LiquidityEligibility(
        eligible=not reasons,
        reason_codes=tuple(reasons),
        spread_pct=spread_pct,
        open_interest=oi,
        volume=volume,
    )


def minmax_normalize(values: Sequence[object]) -> tuple[float, ...]:
    numbers = tuple(_number(value) for value in values)
    if not numbers:
        return ()
    low, high = min(numbers), max(numbers)
    if high == low:
        return tuple(0.5 for _ in numbers)
    return tuple((value - low) / (high - low) for value in numbers)


def normalize_option_features(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    source = [dict(row) for row in rows]
    oi_norm = minmax_normalize([row.get("open_interest") or row.get("oi") for row in source])
    volume_norm = minmax_normalize([row.get("volume") or row.get("traded_volume") for row in source])
    oi_change_norm = minmax_normalize([row.get("oi_change") or row.get("open_interest_change") for row in source])

    result = []
    for index, row in enumerate(source):
        result.append(
            {
                **row,
                "open_interest_normalized": oi_norm[index],
                "volume_normalized": volume_norm[index],
                "oi_change_normalized": oi_change_norm[index],
                "normalization_policy_version": OPTION_RESEARCH_POLICY_VERSION,
            }
        )
    return tuple(result)


def aggregate_option_chain_without_double_counting(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, float]:
    """Aggregate each contract exactly once by contract key.

    A duplicated contract may appear in multiple display/ranking buckets. The
    latest occurrence replaces the prior occurrence instead of adding volume or
    OI twice.
    """

    unique: dict[tuple[str, float, str], dict[str, Any]] = {}
    for original in rows:
        row = dict(original)
        contract = str(row.get("instrument_key") or row.get("contract") or row.get("symbol") or "")
        strike = _number(row.get("strike"))
        option_type = str(row.get("option_type") or row.get("type") or "").upper()
        key = (contract, strike, option_type)
        unique[key] = row

    return {
        "contract_count": float(len(unique)),
        "total_open_interest": sum(_number(row.get("open_interest") or row.get("oi")) for row in unique.values()),
        "total_volume": sum(_number(row.get("volume") or row.get("traded_volume")) for row in unique.values()),
        "total_oi_change": sum(_number(row.get("oi_change") or row.get("open_interest_change")) for row in unique.values()),
    }


def rank_liquid_option_candidates(
    rows: Iterable[Mapping[str, Any]],
    *,
    min_open_interest: float = 1000.0,
    min_volume: float = 100.0,
    max_spread_pct: float = 5.0,
) -> tuple[dict[str, Any], ...]:
    normalized = normalize_option_features(rows)
    ranked = []
    for row in normalized:
        liquidity = assess_option_liquidity(
            row,
            min_open_interest=min_open_interest,
            min_volume=min_volume,
            max_spread_pct=max_spread_pct,
        )
        if not liquidity.eligible:
            continue
        spread_score = max(0.0, 1.0 - float(liquidity.spread_pct or 0.0) / max_spread_pct)
        research_score = (
            0.40 * float(row["open_interest_normalized"])
            + 0.35 * float(row["volume_normalized"])
            + 0.15 * float(row["oi_change_normalized"])
            + 0.10 * spread_score
        )
        ranked.append(
            {
                **row,
                "liquidity_eligible": True,
                "liquidity_reason_codes": (),
                "spread_pct": liquidity.spread_pct,
                "research_rank_score": round(research_score, 6),
                "authority": "OBSERVATIONAL_ONLY",
                "policy_version": OPTION_RESEARCH_POLICY_VERSION,
            }
        )
    ranked.sort(key=lambda row: (-float(row["research_rank_score"]), str(row.get("instrument_key") or row.get("symbol") or "")))
    return tuple(ranked)


__all__ = [
    "OPTION_RESEARCH_POLICY_VERSION",
    "LiquidityEligibility",
    "assess_option_liquidity",
    "minmax_normalize",
    "normalize_option_features",
    "aggregate_option_chain_without_double_counting",
    "rank_liquid_option_candidates",
]
