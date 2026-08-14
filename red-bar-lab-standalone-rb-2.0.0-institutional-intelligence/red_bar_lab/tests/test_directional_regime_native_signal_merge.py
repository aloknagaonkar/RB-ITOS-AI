from pathlib import Path

from red_bar_lab.execution.directional_regime_native_signal import (
    bundle_to_native_signal,
    decide_native_signal,
)


def bundle(direction="BULLISH"):
    return {
        "bundle_id": "BND-1",
        "direction": direction,
        "current_regime": direction,
        "detected_at": "2026-08-14T10:00:00",
        "fresh_until": "2026-08-14T10:15:00",
        "primary_signal_id": "SIG-1",
        "primary_setup_type": (
            "BULLISH_STRUCTURE_BREAK"
            if direction == "BULLISH"
            else "BEARISH_STRUCTURE_BREAK"
        ),
        "trigger_level": 24500.0,
        "invalidation_level": 24470.0,
    }


def test_fresh_bundle_becomes_native_signal():
    signal = bundle_to_native_signal(
        bundle(),
        now="2026-08-14T10:05:00",
    )
    assert signal["signal_id"] == "DRI-BND-1"
    assert signal["direction"] == "BULLISH"
    assert signal["option_type"] == "CE"
    assert signal["execution_allowed"] is True


def test_expired_bundle_is_not_executable():
    assert bundle_to_native_signal(
        bundle(),
        now="2026-08-14T10:20:00",
    ) is None


def test_same_direction_within_ten_minutes_merges():
    native = bundle_to_native_signal(
        bundle(),
        now="2026-08-14T10:05:00",
    )
    legacy = [{
        "signal_id": "REF-1",
        "direction": "BULLISH",
        "confirmation_timestamp": "2026-08-14T10:07:00",
        "signal_source": "REFERENCE_LEVEL",
    }]
    result = decide_native_signal(native, legacy)
    assert result.action == "DUAL_SOURCE_ALIGNED"
    assert result.native_signal["signal_id"] == "REF-1"
    assert result.native_signal["source_count"] == 2
    assert result.native_signal["directional_bundle_id"] == "BND-1"


def test_opposite_direction_within_ten_minutes_holds():
    native = bundle_to_native_signal(
        bundle("BEARISH"),
        now="2026-08-14T10:05:00",
    )
    legacy = [{
        "signal_id": "REF-1",
        "direction": "BULLISH",
        "confirmation_timestamp": "2026-08-14T10:07:00",
    }]
    result = decide_native_signal(native, legacy)
    assert result.action == "SOURCE_CONFLICT"
    assert result.native_signal is None


def test_same_direction_open_trade_is_reinforcement_only():
    native = bundle_to_native_signal(
        bundle(),
        now="2026-08-14T10:05:00",
    )
    result = decide_native_signal(
        native,
        [],
        open_orders=[{
            "signal_id": "REF-OPEN",
            "direction": "BULLISH",
            "status": "OPEN",
        }],
    )
    assert result.action == "REINFORCEMENT_ONLY"
    assert result.native_signal is None


def test_native_signal_is_single_source_when_no_nearby_signal():
    native = bundle_to_native_signal(
        bundle(),
        now="2026-08-14T10:05:00",
    )
    legacy = [{
        "signal_id": "REF-OLD",
        "direction": "BULLISH",
        "confirmation_timestamp": "2026-08-14T09:30:00",
    }]
    result = decide_native_signal(native, legacy)
    assert result.action == "SINGLE_SOURCE"
    assert result.native_signal["signal_id"] == "DRI-BND-1"
