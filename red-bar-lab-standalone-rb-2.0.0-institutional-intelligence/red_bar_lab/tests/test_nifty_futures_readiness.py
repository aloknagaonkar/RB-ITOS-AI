from types import SimpleNamespace

from red_bar_lab.services.nifty_futures_readiness import (
    assess_nifty_futures_readiness,
    futures_readiness_log_values,
)


def _contract(status="READY"):
    return SimpleNamespace(status=status)


def _market(
    *,
    status="READY",
    candle_status="READY",
    volume_status="APPLICABLE",
    latest_oi=1000,
):
    return SimpleNamespace(
        status=status,
        candle_readiness=SimpleNamespace(status=candle_status),
        volume_authority=SimpleNamespace(status=volume_status),
        latest_oi=latest_oi,
    )


def _positioning(status="READY", state="LONG_BUILDUP"):
    return SimpleNamespace(status=status, state=state)


def test_ready_when_contract_market_volume_and_oi_are_available():
    result = assess_nifty_futures_readiness(
        contract=_contract(),
        market=_market(),
        positioning=_positioning(),
    )

    assert result.status == "READY"
    assert result.ready is True
    assert result.blocking_reasons == ()
    assert result.positioning_state == "LONG_BUILDUP"


def test_market_closed_is_advisory_not_blocking():
    result = assess_nifty_futures_readiness(
        contract=_contract(),
        market=_market(candle_status="MARKET_CLOSED"),
        positioning=_positioning(state="NEUTRAL"),
    )

    assert result.status == "READY"
    assert result.blocking_reasons == ()
    assert result.advisory_reasons == (
        "CANDLE_MARKET_CLOSED",
        "POSITIONING_NEUTRAL",
    )


def test_missing_oi_degrades_resolved_contract():
    result = assess_nifty_futures_readiness(
        contract=_contract(),
        market=_market(latest_oi=None),
        positioning=_positioning(status="INSUFFICIENT_DATA", state="NEUTRAL"),
    )

    assert result.status == "DEGRADED"
    assert result.blocking_reasons == ("OI_MISSING",)
    assert "POSITIONING_INSUFFICIENT_DATA" in result.advisory_reasons


def test_unresolved_contract_is_unavailable():
    result = assess_nifty_futures_readiness(
        contract=_contract("UNAVAILABLE"),
        market=_market(status="UNAVAILABLE", volume_status="MISSING", latest_oi=None),
        positioning=_positioning(status="INSUFFICIENT_DATA", state="NEUTRAL"),
    )

    assert result.status == "UNAVAILABLE"
    assert "CONTRACT_UNAVAILABLE" in result.blocking_reasons


def test_non_nifty_underlying_is_not_applicable():
    result = assess_nifty_futures_readiness(
        contract=_contract(),
        market=_market(),
        positioning=_positioning(),
        applicable=False,
    )

    assert result.status == "NOT_APPLICABLE"
    assert result.contract_status == "NOT_APPLICABLE"


def test_log_values_keep_blocking_and_advisory_reasons_separate():
    result = assess_nifty_futures_readiness(
        contract=_contract(),
        market=_market(candle_status="MARKET_CLOSED"),
        positioning=_positioning(status="INSUFFICIENT_DATA", state="NEUTRAL"),
    )

    values = futures_readiness_log_values(result)

    assert values[0] == "READY"
    assert values[9] == "NONE"
    assert values[10] == (
        "CANDLE_MARKET_CLOSED,POSITIONING_INSUFFICIENT_DATA,POSITIONING_NEUTRAL"
    )
