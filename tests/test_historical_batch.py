import json
from datetime import date

import pytest

from market_lab.historical_batch import (
    HistoricalBatchSessionResult,
    build_historical_batch_report,
    load_historical_batch_manifest,
)
from market_lab.historical_validation import HistoricalSessionValidationReport


UNDERLYING = "NSE_INDEX|Nifty 50"


def report(session_date, expiry, status="AVAILABLE", snapshots=375, fixed_available=370):
    unavailable = snapshots - fixed_available
    return HistoricalSessionValidationReport(
        status=status,
        underlying=UNDERLYING,
        session_date=session_date,
        expiry=expiry,
        wings=5,
        underlying_candle_count=snapshots,
        reconstructed_snapshot_count=snapshots,
        first_timestamp=None,
        last_timestamp=None,
        atm_change_count=10,
        selected_contract_count=26,
        empty_candle_series_count=0,
        missing_contract_side_count=0,
        missing_candle_side_count=0,
        missing_oi_side_count=0,
        moving_pcr_available_count=snapshots,
        moving_pcr_unavailable_count=0,
        full_reconstructed_pcr_available_count=snapshots,
        full_reconstructed_pcr_unavailable_count=0,
        fixed_pcr_available_count=fixed_available,
        fixed_pcr_unavailable_count=unavailable,
        timestamp_gaps=[],
        duplicate_timestamp_count=0,
        issues=[],
    )


def test_manifest_requires_explicit_unique_session_expiry_pairs(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps([
        {"session_date": "2026-09-01", "expiry": "2026-09-08"},
        {"session_date": "2026-09-02", "expiry": "2026-09-08"},
    ]), encoding="utf-8")

    manifest = load_historical_batch_manifest(path)

    assert [item.session_date for item in manifest.sessions] == [
        date(2026, 9, 1), date(2026, 9, 2)
    ]
    assert all(item.expiry == date(2026, 9, 8) for item in manifest.sessions)


def test_manifest_rejects_duplicate_sessions(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"sessions": [
        {"session_date": "2026-09-01", "expiry": "2026-09-08"},
        {"session_date": "2026-09-01", "expiry": "2026-09-08"},
    ]}), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate session_date"):
        load_historical_batch_manifest(path)


def test_manifest_rejects_expiry_before_session(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps([
        {"session_date": "2026-09-09", "expiry": "2026-09-08"}
    ]), encoding="utf-8")

    with pytest.raises(ValueError, match="expiry must be on or after session_date"):
        load_historical_batch_manifest(path)


def test_batch_aggregates_available_sessions_deterministically():
    expiry = date(2026, 9, 8)
    sep1 = report(date(2026, 9, 1), expiry)
    sep2 = report(date(2026, 9, 2), expiry)
    results = [
        HistoricalBatchSessionResult(
            session_date=sep2.session_date, expiry=expiry, status="AVAILABLE", report=sep2
        ),
        HistoricalBatchSessionResult(
            session_date=sep1.session_date, expiry=expiry, status="AVAILABLE", report=sep1
        ),
    ]

    batch = build_historical_batch_report(UNDERLYING, 5, results)

    assert batch.status == "AVAILABLE"
    assert batch.requested_session_count == 2
    assert batch.available_session_count == 2
    assert batch.unavailable_session_count == 0
    assert batch.total_reconstructed_snapshots == 750
    assert batch.total_atm_changes == 20
    assert batch.moving_pcr_available_count == 750
    assert batch.fixed_pcr_available_count == 740
    assert batch.fixed_pcr_unavailable_count == 10
    assert [item.session_date for item in batch.sessions] == [date(2026, 9, 1), date(2026, 9, 2)]


def test_batch_marks_partial_and_preserves_failed_session_issue():
    expiry = date(2026, 9, 8)
    sep1 = report(date(2026, 9, 1), expiry)
    results = [
        HistoricalBatchSessionResult(
            session_date=sep1.session_date, expiry=expiry, status="AVAILABLE", report=sep1
        ),
        HistoricalBatchSessionResult(
            session_date=date(2026, 9, 2),
            expiry=expiry,
            status="UNAVAILABLE",
            issues=["provider timeout"],
        ),
    ]

    batch = build_historical_batch_report(UNDERLYING, 5, results)

    assert batch.status == "PARTIAL"
    assert batch.available_session_count == 1
    assert batch.unavailable_session_count == 1
    assert batch.total_reconstructed_snapshots == 375
    assert batch.sessions[1].issues == ["provider timeout"]


def test_batch_rejects_empty_result_set():
    with pytest.raises(ValueError, match="at least one"):
        build_historical_batch_report(UNDERLYING, 5, [])
