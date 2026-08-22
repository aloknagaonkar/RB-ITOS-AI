from __future__ import annotations

"""Additive contract-quality corrections for observational market evidence.

This installer preserves the stable market-evidence module while correcting
its IV availability rule and ATM-distance derivation.  It can be removed once
the stable module is consolidated in a later cleanup release.
"""

from statistics import median
from typing import Mapping


def _number(value: object) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def robust_strike_step(rows: list[Mapping[str, object]]) -> float | None:
    """Return the median positive adjacent strike interval.

    A single anomalous strike must not redefine the distance of every contract.
    """
    strikes = sorted(
        {
            value
            for row in rows
            if (value := _number(row.get("strike"))) is not None
        }
    )
    differences = [
        right - left
        for left, right in zip(strikes, strikes[1:])
        if right > left
    ]
    return float(median(differences)) if differences else None


def robust_distance_steps(
    row: Mapping[str, object],
    *,
    step: float | None,
) -> int:
    """Prefer persisted strike offsets, then derive from the robust interval."""
    explicit_offset = _number(row.get("strike_offset_steps"))
    if explicit_offset is not None:
        return max(0, int(round(abs(explicit_offset))))

    strike = _number(row.get("strike"))
    atm = _number(row.get("atm_strike"))
    if strike is not None and atm is not None and step not in (None, 0):
        return max(0, int(round(abs(strike - atm) / float(step))))

    rank = int(_number(row.get("distance_rank")) or 1)
    return max(0, rank // 2)


def strict_contract_eligibility(
    row: Mapping[str, object],
) -> tuple[bool, str]:
    """Apply one symmetric CE/PE quality contract, including mandatory IV."""
    price = _number(row.get("current_price"))
    bid = _number(row.get("bid"))
    ask = _number(row.get("ask"))
    supplied_spread = _number(row.get("spread"))
    iv = _number(row.get("iv"))
    volume = _number(row.get("volume"))
    oi = _number(row.get("oi"))

    if price is None or price <= 0:
        return False, "MISSING_PRICE"
    if volume is None or volume <= 0 or oi is None or oi <= 0:
        return False, "ILLIQUID"
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return False, "QUOTE_UNAVAILABLE"
    if ask < bid:
        return False, "INVALID_QUOTE"

    midpoint = (bid + ask) / 2.0
    if midpoint <= 0:
        return False, "INVALID_QUOTE"
    effective_spread = max(ask - bid, supplied_spread or 0.0)
    if effective_spread / midpoint * 100.0 > 3.0:
        return False, "WIDE_SPREAD"

    if iv is None:
        return False, "IV_UNAVAILABLE"
    if not 1.0 <= iv <= 150.0:
        return False, "IV_OUTLIER"
    return True, "ELIGIBLE"


def install() -> None:
    from red_bar_lab.services import market_evidence_engine

    market_evidence_engine._strike_step = robust_strike_step
    market_evidence_engine._distance_steps = robust_distance_steps
    market_evidence_engine._eligible = strict_contract_eligibility


__all__ = [
    "install",
    "robust_distance_steps",
    "robust_strike_step",
    "strict_contract_eligibility",
]
