from red_bar_lab.execution.dri_opportunity_context import (
    resolve_opposite_red_bar,
)


def dri_signal(alignment="NOT_AVAILABLE"):
    return {
        "signal_id": "DRI-BND-1",
        "signal_source": "DIRECTIONAL_REGIME_INTELLIGENCE",
        "direction": "BULLISH",
        "red_bar_alignment": alignment,
        "confirmation_timestamp": "2026-08-14T15:00:00+05:30",
    }


def test_dri_not_available_is_not_blocked_by_newer_opposite_signal():
    current = dri_signal("NOT_AVAILABLE")
    signals = [
        current,
        {
            "signal_id": "REF-NEWER",
            "direction": "BEARISH",
            "confirmation_timestamp": "2026-08-14T15:01:00+05:30",
        },
    ]
    assert resolve_opposite_red_bar(
        signal=current,
        signals=signals,
    ) is False


def test_dri_explicit_opposite_blocks():
    current = dri_signal("OPPOSITE")
    assert resolve_opposite_red_bar(
        signal=current,
        signals=[current],
    ) is True


def test_dri_directional_alignment_mismatch_blocks():
    current = dri_signal("BEARISH")
    assert resolve_opposite_red_bar(
        signal=current,
        signals=[current],
    ) is True


def test_reference_signal_keeps_newer_opposite_rule():
    current = {
        "signal_id": "REF-1",
        "signal_source": "REFERENCE_LEVEL",
        "direction": "BULLISH",
        "confirmation_timestamp": "2026-08-14T15:00:00+05:30",
    }
    newer = {
        "signal_id": "REF-2",
        "signal_source": "REFERENCE_LEVEL",
        "direction": "BEARISH",
        "confirmation_timestamp": "2026-08-14T15:01:00+05:30",
    }
    assert resolve_opposite_red_bar(
        signal=current,
        signals=[current, newer],
    ) is True


def test_reference_signal_ignores_newer_dri_opposite():
    current = {
        "signal_id": "REF-1",
        "signal_source": "REFERENCE_LEVEL",
        "direction": "BULLISH",
        "confirmation_timestamp": "2026-08-14T15:00:00+05:30",
    }
    newer_dri = {
        "signal_id": "DRI-BND-2",
        "signal_source": "DIRECTIONAL_REGIME_INTELLIGENCE",
        "direction": "BEARISH",
        "confirmation_timestamp": "2026-08-14T15:01:00+05:30",
        "red_bar_alignment": "NOT_AVAILABLE",
    }
    assert resolve_opposite_red_bar(
        signal=current,
        signals=[current, newer_dri],
    ) is False
