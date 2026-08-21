from red_bar_lab.services.rsi_readiness import assess_rsi_readiness


AS_OF = "2026-08-21T10:20:00+05:30"


def test_ready_requires_observed_value_period_candles_and_timestamp():
    result = assess_rsi_readiness(
        {
            "rsi_value": 31.5,
            "period": 7,
            "candle_count": 20,
            "source_timestamp": "2026-08-21T10:19:00+05:30",
        },
        as_of_timestamp=AS_OF,
    )

    assert result.status == "READY"
    assert result.no_lookahead_passed is True
    assert result.age_seconds == 60
    assert result.authority == "OBSERVATIONAL_ONLY"


def test_configuration_without_observation_is_not_ready():
    result = assess_rsi_readiness(None, as_of_timestamp=AS_OF)

    assert result.status == "MISSING"
    assert result.reason_code == "RSI_OBSERVATION_MISSING"


def test_missing_value_and_insufficient_candles_are_explicit():
    missing_value = assess_rsi_readiness(
        {"period": 7, "candle_count": 20, "source_timestamp": AS_OF},
        as_of_timestamp=AS_OF,
    )
    insufficient = assess_rsi_readiness(
        {
            "rsi_value": 30,
            "period": 7,
            "candle_count": 7,
            "source_timestamp": AS_OF,
        },
        as_of_timestamp=AS_OF,
    )

    assert missing_value.reason_code == "RSI_VALUE_MISSING_OR_INVALID"
    assert insufficient.reason_code == "RSI_CANDLE_COVERAGE_INSUFFICIENT"


def test_stale_and_future_observations_never_report_ready():
    stale = assess_rsi_readiness(
        {
            "rsi_value": 30,
            "period": 7,
            "candle_count": 20,
            "source_timestamp": "2026-08-21T10:10:00+05:30",
        },
        as_of_timestamp=AS_OF,
    )
    future = assess_rsi_readiness(
        {
            "rsi_value": 30,
            "period": 7,
            "candle_count": 20,
            "source_timestamp": "2026-08-21T10:21:00+05:30",
        },
        as_of_timestamp=AS_OF,
    )

    assert stale.status == "STALE"
    assert stale.reason_code == "RSI_OBSERVATION_STALE"
    assert future.status == "FAILED"
    assert future.reason_code == "RSI_LOOKAHEAD_DETECTED"
