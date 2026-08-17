from __future__ import annotations

from red_bar_lab.ui.strategy_history_coverage import build_history_coverage


def _record(**overrides):
    row = {
        "strategy_version": "RSI-V1",
        "setup_type": "REVERSAL",
        "mfe_points": 8.0,
        "mae_points": 2.0,
        "exit_policy_version": "EXIT-V1",
    }
    row.update(overrides)
    return row


def test_empty_history_reports_no_history_without_fabrication():
    result = build_history_coverage([])
    assert result["coverage_status"] == "EMPTY"
    assert result["matching_readiness"] == "NO_HISTORY"
    assert result["excursion_readiness"] == "MFE_MAE_UNAVAILABLE"
    assert result["record_count"] == 0


def test_complete_history_is_versioned_and_excursion_ready():
    result = build_history_coverage([_record(), _record()])
    assert result["coverage_status"] == "HIGH"
    assert result["matching_readiness"] == "VERSIONED_MATCHING_READY"
    assert result["excursion_readiness"] == "MFE_MAE_READY"
    assert result["missing_fields"] == []
    assert all(row["coverage_pct"] == 100.0 for row in result["fields"])


def test_partial_metadata_is_reported_but_does_not_mutate_records():
    records = [_record(), _record(strategy_version=None, mfe_points=None)]
    before = [dict(row) for row in records]
    result = build_history_coverage(records)
    assert result["coverage_status"] == "PARTIAL"
    assert result["matching_readiness"] == "PARTIAL_VERSIONED_MATCHING"
    assert result["excursion_readiness"] == "PARTIAL_MFE_MAE"
    assert "strategy_version" in result["missing_fields"]
    assert "mfe_points" in result["missing_fields"]
    assert records == before


def test_missing_versions_forces_baseline_only_diagnostic():
    result = build_history_coverage([
        _record(strategy_version=None, exit_policy_version=None),
        _record(strategy_version=None, exit_policy_version=None),
    ])
    assert result["coverage_status"] == "LOW"
    assert result["matching_readiness"] == "STRATEGY_SIDE_BASELINE_ONLY"
    assert result["source_read_only"] is True
    assert result["execution_allowed"] is False
