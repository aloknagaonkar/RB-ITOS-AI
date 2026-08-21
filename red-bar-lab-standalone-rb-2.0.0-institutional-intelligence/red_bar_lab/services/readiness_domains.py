from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ReadinessDomainResult:
    status: str
    blocking_reasons: tuple[str, ...]
    advisory_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReadinessDomains:
    market_data_readiness: ReadinessDomainResult
    independent_strategy_readiness: ReadinessDomainResult
    red_bar_v2_readiness: ReadinessDomainResult
    execution_readiness: ReadinessDomainResult
    authority: str = "OBSERVATIONAL_ONLY"


def _result(reasons: Iterable[str], advisory: Iterable[str] = ()) -> ReadinessDomainResult:
    blocking = tuple(dict.fromkeys(str(value) for value in reasons if value))
    cautions = tuple(dict.fromkeys(str(value) for value in advisory if value))
    return ReadinessDomainResult(
        status="BLOCKED" if blocking else "READY",
        blocking_reasons=blocking,
        advisory_reasons=cautions,
    )


def build_readiness_domains(
    *,
    market_data_reasons: Iterable[str] = (),
    independent_strategy_reasons: Iterable[str] = (),
    red_bar_v2_reasons: Iterable[str] = (),
    execution_reasons: Iterable[str] = (),
    market_data_advisories: Iterable[str] = (),
    independent_strategy_advisories: Iterable[str] = (),
    red_bar_v2_advisories: Iterable[str] = (),
    execution_advisories: Iterable[str] = (),
) -> ReadinessDomains:
    """Build isolated readiness domains without cross-strategy contamination.

    The independent path intentionally does not consume Red Bar V2 blockers.
    Execution readiness remains separately owned and is not inferred from a
    diagnostic page result.
    """

    return ReadinessDomains(
        market_data_readiness=_result(market_data_reasons, market_data_advisories),
        independent_strategy_readiness=_result(
            independent_strategy_reasons,
            independent_strategy_advisories,
        ),
        red_bar_v2_readiness=_result(red_bar_v2_reasons, red_bar_v2_advisories),
        execution_readiness=_result(execution_reasons, execution_advisories),
    )


def independent_path_ready(domains: ReadinessDomains) -> bool:
    return (
        domains.market_data_readiness.status == "READY"
        and domains.independent_strategy_readiness.status == "READY"
    )


def red_bar_v2_path_ready(domains: ReadinessDomains) -> bool:
    return (
        domains.market_data_readiness.status == "READY"
        and domains.red_bar_v2_readiness.status == "READY"
    )


__all__ = [
    "ReadinessDomainResult",
    "ReadinessDomains",
    "build_readiness_domains",
    "independent_path_ready",
    "red_bar_v2_path_ready",
]
