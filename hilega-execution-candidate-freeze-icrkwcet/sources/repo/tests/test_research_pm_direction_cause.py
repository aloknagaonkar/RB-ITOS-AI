from scripts.research_pm_direction_cause import (
    assign_chronological_split,
    delay_bucket,
    entry_time_bucket,
    metric,
    outlier_summary,
)


def trade(points, day="2026-01-01"):
    return {"selected_exit_points": points, "session_date": day}


def test_metric_preserves_unresolved_rows():
    result = metric([trade(20.0), trade(-10.0), trade(None)])
    assert result["entries"] == 3
    assert result["completed"] == 2
    assert result["unresolved"] == 1
    assert result["sum_points"] == 10.0


def test_outlier_summary_removes_only_best_trade():
    result = outlier_summary(
        "PM_B|BEARISH", [trade(50.0), trade(10.0), trade(-5.0)]
    )
    assert result["best_trade_points"] == 50.0
    assert result["sum_without_best_trade"] == 5.0
    assert result["top_three_sum_points"] == 55.0


def test_chronological_split_uses_distinct_dates_without_leakage():
    rows = [trade(1.0, f"2026-01-{day:02d}") for day in range(1, 11)]
    cutoff = assign_chronological_split(rows)
    assert cutoff == "2026-01-07"
    assert [row["chronological_split"] for row in rows[:7]] == [
        "IS_FIRST_70_PCT"
    ] * 7
    assert [row["chronological_split"] for row in rows[7:]] == [
        "OOS_LAST_30_PCT"
    ] * 3


def test_entry_time_buckets_are_fixed_before_analysis():
    assert entry_time_bucket("2026-09-30T13:44:00+05:30") == "13:15_TO_13:44"
    assert entry_time_bucket("2026-09-30T13:45:00+05:30") == "13:45_TO_14:14"
    assert entry_time_bucket("2026-09-30T14:15:00+05:30") == "14:15_OR_LATER"


def test_delay_buckets_keep_immediate_pm_e_separate():
    assert delay_bucket(0.0) == "IMMEDIATE"
    assert delay_bucket(3.0) == "DELAY_1_TO_3"
    assert delay_bucket(6.0) == "DELAY_4_TO_6"
    assert delay_bucket(10.0) == "DELAY_7_TO_10"
