from red_bar_lab.services.red_bar_v2_reference_readiness import (
    RED_BAR_V2_REFERENCE_TYPE,
    assess_red_bar_v2_reference_readiness,
)


def _signal():
    return {
        "signal_id": "RBV2-1",
        "confirmation_timestamp": "2026-08-21T10:30:00+05:30",
    }


def _reference(**overrides):
    payload = {
        "reference_type": RED_BAR_V2_REFERENCE_TYPE,
        "reference_timestamp": "2026-08-21T10:25:00+05:30",
        "reference_high": 25020.0,
        "reference_low": 24980.0,
        "reference_midpoint": 25000.0,
        "data_quality": "VALID",
    }
    payload.update(overrides)
    return payload


def test_valid_next_red_candle_reference_is_ready():
    result = assess_red_bar_v2_reference_readiness(_signal(), _reference())
    assert result.status == "READY"
    assert result.reason_code is None
    assert result.authority == "OBSERVATIONAL_ONLY"


def test_first_candle_reference_is_rejected():
    result = assess_red_bar_v2_reference_readiness(
        _signal(),
        _reference(reference_type="FIRST_CANDLE"),
    )
    assert result.status == "FAILED"
    assert result.reason_code == "REFERENCE_TYPE_MISMATCH"


def test_reference_after_confirmation_is_rejected():
    result = assess_red_bar_v2_reference_readiness(
        _signal(),
        _reference(reference_timestamp="2026-08-21T10:31:00+05:30"),
    )
    assert result.status == "FAILED"
    assert result.reason_code == "REFERENCE_AFTER_CONFIRMATION"


def test_midpoint_must_be_inside_reference_range():
    result = assess_red_bar_v2_reference_readiness(
        _signal(),
        _reference(reference_midpoint=25050.0),
    )
    assert result.status == "FAILED"
    assert result.reason_code == "REFERENCE_MIDPOINT_OUTSIDE_RANGE"


def test_missing_reference_has_explicit_reason():
    result = assess_red_bar_v2_reference_readiness(_signal(), None)
    assert result.status == "MISSING"
    assert result.reason_code == "REFERENCE_NOT_FOUND"
