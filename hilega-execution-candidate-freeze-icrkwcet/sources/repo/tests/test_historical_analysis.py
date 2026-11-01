import csv
import json
from pathlib import Path

import pytest

from market_lab.historical_analysis import (
    analyze_historical_evidence_csv,
    build_historical_analysis_report,
    load_evidence_csv,
)


def _row(session: str, value: float, forward: float) -> dict[str, object]:
    return {
        "session_date": session,
        "timestamp": f"{session}T10:00:00+05:30",
        "fixed_pcr": value,
        "moving_pcr": value + 0.01,
        "full_pcr": value + 0.02,
        "fixed_pcr_change_5m": value - 1.0,
        "fixed_pcr_change_15m": value - 1.0,
        "fixed_pcr_change_30m": value - 1.0,
        "moving_pcr_change_5m": value - 1.0,
        "moving_pcr_change_15m": value - 1.0,
        "moving_pcr_change_30m": value - 1.0,
        "full_pcr_change_5m": value - 1.0,
        "full_pcr_change_15m": value - 1.0,
        "full_pcr_change_30m": value - 1.0,
        "fixed_moving_pcr_spread": 0.01,
        "atm_divergence_points": (value - 1.0) * 50,
        "fixed_oi_imbalance_pct": value - 1.0,
        "moving_oi_imbalance_pct": value - 1.0,
        "full_oi_imbalance_pct": value - 1.0,
        "forward_change_5m": forward,
        "forward_change_10m": forward * 2,
        "forward_change_15m": forward * 3,
        "forward_change_30m": forward * 4,
    }


def test_report_is_observational_and_session_aware():
    rows = [
        _row("2026-09-01", 0.8, -10),
        _row("2026-09-01", 0.9, -5),
        _row("2026-09-02", 1.0, 0),
        _row("2026-09-02", 1.1, 5),
        _row("2026-09-03", 1.2, 10),
    ]
    report = build_historical_analysis_report(rows, "evidence.csv")
    assert report.status == "AVAILABLE"
    assert report.row_count == 5
    assert report.session_count == 3
    moving = next(item for item in report.feature_analyses if item.feature == "moving_pcr")
    assert moving.available_row_count == 5
    assert moving.session_count == 3
    assert len(moving.thresholds) == 4
    assert len(moving.buckets) == 5
    assert moving.correlations["forward_change_5m"] == pytest.approx(1.0)
    assert any("no BUY/SELL" in line for line in report.methodology)


def test_forward_stats_report_distinct_sessions():
    rows = [
        _row("2026-09-01", 0.1, -5),
        _row("2026-09-01", 0.2, -10),
        _row("2026-09-02", 0.3, 5),
        _row("2026-09-03", 0.4, 10),
        _row("2026-09-04", 0.5, 15),
    ]
    report = build_historical_analysis_report(rows, "evidence.csv")
    fixed = next(item for item in report.feature_analyses if item.feature == "fixed_pcr")
    assert sum(bucket.row_count for bucket in fixed.buckets) == 5
    assert all("forward_change_5m" in bucket.forwards for bucket in fixed.buckets)


def test_loader_derives_oi_imbalance_and_preserves_missing(tmp_path: Path):
    path = tmp_path / "evidence.csv"
    fields = [
        "session_date", "timestamp",
        "fixed_call_oi_change_pct", "fixed_put_oi_change_pct",
        "moving_call_oi_change_pct", "moving_put_oi_change_pct",
        "full_call_oi_change_pct", "full_put_oi_change_pct",
        "forward_change_5m", "forward_change_10m", "forward_change_15m", "forward_change_30m",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "session_date": "2026-09-01", "timestamp": "2026-09-01T10:00:00+05:30",
            "fixed_call_oi_change_pct": "2", "fixed_put_oi_change_pct": "5",
            "moving_call_oi_change_pct": "", "moving_put_oi_change_pct": "4",
            "full_call_oi_change_pct": "1", "full_put_oi_change_pct": "3",
            "forward_change_5m": "10", "forward_change_10m": "", "forward_change_15m": "20", "forward_change_30m": "30",
        })
    rows = load_evidence_csv(path)
    assert rows[0]["fixed_oi_imbalance_pct"] == 3.0
    assert rows[0]["moving_oi_imbalance_pct"] is None
    assert rows[0]["forward_change_10m"] is None


def test_analyze_csv_and_json_serialization(tmp_path: Path):
    path = tmp_path / "evidence.csv"
    fields = ["session_date", "timestamp", *[f"forward_change_{h}m" for h in (5, 10, 15, 30)]]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"session_date": "2026-09-01", "timestamp": "x", "forward_change_5m": "1", "forward_change_10m": "2", "forward_change_15m": "3", "forward_change_30m": "4"})
    report = analyze_historical_evidence_csv(path)
    payload = json.loads(report.model_dump_json())
    assert payload["row_count"] == 1
    assert payload["session_count"] == 1


def test_missing_required_forward_column_is_rejected(tmp_path: Path):
    path = tmp_path / "bad.csv"
    path.write_text("session_date,timestamp,forward_change_5m\n2026-09-01,x,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        load_evidence_csv(path)
