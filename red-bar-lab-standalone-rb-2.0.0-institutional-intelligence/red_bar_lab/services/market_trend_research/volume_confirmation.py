from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping, Sequence


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if isfinite(result) else None


@dataclass(frozen=True, slots=True)
class VolumeConfirmationCheck:
    check: str
    live_value: str
    required: str
    status: str
    points: float


@dataclass(frozen=True, slots=True)
class VolumeConfirmation:
    score: float
    maximum_score: float
    side: str
    status: str
    contract: str | None
    checks: tuple[VolumeConfirmationCheck, ...]
    authority: str = "OBSERVATIONAL_ONLY"

    @property
    def interpretation(self) -> str:
        if self.side not in {"CE", "PE"}:
            return "Waiting for a directional CE/PE research preference"
        return (
            f"{self.contract or self.side}; observational volume confirmation "
            f"{self.score:.0f}/{self.maximum_score:.0f}"
        )


@dataclass(frozen=True, slots=True)
class VolumeComparison:
    """Independent CE/PE participation comparison with no trading authority."""

    ce: VolumeConfirmation
    pe: VolumeConfirmation
    direction: str
    status: str
    interpretation: str
    authority: str = "OBSERVATIONAL_ONLY"


def _representative(
    rows: Sequence[Mapping[str, object]],
    *,
    side: str,
    expiry: str,
    selected_strikes: frozenset[float],
) -> Mapping[str, object] | None:
    eligible = []
    for row in rows:
        strike = _number(row.get("strike"))
        if (
            str(row.get("option_type") or "").upper() == side
            and str(row.get("expiry") or "") == expiry
            and strike is not None
            and strike in selected_strikes
        ):
            eligible.append(row)
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda row: (
            _number(row.get("option_relative_volume")) or -1.0,
            _number(row.get("interval_volume")) or -1.0,
        ),
    )


