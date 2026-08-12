from red_bar_lab.services.red_bar_diagnostics import build_red_bar_lifecycle


def _reference():
    return {
        "level_type": "NEXT_RED_CANDLE",
        "source_timestamp": "2026-08-12T09:20:00+05:30",
        "source_high": 24500.0,
        "source_low": 24450.0,
        "midpoint": 24475.0,
        "interval_minutes": 5,
        "data_quality": "VALID",
    }


def test_diagnostics_waits_for_reference():
    result = build_red_bar_lifecycle([], [])
    assert result["status"] == "WAITING_FOR_RED_CANDLE"
    assert result["reference_persisted"] is False


def test_diagnostics_detected_reference_waits_for_cross():
    result = build_red_bar_lifecycle([_reference()], [])
    assert result["status"] == "WAITING_FOR_5M_CROSS"
    assert result["reference_persisted"] is True
    assert result["midpoint"] == 24475.0


def test_diagnostics_cross_waits_for_confirmation():
    attempts = [{
        "level_type": "NEXT_RED_CANDLE",
        "state": "AWAITING_CONFIRMATION",
        "direction": "BEARISH",
        "cross_timestamp": "2026-08-12T09:35:00+05:30",
        "confirmation_timestamp": None,
    }]
    result = build_red_bar_lifecycle([_reference()], attempts)
    assert result["status"] == "WAITING_FOR_1M_CONFIRMATION"
    assert result["signal_attempts"] == 1
    assert result["direction"] == "BEARISH"


def test_diagnostics_reports_active_signal():
    attempts = [{
        "level_type": "NEXT_RED_CANDLE",
        "state": "ACTIVE",
        "direction": "BULLISH",
        "cross_timestamp": "2026-08-12T09:35:00+05:30",
        "confirmation_timestamp": "2026-08-12T09:41:00+05:30",
    }]
    result = build_red_bar_lifecycle([_reference()], attempts)
    assert result["status"] == "ACTIVE"
    assert result["latest_signal_state"] == "ACTIVE"
