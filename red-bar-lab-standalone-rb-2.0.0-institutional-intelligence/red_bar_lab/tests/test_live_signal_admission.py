from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from red_bar_lab.execution.live_signal_admission import (
    AdmissionMode,
    evaluate_live_signal_admission,
)


IST = ZoneInfo("Asia/Kolkata")


def _market_time() -> datetime:
    return datetime(2026, 8, 21, 10, 30, tzinfo=IST)


def test_live_fresh_signal_is_admitted():
    now = _market_time()
    decision = evaluate_live_signal_admission(
        confirmation_timestamp=now - timedelta(seconds=30),
        now=now,
    )
    assert decision.allowed is True
    assert decision.decision == "ADMIT"
    assert decision.reason == "LIVE_SIGNAL_FRESH"
    assert decision.requires_opportunity_extension is False


def test_live_stale_signal_requires_explicit_extension():
    now = _market_time()
    decision = evaluate_live_signal_admission(
        confirmation_timestamp=now - timedelta(minutes=6),
        now=now,
        max_signal_age_seconds=180,
        enable_opportunity_extension=True,
    )
    assert decision.allowed is True
    assert decision.decision == "REQUIRE_OPPORTUNITY_EXTENSION"
    assert decision.reason == "STALE_SIGNAL_REQUIRES_LIVE_EXTENSION"
    assert decision.requires_opportunity_extension is True


def test_live_stale_signal_blocks_when_extension_is_disabled():
    now = _market_time()
    decision = evaluate_live_signal_admission(
        confirmation_timestamp=now - timedelta(minutes=6),
        now=now,
        max_signal_age_seconds=180,
        enable_opportunity_extension=False,
    )
    assert decision.allowed is False
    assert decision.reason == "MAX_SIGNAL_AGE_EXCEEDED"


def test_replay_mode_does_not_apply_live_clock_policy():
    now = _market_time()
    decision = evaluate_live_signal_admission(
        confirmation_timestamp=now - timedelta(days=10),
        now=now,
        mode=AdmissionMode.REPLAY,
    )
    assert decision.allowed is True
    assert decision.decision == "REPLAY_ONLY"
    assert decision.reason == "REPLAY_TIMESTAMP_ACCEPTED"


def test_future_and_missing_timestamps_fail_closed_in_all_modes():
    now = _market_time()
    missing = evaluate_live_signal_admission(
        confirmation_timestamp=None,
        now=now,
    )
    future = evaluate_live_signal_admission(
        confirmation_timestamp=now + timedelta(seconds=1),
        now=now,
        mode=AdmissionMode.REPLAY,
    )
    assert missing.allowed is False
    assert missing.reason == "SIGNAL_CONFIRMATION_TIMESTAMP_MISSING"
    assert future.allowed is False
    assert future.reason == "SIGNAL_TIMESTAMP_IN_FUTURE"


def test_outside_market_hours_requires_explicit_override():
    now = datetime(2026, 8, 21, 8, 30, tzinfo=IST)
    blocked = evaluate_live_signal_admission(
        confirmation_timestamp=now - timedelta(seconds=30),
        now=now,
    )
    allowed = evaluate_live_signal_admission(
        confirmation_timestamp=now - timedelta(seconds=30),
        now=now,
        allow_outside_market_hours=True,
    )
    assert blocked.allowed is False
    assert blocked.reason == "OUTSIDE_AUTOMATIC_ENTRY_HOURS"
    assert allowed.allowed is True
    assert allowed.reason == "LIVE_SIGNAL_FRESH"


def test_already_executed_signal_skips_age_gate_without_readmission_semantics():
    # Regression for the 2026-09-01 failure: a signal confirmed at 09:30 that
    # already opened a paper order must not be BLOCKed by the 180s freshness
    # gate on later cycles. The decision returns ADMIT so the caller can skip
    # re-entry, but the freshness flag stays False (it is not a fresh entry).
    now = datetime(2026, 9, 1, 9, 40, tzinfo=IST)
    decision = evaluate_live_signal_admission(
        confirmation_timestamp=now - timedelta(minutes=10),
        now=now,
        max_signal_age_seconds=180,
        enable_opportunity_extension=False,
        already_executed=True,
    )
    assert decision.allowed is True
    assert decision.decision == "ADMIT"
    assert decision.reason == "SIGNAL_ALREADY_EXECUTED"
    assert decision.freshness_ok is False
    assert decision.requires_opportunity_extension is False


def test_already_executed_signal_still_respects_market_hours():
    # The already-executed bypass only relaxes the age gate; it must not bypass
    # the automatic-entry-hours boundary.
    now = datetime(2026, 9, 1, 8, 30, tzinfo=IST)
    blocked = evaluate_live_signal_admission(
        confirmation_timestamp=now - timedelta(minutes=10),
        now=now,
        max_signal_age_seconds=180,
        enable_opportunity_extension=False,
        already_executed=True,
    )
    assert blocked.allowed is False
    assert blocked.reason == "OUTSIDE_AUTOMATIC_ENTRY_HOURS"
