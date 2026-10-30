import csv
from pathlib import Path

from market_lab.pcr_deep_analysis import analyze_pcr_deep_csv


def _write_csv(path: Path) -> None:
    fields = [
        "session_date", "timestamp", "spot",
        "fixed_pcr", "moving_pcr", "full_pcr",
        "fixed_pcr_change_5m", "fixed_pcr_change_15m", "fixed_pcr_change_30m",
        "moving_pcr_change_5m", "moving_pcr_change_15m", "moving_pcr_change_30m",
        "full_pcr_change_5m", "full_pcr_change_15m", "full_pcr_change_30m",
        "forward_change_5m", "forward_change_10m", "forward_change_15m", "forward_change_30m",
    ]
    rows = [
        # Low-PCR bullish 5m flip while longer horizons still fall.
        ["2026-01-01", "2026-01-01T10:00:00+05:30", 100, 0.45, 0.60, 0.65,
         0.01, -0.02, -0.03, 0.02, -0.03, -0.04, 0.01, -0.01, -0.02,
         2, 3, 5, 8],
        # All horizons / panels rising, high PCR.
        ["2026-01-02", "2026-01-02T11:00:00+05:30", 110, 1.60, 1.70, 1.80,
         0.01, 0.02, 0.03, 0.01, 0.02, 0.03, 0.01, 0.02, 0.03,
         1, 2, 3, 4],
        # High PCR rolling over on all horizons / panels.
        ["2026-01-03", "2026-01-03T12:00:00+05:30", 120, 1.55, 1.60, 1.65,
         -0.01, -0.02, -0.03, -0.01, -0.02, -0.03, -0.01, -0.02, -0.03,
         -1, -2, -3, -4],
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        writer.writerows(rows)


def _condition(items, name):
    return next(item for item in items if item.condition == name)


def test_absolute_thresholds_and_forward_stats(tmp_path):
    path = tmp_path / "evidence.csv"
    _write_csv(path)
    report = analyze_pcr_deep_csv(path)
    moving = next(panel for panel in report.panels if panel.panel == "moving")
    low = _condition(moving.level_thresholds, "PCR_LT_0_70")
    assert low.row_count == 1
    assert low.session_count == 1
    assert low.forwards["forward_change_15m"].mean == 5.0
    high = _condition(moving.level_thresholds, "PCR_GT_1_50")
    assert high.row_count == 2


def test_multi_horizon_and_cross_panel_alignment(tmp_path):
    path = tmp_path / "evidence.csv"
    _write_csv(path)
    report = analyze_pcr_deep_csv(path)
    moving = next(panel for panel in report.panels if panel.panel == "moving")
    rising = _condition(moving.horizon_alignment, "ALL_5M_15M_30M_RISING")
    falling = _condition(moving.horizon_alignment, "ALL_5M_15M_30M_FALLING")
    assert rising.row_count == 1
    assert falling.row_count == 1
    all_rising = _condition(report.cross_panel.conditions, "ALL_PANELS_ALL_5M_15M_30M_RISING")
    all_falling = _condition(report.cross_panel.conditions, "ALL_PANELS_ALL_5M_15M_30M_FALLING")
    assert all_rising.row_count == 1
    assert all_falling.row_count == 1


def test_early_flip_is_reported_as_candidate(tmp_path):
    path = tmp_path / "evidence.csv"
    _write_csv(path)
    report = analyze_pcr_deep_csv(path)
    moving = next(panel for panel in report.panels if panel.panel == "moving")
    candidate = _condition(moving.early_flip_candidates, "BULLISH_5M_FLIP_WHILE_15M_30M_FALLING")
    assert candidate.row_count == 1
    assert candidate.forwards["forward_change_30m"].mean == 8.0
    assert any("not labelled as confirmed reversals" in item for item in report.methodology)


def test_level_plus_turn_conditions(tmp_path):
    path = tmp_path / "evidence.csv"
    _write_csv(path)
    report = analyze_pcr_deep_csv(path)
    fixed = next(panel for panel in report.panels if panel.panel == "fixed")
    low_turn = _condition(fixed.level_plus_turn, "PCR_LT_0_50_AND_5M_RISING")
    high_turn = _condition(fixed.level_plus_turn, "PCR_GT_1_50_AND_5M_FALLING")
    assert low_turn.row_count == 1
    assert high_turn.row_count == 1
