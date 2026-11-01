from copy import deepcopy
from datetime import datetime, timedelta
import sqlite3

import pytest

from closed_history_baseline_candidate import seal_history, review_reentry_history
from test_fixture_closeout_review import (
    synthetic_scope, env, bound_env, module, prepared, lifecycle, closed,
)
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign


def resign(snapshot):
    snapshot.pop("signature", None)
    snapshot["signature"] = sign(snapshot, PIN)


@pytest.fixture
def history(closed):
    lifecycle, data, sequence, fees = closed
    source, snapshot, key, at = data
    with sqlite3.connect(":memory:") as db:
        db.execute("BEGIN IMMEDIATE")
        sealed = seal_history(
            db, source, snapshot, PIN, entry_id=key,
            journal=lifecycle[0][0]["path"],
            exit_sequences=[sequence], as_of=at,
        )["record"]
    current = deepcopy(snapshot)
    later = datetime.fromisoformat(at) + timedelta(seconds=1)
    current.update(
        snapshot_id="fresh-reentry-history-capture",
        generated_at=later.isoformat(), completed_at=later.isoformat())
    resign(current)
    return source, sealed, current, later.isoformat()


def assess(history, archives=None):
    source, sealed, current, at = history
    return review_reentry_history(
        current, [sealed] if archives is None else archives,
        PIN, as_of=at)


def test_completed_orders_remain_visible_and_attributed(history):
    before = deepcopy(history)
    result = assess(history)
    assert result["matched_order_count"] == 2
    assert result["matched_trade_count"] == 2
    assert result["entry_permission"] is False
    assert result["current_cash_assessed"] is False
    assert history == before


def test_unrelated_order_cannot_be_adopted(history):
    row = deepcopy(history[2]["orders"][0])
    row.update(order_id="UNRELATED-ORDER", filled=0, pending=0, status="CANCELLED")
    history[2]["orders"].append(row)
    resign(history[2])
    with pytest.raises(ValueError, match="UNATTRIBUTED_OR_MISSING"):
        assess(history)


def test_changed_historical_trade_blocks(history):
    history[2]["trades"][0]["price"] = "999"
    resign(history[2])
    with pytest.raises(ValueError, match="CLOSED_TRADE_EVIDENCE_CHANGED"):
        assess(history)


def test_missing_historical_order_blocks(history):
    history[2]["orders"] = []
    history[2]["trades"] = []
    resign(history[2])
    with pytest.raises(ValueError, match="UNATTRIBUTED_OR_MISSING"):
        assess(history)


def test_missing_zero_position_is_not_flat(history):
    history[2]["positions"] = []
    resign(history[2])
    with pytest.raises(ValueError, match="MISSING_POSITION_ROW"):
        assess(history)


def test_unrelated_position_exposure_blocks(history):
    history[2]["positions"].append(dict(
        instrument="NSE_FO|999999", product="I", quantity=1))
    resign(history[2])
    with pytest.raises(ValueError, match="ACCOUNT_NOT_FLAT"):
        assess(history)


def test_tampered_archive_blocks(history):
    history[1]["source_fingerprint"] = "changed"
    with pytest.raises(ValueError, match="CLOSED_HISTORY_SIGNATURE_INVALID"):
        assess(history)


def test_duplicate_archive_blocks(history):
    with pytest.raises(ValueError, match="DUPLICATE_CLOSED_LIFECYCLE"):
        assess(history, archives=[history[1], history[1]])
