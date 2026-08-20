from __future__ import annotations

from dataclasses import dataclass


READY = "READY"
DEGRADED = "DEGRADED"
UNAVAILABLE = "UNAVAILABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class NiftyFuturesReadiness:
    status: str
    reason: str
    contract_status: str
    market_status: str
    candle_status: str
    volume_status: str
    oi_status: str
    positioning_status: str
    positioning_state: str
    blocking_reasons: tuple[str, ...] = ()
    advisory_reasons: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status == READY


def assess_nifty_futures_readiness(
    *,
    contract,
    market,
    positioning,
    applicable: bool = True,
) -> NiftyFuturesReadiness:
    """Combine futures discovery, market data and positioning diagnostics.

    The result is observational only. It deliberately separates blocking data
    gaps from advisory conditions and does not alter Red Bar V2 execution.
    """

    if not applicable:
        return NiftyFuturesReadiness(
            status=NOT_APPLICABLE,
            reason="NIFTY futures readiness is not applicable to this underlying.",
            contract_status=NOT_APPLICABLE,
            market_status=NOT_APPLICABLE,
            candle_status=NOT_APPLICABLE,
            volume_status=NOT_APPLICABLE,
            oi_status=NOT_APPLICABLE,
            positioning_status=NOT_APPLICABLE,
            positioning_state="NEUTRAL",
        )

    contract_status = str(getattr(contract, "status", "UNAVAILABLE") or "UNAVAILABLE")
    market_status = str(getattr(market, "status", "UNAVAILABLE") or "UNAVAILABLE")
    candle = getattr(market, "candle_readiness", None)
    candle_status = str(getattr(candle, "status", "UNAVAILABLE") or "UNAVAILABLE")
    volume = getattr(market, "volume_authority", None)
    volume_status = str(getattr(volume, "status", "MISSING") or "MISSING")
    latest_oi = getattr(market, "latest_oi", None)
    oi_status = "READY" if latest_oi is not None and float(latest_oi) >= 0 else "MISSING"
    positioning_status = str(
        getattr(positioning, "status", "INSUFFICIENT_DATA") or "INSUFFICIENT_DATA"
    )
    positioning_state = str(getattr(positioning, "state", "NEUTRAL") or "NEUTRAL")

    blocking: list[str] = []
    advisory: list[str] = []

    if contract_status != READY:
        blocking.append(f"CONTRACT_{contract_status}")
    if market_status != READY:
        blocking.append(f"MARKET_{market_status}")
    if volume_status != "APPLICABLE":
        blocking.append(f"VOLUME_{volume_status}")
    if oi_status != READY:
        blocking.append("OI_MISSING")

    if candle_status not in {READY, "MARKET_CLOSED"}:
        blocking.append(f"CANDLE_{candle_status}")
    elif candle_status == "MARKET_CLOSED":
        advisory.append("CANDLE_MARKET_CLOSED")

    if positioning_status != READY:
        advisory.append(f"POSITIONING_{positioning_status}")
    if positioning_state == "NEUTRAL":
        advisory.append("POSITIONING_NEUTRAL")

    if blocking:
        status = UNAVAILABLE if contract_status != READY else DEGRADED
        reason = "NIFTY futures diagnostics have blocking data gaps."
    else:
        status = READY
        reason = "NIFTY futures contract, completed candle, volume and OI are ready."

    return NiftyFuturesReadiness(
        status=status,
        reason=reason,
        contract_status=contract_status,
        market_status=market_status,
        candle_status=candle_status,
        volume_status=volume_status,
        oi_status=oi_status,
        positioning_status=positioning_status,
        positioning_state=positioning_state,
        blocking_reasons=tuple(blocking),
        advisory_reasons=tuple(advisory),
    )


def futures_readiness_log_values(result: NiftyFuturesReadiness) -> tuple[str, ...]:
    return (
        result.status,
        result.reason,
        result.contract_status,
        result.market_status,
        result.candle_status,
        result.volume_status,
        result.oi_status,
        result.positioning_status,
        result.positioning_state,
        ",".join(result.blocking_reasons) or "NONE",
        ",".join(result.advisory_reasons) or "NONE",
    )