def calculate_volume_confirmation(
    option_rows: Sequence[Mapping[str, object]],
    *,
    preferred_side: str,
    selected_expiry: str,
    selected_strikes: frozenset[float],
    futures_relative_volume: float | None,
) -> VolumeConfirmation:
    """Score participation without owning admission or execution authority."""
    side = preferred_side.upper()
    if side not in {"CE", "PE"}:
        return VolumeConfirmation(0.0, 20.0, "WAIT", "WAIT", None, ())
    selected = _representative(
        option_rows,
        side=side,
        expiry=selected_expiry,
        selected_strikes=selected_strikes,
    )
    if selected is None:
        return VolumeConfirmation(0.0, 20.0, side, "INCOMPLETE", None, ())

    rvol = _number(selected.get("option_relative_volume"))
    interval_volume = _number(selected.get("interval_volume"))
    premium_change = _number(selected.get("premium_change_from_previous_refresh_pct"))
    oi_change = _number(selected.get("oi_change_from_previous_refresh"))
    price = _number(selected.get("current_price"))
    vwap = _number(selected.get("vwap"))
    futures_rvol = _number(futures_relative_volume)
    opposite_side = "PE" if side == "CE" else "CE"
    opposite = _representative(
        option_rows,
        side=opposite_side,
        expiry=selected_expiry,
        selected_strikes=selected_strikes,
    )
    opposite_premium = _number(opposite.get("premium_change_from_previous_refresh_pct")) if opposite is not None else None
    opposite_oi = _number(opposite.get("oi_change_from_previous_refresh")) if opposite is not None else None

    option_volume_pass = rvol is not None and rvol >= 1.5
    long_buildup = premium_change is not None and premium_change > 0 and oi_change is not None and oi_change > 0
    above_vwap = price is not None and vwap is not None and price > vwap
    futures_pass = futures_rvol is not None and futures_rvol >= 1.2
    opposite_writing = opposite_premium is not None and opposite_premium < 0 and opposite_oi is not None and opposite_oi > 0
    checks = (
        VolumeConfirmationCheck("Selected option interval volume", "Not available" if interval_volume is None else f"{interval_volume:,.0f}", "Observation", "AVAILABLE" if interval_volume is not None else "MISSING", 0.0),
        VolumeConfirmationCheck("Selected option relative volume", "Not available" if rvol is None else f"{rvol:.2f}", ">= 1.50", "PASS" if option_volume_pass else "WAIT" if rvol is None else "FAIL", 6.0 if option_volume_pass else 0.0),
        VolumeConfirmationCheck("Premium and OI buildup", "Not available" if premium_change is None or oi_change is None else f"Premium {premium_change:+.2f}%; OI {oi_change:+,.0f}", "Selected-side long buildup", "PASS" if long_buildup else "WAIT" if premium_change is None or oi_change is None else "FAIL", 5.0 if long_buildup else 0.0),
        VolumeConfirmationCheck("Option price versus VWAP", "Not available" if price is None or vwap is None else f"{price:.2f} vs {vwap:.2f}", "Price above VWAP", "PASS" if above_vwap else "WAIT" if price is None or vwap is None else "FAIL", 4.0 if above_vwap else 0.0),
        VolumeConfirmationCheck("NIFTY futures relative volume", "Not available" if futures_rvol is None else f"{futures_rvol:.2f}", ">= 1.20", "PASS" if futures_pass else "WAIT" if futures_rvol is None else "FAIL", 3.0 if futures_pass else 0.0),
        VolumeConfirmationCheck("Opposite-side writing", "Not available" if opposite_premium is None or opposite_oi is None else f"{opposite_side} premium {opposite_premium:+.2f}%; OI {opposite_oi:+,.0f}", "Premium down and OI up", "PASS" if opposite_writing else "WAIT" if opposite_premium is None or opposite_oi is None else "FAIL", 2.0 if opposite_writing else 0.0),
    )
    score = sum(check.points for check in checks)
    required_missing = rvol is None or premium_change is None or oi_change is None
    status = "INCOMPLETE" if required_missing else "CONFIRMED" if score >= 15.0 else "PARTIAL_CONFIRMATION" if score >= 10.0 else "NOT_CONFIRMED"
    return VolumeConfirmation(score, 20.0, side, status, str(selected.get("tradingsymbol") or selected.get("instrument_key") or side), checks)


def compare_volume_confirmation(
    option_rows: Sequence[Mapping[str, object]],
    *,
    selected_expiry: str,
    selected_strikes: frozenset[float],
    futures_relative_volume: float | None,
    minimum_lean_score: float = 10.0,
    minimum_score_gap: float = 3.0,
) -> VolumeComparison:
    """Evaluate both option sides even when PCR has no directional preference."""
    ce = calculate_volume_confirmation(option_rows, preferred_side="CE", selected_expiry=selected_expiry, selected_strikes=selected_strikes, futures_relative_volume=futures_relative_volume)
    pe = calculate_volume_confirmation(option_rows, preferred_side="PE", selected_expiry=selected_expiry, selected_strikes=selected_strikes, futures_relative_volume=futures_relative_volume)
    if ce.status == "INCOMPLETE" or pe.status == "INCOMPLETE":
        return VolumeComparison(ce, pe, "WAIT", "INCOMPLETE", "CE and PE volume evidence must both be available for comparison")
    gap = ce.score - pe.score
    winner = ce if gap > 0 else pe
    if winner.score < minimum_lean_score or abs(gap) < minimum_score_gap:
        return VolumeComparison(ce, pe, "BALANCED", "OBSERVATIONAL", f"No material volume edge; score gap {abs(gap):.0f}")
    direction = "LEAN_CE" if gap > 0 else "LEAN_PE"
    return VolumeComparison(ce, pe, direction, "OBSERVATIONAL", f"{winner.side} participation leads by {abs(gap):.0f} points; PCR authority unchanged")


__all__ = [
    "VolumeConfirmation",
    "VolumeConfirmationCheck",
    "VolumeComparison",
    "calculate_volume_confirmation",
    "compare_volume_confirmation",
]
