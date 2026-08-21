from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Iterable, Mapping


OPTION_CHAIN_WINDOW_POLICY_VERSION = "option-chain-window-v1"


@dataclass(frozen=True)
class OptionChainWindow:
    status: str
    atm_strike: float | None
    selected_strikes: tuple[float, ...]
    rows: tuple[dict[str, Any], ...]
    strikes_each_side: int
    reason_code: str | None = None
    policy_version: str = OPTION_CHAIN_WINDOW_POLICY_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _strike(row: Mapping[str, Any]) -> float | None:
    for key in ("strike", "strike_price", "strikePrice"):
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def select_atm_option_chain_window(
    rows: Iterable[Mapping[str, Any]] | None,
    *,
    spot: object = None,
    atm_strike: object = None,
    strikes_each_side: int = 4,
) -> OptionChainWindow:
    """Return only ATM and the configured number of strikes on each side.

    The function is presentation-only. It does not change option selection,
    ranking, trade creation, or execution authority.
    """

    width = max(0, int(strikes_each_side))
    normalized: list[tuple[float, dict[str, Any]]] = []
    for original in rows or ():
        row = dict(original)
        strike = _strike(row)
        if strike is not None:
            normalized.append((strike, row))

    if not normalized:
        return OptionChainWindow(
            status="MISSING",
            atm_strike=None,
            selected_strikes=(),
            rows=(),
            strikes_each_side=width,
            reason_code="OPTION_CHAIN_ROWS_MISSING",
        )

    strikes = sorted({strike for strike, _ in normalized})
    requested_atm = _number(atm_strike)
    spot_value = _number(spot)
    anchor = requested_atm if requested_atm is not None else spot_value
    if anchor is None:
        return OptionChainWindow(
            status="MISSING",
            atm_strike=None,
            selected_strikes=(),
            rows=(),
            strikes_each_side=width,
            reason_code="ATM_REFERENCE_MISSING",
        )

    atm = min(strikes, key=lambda strike: (abs(strike - anchor), strike))
    atm_index = strikes.index(atm)
    selected = tuple(
        strikes[
            max(0, atm_index - width) : min(len(strikes), atm_index + width + 1)
        ]
    )
    selected_set = set(selected)
    selected_rows = tuple(
        row
        for strike, row in sorted(normalized, key=lambda item: item[0])
        if strike in selected_set
    )

    return OptionChainWindow(
        status="READY",
        atm_strike=atm,
        selected_strikes=selected,
        rows=selected_rows,
        strikes_each_side=width,
    )


__all__ = [
    "OPTION_CHAIN_WINDOW_POLICY_VERSION",
    "OptionChainWindow",
    "select_atm_option_chain_window",
]
