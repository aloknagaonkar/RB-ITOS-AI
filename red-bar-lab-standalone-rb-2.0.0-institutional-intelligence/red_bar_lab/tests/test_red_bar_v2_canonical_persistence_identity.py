from datetime import datetime, timedelta, timezone

from red_bar_lab.domain.red_bar_v2 import AdmissionOutcome, Direction, EntryType
from red_bar_lab.services.red_bar_v2_canonical import (
    build_canonical_bundle_event_id,
    build_canonical_resolution_id,
)
from red_bar_lab.tests.red_bar_v2_persistence_fixtures import TRADING_DATE, UNDERLYING


def test_resolution_identity_is_deterministic_and_utc_normalized():
    ist = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 8, 24, 10, 5, tzinfo=ist)
    utc = local.astimezone(timezone.utc)
    values = dict(
        strategy_id="RED_BAR_V2",
        strategy_version="2.0.0",
        instrument_key=UNDERLYING,
        trading_date=TRADING_DATE,
        source_replay_id="REPLAY-1",
        entry_type=EntryType.REVERSAL,
        direction=Direction.BULLISH,
        admission_outcome=AdmissionOutcome.ALLOWED,
    )
    first = build_canonical_resolution_id(evaluation_timestamp=local, **values)
    second = build_canonical_resolution_id(evaluation_timestamp=utc, **values)
    assert first == second
    assert first.startswith("RBV2-RESOLUTION-")


def test_lifecycle_event_identity_is_deterministic():
    timestamp = datetime(2026, 8, 24, 10, 5, tzinfo=timezone.utc)
    values = dict(
        bundle_id="RBV2-BUNDLE-ABC",
        event_type="BUNDLE_AVAILABLE",
        event_timestamp=timestamp,
        source="CANONICAL_RESOLVER",
        reason_code="CANONICAL_ADMISSION_ALLOWED",
    )
    assert build_canonical_bundle_event_id(**values) == build_canonical_bundle_event_id(**values)
