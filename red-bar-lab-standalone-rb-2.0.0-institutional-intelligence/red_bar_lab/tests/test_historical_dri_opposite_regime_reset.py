from red_bar_lab.services.historical_dri_quality import (
    SameDirectionReentryGate,
)
from red_bar_lab.services.historical_dri_reentry_policy import (
    ResetAndRebreakGate,
)


def test_opposite_direction_clears_cooldown_state():
    gate = SameDirectionReentryGate(cooldown_minutes=20)
    gate.record_taken("BULLISH", "2026-08-14T09:46:00+05:30")
    gate.reset_opposite("BEARISH")
    assert "BULLISH" not in gate._last_taken


def test_opposite_direction_clears_reset_rebreak_state():
    gate = ResetAndRebreakGate()
    gate.record_taken(
        "BULLISH",
        "2026-08-14T09:46:00+05:30",
        trigger_level=24300,
        invalidation_level=24290,
    )
    gate.reset_opposite("BEARISH")
    assert "BULLISH" not in gate._last_taken


def test_same_direction_state_is_preserved():
    cooldown = SameDirectionReentryGate(cooldown_minutes=20)
    cooldown.record_taken("BULLISH", "2026-08-14T09:46:00+05:30")
    cooldown.reset_opposite("BULLISH")
    assert "BULLISH" in cooldown._last_taken

    reentry = ResetAndRebreakGate()
    reentry.record_taken(
        "BULLISH",
        "2026-08-14T09:46:00+05:30",
        trigger_level=24300,
        invalidation_level=24290,
    )
    reentry.reset_opposite("BULLISH")
    assert "BULLISH" in reentry._last_taken
