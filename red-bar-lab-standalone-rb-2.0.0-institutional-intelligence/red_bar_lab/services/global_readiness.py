from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


READY = "READY"
DEGRADED = "DEGRADED"
BLOCKED = "BLOCKED"
NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class GlobalReadiness:
    status: str
    reason: str
    component_statuses: Mapping[str, str]
    blocking_reasons: tuple[str, ...] = ()
    advisory_reasons: tuple[str, ...] = ()
    execution_reasons: tuple[str, ...] = ()
    authority: str = "OBSERVATIONAL_ONLY"

    @property
    def ready(self) -> bool:
        return self.status == READY


def _status(value: object, default: str = "UNAVAILABLE") -> str:
    if isinstance(value, str):
        text = value
    else:
        text = getattr(value, "status", default)
    return str(text or default).strip().upper()


def assess_global_readiness(
    *,
    underlying_candle: object,
    option_chain: object,
    option_quotes: object,
    futures: object,
    applicable: bool = True,
) -> GlobalReadiness:
    """Combine independent market-data readiness without execution authority.

    Blocking reasons identify unavailable raw inputs. Advisory reasons identify
    usable but imperfect conditions. Execution reasons are reported separately
    and are never consumed by the stable Decision Engine in this phase.
    """

    if not applicable:
        return GlobalReadiness(
            status=NOT_APPLICABLE,
            reason="Global readiness is not applicable to this underlying.",
            component_statuses={
                "underlying_candle": NOT_APPLICABLE,
                "option_chain": NOT_APPLICABLE,
                "option_quotes": NOT_APPLICABLE,
                "futures": NOT_APPLICABLE,
            },
        )

    components = {
        "underlying_candle": _status(underlying_candle),
        "option_chain": _status(option_chain),
        "option_quotes": _status(option_quotes),
        "futures": _status(futures),
    }
    blocking: list[str] = []
    advisory: list[str] = []
    execution: list[str] = []

    accepted = {READY, "APPLICABLE", "MARKET_CLOSED"}
    advisory_statuses = {DEGRADED, "STALE", "PARTIAL", "INSUFFICIENT_DATA", "MARKET_CLOSED"}

    for name, status in components.items():
        code = name.upper()
        if status in accepted:
            if status == "MARKET_CLOSED":
                advisory.append(f"{code}_MARKET_CLOSED")
            continue
        if status in advisory_statuses:
            advisory.append(f"{code}_{status}")
            continue
        blocking.append(f"{code}_{status}")

    if blocking:
        status = BLOCKED
        reason = "Global readiness has blocking market-data gaps."
        execution.append("EXECUTION_NOT_EVALUATED_DATA_BLOCKED")
    elif advisory:
        status = DEGRADED
        reason = "Global readiness is usable with advisory conditions."
        execution.append("EXECUTION_POLICY_UNCHANGED")
    else:
        status = READY
        reason = "Underlying, option-chain, option-quote and futures data are ready."
        execution.append("EXECUTION_POLICY_UNCHANGED")

    return GlobalReadiness(
        status=status,
        reason=reason,
        component_statuses=components,
        blocking_reasons=tuple(blocking),
        advisory_reasons=tuple(advisory),
        execution_reasons=tuple(execution),
    )


def global_readiness_log_values(result: GlobalReadiness) -> tuple[str, ...]:
    components = result.component_statuses
    return (
        result.status,
        result.reason,
        components.get("underlying_candle", "UNAVAILABLE"),
        components.get("option_chain", "UNAVAILABLE"),
        components.get("option_quotes", "UNAVAILABLE"),
        components.get("futures", "UNAVAILABLE"),
        ",".join(result.blocking_reasons) or "NONE",
        ",".join(result.advisory_reasons) or "NONE",
        ",".join(result.execution_reasons) or "NONE",
        result.authority,
    )
