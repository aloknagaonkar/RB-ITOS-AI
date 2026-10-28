
from copy import deepcopy
import pytest
from market_lab import hilega_production_simulator_bridge_v1 as b

def record():
    name = next(iter(b.ENTRIES))
    at = "2026-10-28T14:00:00+05:30"
    return dict(stage="DIRECTIONAL_DECISION", status="PROCESSED",
        sequence=1, record_hash="a"*64, payload=dict(
            reconstructed=False, policy_id=b.POLICY,
            strategy_version=b.VERSION, decision_timestamp=at,
            accepted_events=[name], event_details=[dict(
                event_type=name, event_time=at, entry_time=at,
                qualified_signal_time="2026-10-28T13:55:00+05:30")]))

@pytest.mark.parametrize("stage", [
    "CANDLE_INPUT_REVISION_REVIEW", "CANDLE_SIGNAL_REPLAY_REVIEW"])
def test_review_is_not_execution(stage):
    r = record()
    assert len(b.accepted(r)) == 1
    r["stage"] = stage
    assert b.accepted(r) == []

def test_reconstruction_is_not_execution():
    r = record()
    r["payload"]["reconstructed"] = True
    assert b.accepted(r) == []

def test_metadata_does_not_create_new_identity():
    r = record()
    original = b.accepted(r)[0]
    revised = deepcopy(r)
    revised.update(sequence=99, record_hash="b"*64)
    revised["payload"]["revision_review"] = {"later_close": 22706.5}
    after = b.accepted(revised)[0]
    assert after["id"] == original["id"]
    assert after["event_at"] == original["event_at"]

def test_later_receipt_does_not_refresh_signal():
    r = record()
    later = "2026-10-28T14:30:00+05:30"
    r["payload"]["response_received_at"] = later
    event = b.accepted(r)[0]
    assert event["event_at"] == r["payload"]["decision_timestamp"]
    assert event["event_at"] != later
