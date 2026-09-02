from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


READY = "READY"
DEGRADED = "DEGRADED"
BLOCKED = "BLOCKED"
UNAVAILABLE = "UNAVAILABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class GlobalReadiness:
    status: str
    reason: str
    underlying_status: str
    option_chain_status: str
    option_quote_status: str
    pcr_status: str
    futures_status: str
    futures_strength: str
    v2_alignment_status: str
    execution_source_status: str
    market_hours_status: str
    blocking_reasons: tuple[str, ...] = ()
    advisory_reasons: tuple[str, ...] = ()
    execution_reasons: tuple[str, ...] = ()
    authority: str = "OBSERVATIONAL_ONLY"

    @property
    def ready(self) -> bool:
        return self.status == READY

    @property
    def component_statuses(self) -> Mapping[str, str]:
        return {
            "underlying": self.underlying_status,
            "option_chain": self.option_chain_status,
            "option_quote": self.option_quote_status,
            "pcr": self.pcr_status,
            "futures": self.futures_status,
            "futures_strength": self.futures_strength,
            "v2_alignment": self.v2_alignment_status,
            "execution_source": self.execution_source_status,
            "market_hours": self.market_hours_status,
        }


def _status(value: object, default: str = UNAVAILABLE) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = getattr(value, "status", default)
    return str(text or default).strip().upper()


def _strength(value: object) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = getattr(value, "strength", None) or getattr(value, "status", UNAVAILABLE)
    return str(text or UNAVAILABLE).strip().upper()


DATA_DIMENSION_LABELS = {
    "underlying": "underlying candles",
    "option_chain": "option chain",
    "option_quote": "option quotes",
    "pcr": "PCR",
    "futures": "futures contract",
}


def _blocked_reason(
    data_dimensions: list[str],
    alignment: str | None,
) -> str:
    """Describe what is blocking, not what is merely one possible cause.

    A V2-alignment block is not a market-data gap: the underlying, chain,
    quote, PCR and futures feeds can all be READY while the Red Bar V2
    source alignment is not. Naming the wrong subsystem sends the reader
    hunting for a feed outage that does not exist.
    """
    data_text = ", ".join(
        DATA_DIMENSION_LABELS.get(name, name) for name in data_dimensions
    )
    if data_dimensions and alignment:
        return (
            "Global readiness is blocked by market-data gaps "
            f"({data_text}) and Red Bar V2 source alignment ({alignment})."
        )
    if data_dimensions:
        return f"Global readiness is blocked by market-data gaps: {data_text}."
    if alignment:
        return (
            "Global readiness is blocked by Red Bar V2 source alignment "
            f"({alignment}); market-data feeds are not the cause."
        )
    return "Global readiness is blocked."


