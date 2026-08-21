import sqlite3

import pytest

from red_bar_lab.services.signal_enrichment_outcome_store import (
    persist_signal_enrichment_outcomes,
    read_signal_enrichment_outcomes,
)


def _outcome(**overrides):
    row = {
        "signal_id": "RBV2-1",
        "strategy_id": "RED_BAR_V2",
        "stage": "REFERENCE",
        "status": "READY",
        "reason_code": None,
        "input_source": "reference_levels",
        "input_cutoff_timestamp": "2026-08-21T06:10:00+00:00",
        "latest_source_timestamp": "2026-08-21T06:05:00+00:00",
        "no_lookahead_passed": True,
        "attempt_timestamp": "2026-08-21T06:11:00+00:00",
        "retry_count": 0,
        "final_retry_status": "COMPLETE",
    }
    row.update(overrides)
    return row


def test_persist_and_read_signal_enrichment_outcome(tmp_path):
    database_path = tmp_path / "outcomes.db"

    ids = persist_signal_enrichment_outcomes(database_path, [_outcome()])
    rows = read_signal_enrichment_outcomes(database_path, signal_id="RBV2-1")

    assert len(ids) == 1
    assert len(rows) == 1
    assert rows[0]["stage"] == "REFERENCE"
    assert rows[0]["status"] == "READY"
    assert rows[0]["no_lookahead_passed"] == 1
    assert rows[0]["final_retry_status"] == "COMPLETE"


def test_same_attempt_is_idempotently_updated(tmp_path):
    database_path = tmp_path / "outcomes.db"
    original = _outcome(status="MISSING", reason_code="REFERENCE_NOT_FOUND")
    updated = _outcome(status="READY", reason_code=None, retry_count=1)

    first_ids = persist_signal_enrichment_outcomes(database_path, [original])
    second_ids = persist_signal_enrichment_outcomes(database_path, [updated])
    rows = read_signal_enrichment_outcomes(database_path)

    assert first_ids == second_ids
    assert len(rows) == 1
    assert rows[0]["status"] == "READY"
    assert rows[0]["retry_count"] == 1


def test_multiple_stage_statuses_are_preserved(tmp_path):
    database_path = tmp_path / "outcomes.db"
    outcomes = [
        _outcome(stage="REFERENCE", status="READY"),
        _outcome(stage="MARKET", status="MISSING", reason_code="MARKET_CONTEXT_MISSING"),
        _outcome(stage="VOLUME", status="FAILED", reason_code="VOLUME_ENRICHMENT_FAILED"),
        _outcome(stage="OPTIONS", status="STALE", reason_code="OPTION_CONTEXT_STALE"),
    ]

    persist_signal_enrichment_outcomes(database_path, outcomes)
    rows = read_signal_enrichment_outcomes(database_path, signal_id="RBV2-1")

    assert {row["status"] for row in rows} == {"READY", "MISSING", "FAILED", "STALE"}
    assert {row["stage"] for row in rows} == {"REFERENCE", "MARKET", "VOLUME", "OPTIONS"}


def test_invalid_status_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unsupported signal enrichment status"):
        persist_signal_enrichment_outcomes(
            tmp_path / "outcomes.db",
            [_outcome(status="UNKNOWN")],
        )


def test_schema_has_signal_stage_index(tmp_path):
    database_path = tmp_path / "outcomes.db"
    persist_signal_enrichment_outcomes(database_path, [_outcome()])

    with sqlite3.connect(database_path) as connection:
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(signal_enrichment_outcomes)")}

    assert "idx_signal_enrichment_outcomes_signal_stage" in indexes
