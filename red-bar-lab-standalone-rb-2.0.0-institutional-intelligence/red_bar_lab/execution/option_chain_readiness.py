from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

CHAIN_READY = "READY"
CHAIN_EMPTY = "EMPTY_CHAIN"
CHAIN_INVALID_STRIKE = "INVALID_STRIKE"
CHAIN_MISSING_STRIKE = "MISSING_STRIKE"
CHAIN_MISSING_CALL_LEG = "MISSING_CALL_LEG"
CHAIN_MISSING_PUT_LEG = "MISSING_PUT_LEG"
CHAIN_MISSING_CALL_OI = "MISSING_CALL_OI"
CHAIN_MISSING_PUT_OI = "MISSING_PUT_OI"
CHAIN_INVALID_CALL_OI = "INVALID_CALL_OI"
CHAIN_INVALID_PUT_OI = "INVALID_PUT_OI"
CHAIN_ZERO_CALL_OI = "ZERO_CALL_OI"
CHAIN_ZERO_PUT_OI = "ZERO_PUT_OI"


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _option_node(row: Mapping[str, object], side: str) -> dict[str, object]:
    aliases = (
        ("call_options", "call", "ce")
        if side == "CE"
        else ("put_options", "put", "pe")
    )
    for name in aliases:
        node = row.get(name)
        if isinstance(node, Mapping):
            return dict(node)
    return {}


def _market_data(node: Mapping[str, object]) -> dict[str, object]:
    value = node.get("market_data") or node.get("marketData") or node
    return dict(value) if isinstance(value, Mapping) else {}


def _raw_oi(node: Mapping[str, object]) -> object:
    market = _market_data(node)
    if "oi" in market:
        return market.get("oi")
    return node.get("oi")


@dataclass(frozen=True)
class OptionChainReadiness:
    status: str
    reason: str
    strike: float | None
    call_oi: float | None = None
    put_oi: float | None = None

    @property
    def ready(self) -> bool:
        return self.status == CHAIN_READY

    @property
    def pcr_usable(self) -> bool:
        return (
            self.ready
            and self.call_oi not in (None, 0.0)
            and self.put_oi is not None
        )


def assess_option_chain_completeness(
    rows: Sequence[Mapping[str, object]],
    strike: object,
) -> OptionChainReadiness:
    """Assess selected-strike CE/PE and OI completeness.

    This is observational only. Zero OI is distinguished from missing OI so
    diagnostics never fabricate data or silently treat absence as zero.
    """

    target = _number(strike)
    if target is None:
        return OptionChainReadiness(
            CHAIN_INVALID_STRIKE,
            "Selected strike is missing or non-numeric.",
            None,
        )

    if not rows:
        return OptionChainReadiness(
            CHAIN_EMPTY,
            "Option-chain response contains no rows.",
            target,
        )

    matched: Mapping[str, object] | None = None
    for row in rows:
        candidate = _number(row.get("strike_price") or row.get("strike"))
        if candidate is not None and abs(candidate - target) < 0.001:
            matched = row
            break

    if matched is None:
        return OptionChainReadiness(
            CHAIN_MISSING_STRIKE,
            f"Selected strike {target:g} is absent from the option chain.",
            target,
        )

    call_node = _option_node(matched, "CE")
    if not call_node:
        return OptionChainReadiness(
            CHAIN_MISSING_CALL_LEG,
            f"Call leg is absent at strike {target:g}.",
            target,
        )

    put_node = _option_node(matched, "PE")
    if not put_node:
        return OptionChainReadiness(
            CHAIN_MISSING_PUT_LEG,
            f"Put leg is absent at strike {target:g}.",
            target,
        )

    raw_call_oi = _raw_oi(call_node)
    if raw_call_oi is None or raw_call_oi == "":
        return OptionChainReadiness(
            CHAIN_MISSING_CALL_OI,
            f"Call OI is missing at strike {target:g}.",
            target,
        )
    call_oi = _number(raw_call_oi)
    if call_oi is None or call_oi < 0:
        return OptionChainReadiness(
            CHAIN_INVALID_CALL_OI,
            f"Call OI is invalid at strike {target:g}.",
            target,
        )

    raw_put_oi = _raw_oi(put_node)
    if raw_put_oi is None or raw_put_oi == "":
        return OptionChainReadiness(
            CHAIN_MISSING_PUT_OI,
            f"Put OI is missing at strike {target:g}.",
            target,
            call_oi=call_oi,
        )
    put_oi = _number(raw_put_oi)
    if put_oi is None or put_oi < 0:
        return OptionChainReadiness(
            CHAIN_INVALID_PUT_OI,
            f"Put OI is invalid at strike {target:g}.",
            target,
            call_oi=call_oi,
        )

    if call_oi == 0.0:
        return OptionChainReadiness(
            CHAIN_ZERO_CALL_OI,
            f"Call OI is zero at strike {target:g}; PCR is not usable.",
            target,
            call_oi=call_oi,
            put_oi=put_oi,
        )
    if put_oi == 0.0:
        return OptionChainReadiness(
            CHAIN_ZERO_PUT_OI,
            f"Put OI is zero at strike {target:g}; PCR is zero.",
            target,
            call_oi=call_oi,
            put_oi=put_oi,
        )

    return OptionChainReadiness(
        CHAIN_READY,
        f"Selected strike {target:g} has complete CE/PE OI data.",
        target,
        call_oi=call_oi,
        put_oi=put_oi,
    )
