from copy import deepcopy

import pytest

from lifecycle_signal_review import bind_exit_events, review_journal_lifecycle
from test_signed_lifecycle_review import (
    synthetic_scope, env, bound_env, module, prepared,
    lifecycle, fill_entry, invoke, values,
)
from test_hilega_application_preparation_v1 import append
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_production_simulator_bridge_v1 import (
    verified_records, accepted,
)

EXIT = "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"


def linked(lifecycle):
    fill_entry(lifecycle)
    e = lifecycle[0][0]
    append(e["path"], [EXIT])
    records = verified_records(e["path"])
    record = records[-1]
    events = accepted(record)
    assert len(events) == 1 and events[0]["role"] == "EXIT"
    lifecycle[4].clear()
    lifecycle[4].update(events[0])
    invoke(lifecycle)
    return values(lifecycle), events[0], record["sequence"]


def test_real_journal_exit_parent_and_signed_quantity(lifecycle):
    data, event, sequence = linked(lifecycle)
    source, snapshot, key, at = data
    before = deepcopy(data)
    result = review_journal_lifecycle(
        source, snapshot, PIN, entry_id=key, as_of=at,
        journal=lifecycle[0][0]["path"], exit_sequences=[sequence],
    )
    assert result["exit_signal_parent_assessed"] is True
    assert result["exit_signal_reference_count"] == 1
    assert result["strategy_ownership_verified"] is False
    assert result["exit_submission_permission"] is False
    assert data == before


@pytest.mark.parametrize("field", [
    "entry_reference_at", "direction", "event_at",
])
def test_wrong_exit_parent_context_blocks(lifecycle, field):
    data, event, sequence = linked(lifecycle)
    changed = deepcopy(event)
    changed[field] = {
        "entry_reference_at": "2026-10-30T09:00:00+05:30",
        "direction": "BEARISH",
        "event_at": "2026-10-30T15:00:00+05:30",
    }[field]
    with pytest.raises(ValueError, match="EXIT_SIGNAL_PARENT_MISMATCH"):
        bind_exit_events(data[0], entry_id=data[2], events=[changed])


def test_missing_confirmed_exit_blocks(lifecycle):
    data, event, sequence = linked(lifecycle)
    with pytest.raises(ValueError, match="CONFIRMED_EXIT_SIGNAL_MISSING"):
        bind_exit_events(data[0], entry_id=data[2], events=[])


def test_duplicate_exit_signal_blocks(lifecycle):
    data, event, sequence = linked(lifecycle)
    with pytest.raises(ValueError, match="DUPLICATE_EXIT_SIGNAL"):
        bind_exit_events(data[0], entry_id=data[2], events=[event, event])
