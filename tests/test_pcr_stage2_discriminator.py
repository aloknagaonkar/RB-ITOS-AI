import csv
import json
from pathlib import Path

from market_lab.pcr_stage2_discriminator import analyze_stage2_discriminator

FIELDS = [
    "session_date", "timestamp", "fixed_pcr", "moving_pcr", "full_pcr", "fixed_moving_pcr_spread",
    "fixed_pcr_change_1m", "fixed_pcr_change_5m", "fixed_pcr_change_15m", "fixed_pcr_change_30m",
    "moving_pcr_change_1m", "moving_pcr_change_5m", "moving_pcr_change_15m", "moving_pcr_change_30m",
    "full_pcr_change_1m", "full_pcr_change_5m", "full_pcr_change_15m", "full_pcr_change_30m",
    "fixed_call_oi_change_pct", "fixed_put_oi_change_pct", "moving_call_oi_change_pct", "moving_put_oi_change_pct",
    "full_call_oi_change_pct", "full_put_oi_change_pct", "atm_divergence_points",
]


def _row(day, ts, moving_pcr, moving_5m, moving_15m, moving_30m, spread):
    row = {field: "0" for field in FIELDS}
    row.update({
        "session_date": day,
        "timestamp": ts,
        "fixed_pcr": str(moving_pcr - spread),
        "moving_pcr": str(moving_pcr),
        "full_pcr": str(moving_pcr + 0.02),
        "fixed_moving_pcr_spread": str(spread),
        "moving_pcr_change_5m": str(moving_5m),
        "moving_pcr_change_15m": str(moving_15m),
        "moving_pcr_change_30m": str(moving_30m),
        "moving_call_oi_change_pct": "2.0",
        "moving_put_oi_change_pct": "5.0",
    })
    return row


def _write_block(tmp_path: Path, name: str, success_pcr: float, false_pcr: float):
    evidence = tmp_path / f"{name}.csv"
    with evidence.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(_row("2026-01-01", "2026-01-01T10:00:00+05:30", success_pcr, -0.1, -0.05, 0.02, -0.2))
        writer.writerow(_row("2026-01-01", "2026-01-01T11:00:00+05:30", false_pcr, -0.02, -0.01, 0.03, 0.1))
    reversal = tmp_path / f"{name}.json"
    reversal.write_text(json.dumps({
        "status": "AVAILABLE",
        "stages": [{
            "stage": "STAGE_2_5M_15M_BEARISH_30M_RISING",
            "events": [
                {"session_date": "2026-01-01", "event_time": "2026-01-01T10:00:00+05:30", "response_label": "TRUE_BEARISH_REVERSAL"},
                {"session_date": "2026-01-01", "event_time": "2026-01-01T11:00:00+05:30", "response_label": "FALSE_WARNING"},
            ],
        }],
    }), encoding="utf-8")
    return str(evidence), str(reversal)


def test_stage2_discriminator_joins_exact_events_and_compares(tmp_path):
    a = _write_block(tmp_path, "A", 1.4, 0.9)
    b = _write_block(tmp_path, "B", 1.2, 0.8)
    report = analyze_stage2_discriminator([("A", *a), ("B", *b)])
    assert report.status == "AVAILABLE"
    assert report.total_stage_2_events == 4
    assert report.total_joined_events == 4
    assert report.total_success_events == 2
    assert report.total_false_warning_events == 2
    moving = next(item for item in report.features if item.feature == "moving_pcr")
    assert round(moving.success.median, 6) == 1.3
    assert round(moving.false_warning.median, 6) == 0.85
    assert moving.median_difference_success_minus_false > 0
    assert moving.block_direction_consistency_count == 2


def test_stage2_discriminator_does_not_nearest_match(tmp_path):
    evidence, reversal = _write_block(tmp_path, "A", 1.4, 0.9)
    payload = json.loads(Path(reversal).read_text())
    payload["stages"][0]["events"][0]["event_time"] = "2026-01-01T10:01:00+05:30"
    Path(reversal).write_text(json.dumps(payload))
    report = analyze_stage2_discriminator([("A", evidence, reversal)])
    assert report.total_stage_2_events == 2
    assert report.total_joined_events == 1
    assert report.total_success_events == 0
    assert report.status == "UNAVAILABLE"


def test_stage2_discriminator_rejects_duplicate_block_names(tmp_path):
    evidence, reversal = _write_block(tmp_path, "A", 1.4, 0.9)
    try:
        analyze_stage2_discriminator([("A", evidence, reversal), ("A", evidence, reversal)])
    except ValueError as error:
        assert "unique" in str(error)
    else:
        raise AssertionError("expected duplicate block name failure")
