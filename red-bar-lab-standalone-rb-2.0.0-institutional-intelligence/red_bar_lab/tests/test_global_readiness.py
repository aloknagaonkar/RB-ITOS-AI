from types import SimpleNamespace

from red_bar_lab.services.global_readiness import (
    BLOCKED,
    DEGRADED,
    NOT_APPLICABLE,
    READY,
    assess_global_readiness,
    global_readiness_log_values,
)


def _component(status):
    return SimpleNamespace(status=status)


def test_all_ready_components_produce_ready_observational_result():
    result = assess_global_readiness(
        underlying_candle=_component("READY"),
        option_chain=_component("READY"),
        option_quotes=_component("READY"),
        futures=_component("READY"),
    )

    assert result.status == READY
    assert result.blocking_reasons == ()
    assert result.advisory_reasons == ()
    assert result.execution_reasons == ("EXECUTION_POLICY_UNCHANGED",)
    assert result.authority == "OBSERVATIONAL_ONLY"


def test_market_closed_and_partial_inputs_are_advisory():
    result = assess_global_readiness(
        underlying_candle=_component("MARKET_CLOSED"),
        option_chain=_component("PARTIAL"),
        option_quotes=_component("READY"),
        futures=_component("READY"),
    )

    assert result.status == DEGRADED
    assert result.blocking_reasons == ()
    assert "UNDERLYING_CANDLE_MARKET_CLOSED" in result.advisory_reasons
    assert "OPTION_CHAIN_PARTIAL" in result.advisory_reasons


def test_missing_raw_component_blocks_global_readiness():
    result = assess_global_readiness(
        underlying_candle=_component("READY"),
        option_chain=_component("UNAVAILABLE"),
        option_quotes=_component("READY"),
        futures=_component("READY"),
    )

    assert result.status == BLOCKED
    assert result.blocking_reasons == ("OPTION_CHAIN_UNAVAILABLE",)
    assert result.execution_reasons == ("EXECUTION_NOT_EVALUATED_DATA_BLOCKED",)


def test_plain_status_strings_are_supported():
    result = assess_global_readiness(
        underlying_candle="READY",
        option_chain="READY",
        option_quotes="READY",
        futures="DEGRADED",
    )

    assert result.status == DEGRADED
    assert result.component_statuses["futures"] == "DEGRADED"


def test_not_applicable_is_stable():
    result = assess_global_readiness(
        underlying_candle=None,
        option_chain=None,
        option_quotes=None,
        futures=None,
        applicable=False,
    )

    assert result.status == NOT_APPLICABLE
    assert set(result.component_statuses.values()) == {NOT_APPLICABLE}


def test_log_values_keep_reason_groups_separate():
    result = assess_global_readiness(
        underlying_candle="MARKET_CLOSED",
        option_chain="READY",
        option_quotes="STALE",
        futures="READY",
    )

    values = global_readiness_log_values(result)
    assert values[0] == DEGRADED
    assert values[6] == "NONE"
    assert "UNDERLYING_CANDLE_MARKET_CLOSED" in values[7]
    assert "OPTION_QUOTES_STALE" in values[7]
    assert values[8] == "EXECUTION_POLICY_UNCHANGED"
    assert values[9] == "OBSERVATIONAL_ONLY"