def assess_global_readiness(
    *,
    underlying_candle: object,
    option_chain: object,
    option_quotes: object,
    pcr: object = READY,
    futures: object = NOT_APPLICABLE,
    futures_strength: object = NOT_APPLICABLE,
    v2_alignment: object = READY,
    execution_source: object = READY,
    market_hours: object = READY,
) -> GlobalReadiness:
    """Combine market-data and execution-policy observations deterministically.

    The result is diagnostic only. Data-quality reasons, advisory intelligence,
    and execution-policy reasons remain separate and are never consumed by the
    stable Red Bar V2 execution path.
    """

    statuses = {
        "underlying": _status(underlying_candle),
        "option_chain": _status(option_chain),
        "option_quote": _status(option_quotes),
        "pcr": _status(pcr),
        "futures": _status(futures),
        "futures_strength": _strength(futures_strength),
        "v2_alignment": _status(v2_alignment),
        "execution_source": _status(execution_source),
        "market_hours": _status(market_hours),
    }

    blocking: list[str] = []
    advisory: list[str] = []
    execution: list[str] = []
    # Dimensions that contributed a blocking reason, kept separate so the
    # summary text can name what is actually wrong instead of asserting a
    # market-data gap for every blocker.
    blocking_data_dimensions: list[str] = []
    blocking_alignment: str | None = None

    data_components = ("underlying", "option_chain", "option_quote", "pcr", "futures")
    advisory_data_statuses = {DEGRADED, "PARTIAL", "STALE", "MARKET_CLOSED", "INSUFFICIENT"}
    blocking_data_statuses = {BLOCKED, UNAVAILABLE, "MISSING", "ERROR", "UNUSABLE", "INVALID"}

    for name in data_components:
        value = statuses[name]
        code = name.upper()
        if value in {READY, NOT_APPLICABLE, "APPLICABLE"}:
            continue
        if value in advisory_data_statuses:
            advisory.append(f"{code}_{value}")
        elif value in blocking_data_statuses:
            blocking.append(f"{code}_{value}")
            blocking_data_dimensions.append(name)
        else:
            advisory.append(f"{code}_{value}")

    strength = statuses["futures_strength"]
    if strength in {"WEAK", "INSUFFICIENT", "INSUFFICIENT_DATA"}:
        advisory.append(f"FUTURES_STRENGTH_{strength}")
    elif strength not in {"STRONG", "MODERATE", READY, NOT_APPLICABLE}:
        advisory.append(f"FUTURES_STRENGTH_{strength}")

    alignment = statuses["v2_alignment"]
    if alignment not in {READY, "ALIGNED", NOT_APPLICABLE}:
        if alignment in {BLOCKED, UNAVAILABLE, "MISSING", "STALE", "MISALIGNED"}:
            blocking.append(f"V2_ALIGNMENT_{alignment}")
            blocking_alignment = alignment
        else:
            advisory.append(f"V2_ALIGNMENT_{alignment}")

    source = statuses["execution_source"]
    if source not in {READY, "ENABLED"}:
        execution.append(f"EXECUTION_SOURCE_{source}")

    hours = statuses["market_hours"]
    if hours not in {READY, "OPEN", "ENTRY_OPEN"}:
        execution.append(f"MARKET_HOURS_{hours}")
        if hours in {"CLOSED", "MARKET_CLOSED", "OUTSIDE_ENTRY_HOURS"}:
            advisory.append(f"MARKET_HOURS_{hours}")

    unavailable_only = bool(blocking) and all(reason.endswith("_UNAVAILABLE") for reason in blocking)
    if unavailable_only:
        status = UNAVAILABLE
        reason = "Global readiness cannot be established from the available observations."
    elif blocking:
        status = BLOCKED
        reason = _blocked_reason(blocking_data_dimensions, blocking_alignment)
    elif advisory or execution:
        status = DEGRADED
        reason = "Global readiness is observationally usable with advisory or execution-policy conditions."
    else:
        status = READY
        reason = "Market data, Red Bar V2 alignment and execution observations are ready."

    return GlobalReadiness(
        status=status,
        reason=reason,
        underlying_status=statuses["underlying"],
        option_chain_status=statuses["option_chain"],
        option_quote_status=statuses["option_quote"],
        pcr_status=statuses["pcr"],
        futures_status=statuses["futures"],
        futures_strength=statuses["futures_strength"],
        v2_alignment_status=statuses["v2_alignment"],
        execution_source_status=statuses["execution_source"],
        market_hours_status=statuses["market_hours"],
        blocking_reasons=tuple(dict.fromkeys(blocking)),
        advisory_reasons=tuple(dict.fromkeys(advisory)),
        execution_reasons=tuple(dict.fromkeys(execution)),
    )


def global_readiness_log_values(result: GlobalReadiness) -> tuple[str, ...]:
    return (
        result.status,
        result.reason,
        result.underlying_status,
        result.option_chain_status,
        result.option_quote_status,
        result.pcr_status,
        result.futures_status,
        result.futures_strength,
        result.v2_alignment_status,
        result.execution_source_status,
        result.market_hours_status,
        ",".join(result.blocking_reasons) or "NONE",
        ",".join(result.advisory_reasons) or "NONE",
        ",".join(result.execution_reasons) or "NONE",
        result.authority,
    )
