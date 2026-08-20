from types import SimpleNamespace

from red_bar_lab.services.global_readiness import (
    BLOCKED,
    DEGRADED,
    NOT_APPLICABLE,
    READY,
    UNAVAILABLE,
    assess_global_readiness,
    global_readiness_log_values,
)


def _component(status):
    return SimpleNamespace(status=status)


def test_all_ready_components_produce_ready_observational_result():
    result = assess_global_readiness(
        underlying_candle="READY", option_chain="READY", option_quotes="READY",
        pcr="READY", futures="READY", futures_strength="STRONG",
        v2_alignment="ALIGNED", execution_source="ENABLED", market_hours="OPEN",
    )
    assert result.status == READY
    assert result.blocking_reasons == ()
    assert result.advisory_reasons == ()
    assert result.execution_reasons == ()
    assert result.authority == "OBSERVATIONAL_ONLY"


def test_market_closed_and_weak_futures_are_advisory():
    result = assess_global_readiness(
        underlying_candle="MARKET_CLOSED", option_chain="READY", option_quotes="READY",
        pcr="READY", futures="READY", futures_strength="WEAK",
        v2_alignment="ALIGNED", execution_source="ENABLED", market_hours="MARKET_CLOSED",
    )
    assert result.status == DEGRADED
    assert result.blocking_reasons == ()
    assert "UNDERLYING_MARKET_CLOSED" in result.advisory_reasons
    assert "FUTURES_STRENGTH_WEAK" in result.advisory_reasons
    assert "MARKET_HOURS_MARKET_CLOSED" in result.advisory_reasons
    assert result.execution_reasons == ("MARKET_HOURS_MARKET_CLOSED",)


def test_missing_option_chain_blocks_but_disabled_source_is_execution_reason():
    result = assess_global_readiness(
        underlying_candle="READY", option_chain="UNAVAILABLE", option_quotes="READY",
        pcr="UNUSABLE", futures="READY", futures_strength="MODERATE",
        v2_alignment="ALIGNED", execution_source="DISABLED", market_hours="OPEN",
    )
    assert result.status == BLOCKED
    assert "OPTION_CHAIN_UNAVAILABLE" in result.blocking_reasons
    assert "PCR_UNUSABLE" in result.blocking_reasons
    assert result.execution_reasons == ("EXECUTION_SOURCE_DISABLED",)


def test_all_missing_observations_produce_unavailable_state():
    result = assess_global_readiness(
        underlying_candle="UNAVAILABLE", option_chain="UNAVAILABLE",
        option_quotes="UNAVAILABLE", pcr="UNAVAILABLE", futures="UNAVAILABLE",
        futures_strength="INSUFFICIENT", v2_alignment="UNAVAILABLE",
        execution_source="DISABLED", market_hours="MARKET_CLOSED",
    )
    assert result.status == UNAVAILABLE
    assert result.blocking_reasons


def test_bank_nifty_accepts_not_applicable_nifty_futures():
    result = assess_global_readiness(
        underlying_candle="READY", option_chain="READY", option_quotes="READY",
        pcr="READY", futures=NOT_APPLICABLE, futures_strength=NOT_APPLICABLE,
        v2_alignment="ALIGNED", execution_source="ENABLED", market_hours="OPEN",
    )
    assert result.status == READY
    assert result.futures_status == NOT_APPLICABLE


def test_v2_stale_alignment_is_data_blocking_not_execution_policy():
    result = assess_global_readiness(
        underlying_candle="READY", option_chain="READY", option_quotes="READY",
        pcr="READY", futures="READY", futures_strength="INSUFFICIENT",
        v2_alignment="STALE", execution_source="ENABLED", market_hours="OPEN",
    )
    assert result.status == BLOCKED
    assert result.blocking_reasons == ("V2_ALIGNMENT_STALE",)
    assert "FUTURES_STRENGTH_INSUFFICIENT" in result.advisory_reasons


def test_log_values_expose_all_component_statuses_and_reason_groups():
    result = assess_global_readiness(
        underlying_candle=_component("READY"), option_chain="PARTIAL",
        option_quotes="STALE", pcr="READY", futures="DEGRADED",
        futures_strength="WEAK", v2_alignment="ALIGNED",
        execution_source="DISABLED", market_hours="OUTSIDE_ENTRY_HOURS",
    )
    values = global_readiness_log_values(result)
    assert values[0] == DEGRADED
    assert values[2:11] == (
        "READY", "PARTIAL", "STALE", "READY", "DEGRADED", "WEAK",
        "ALIGNED", "DISABLED", "OUTSIDE_ENTRY_HOURS",
    )
    assert values[11] == "NONE"
    assert "OPTION_CHAIN_PARTIAL" in values[12]
    assert "EXECUTION_SOURCE_DISABLED" in values[13]
    assert values[14] == "OBSERVATIONAL_ONLY"
