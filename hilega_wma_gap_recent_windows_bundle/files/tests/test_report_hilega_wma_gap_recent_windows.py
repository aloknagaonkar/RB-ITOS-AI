from scripts.report_hilega_wma_gap_recent_windows import metrics, window_rows


def row(day, points, mfe=20, direction="BULLISH"):
    winner = points > 0
    return {
        "session_date": day,
        "candidate_entry_timestamp": f"{day}T10:00:00+05:30",
        "direction": direction,
        "captured_points": str(points),
        "candidate_mfe_close_points": str(mfe),
        "giveback_from_mfe_points": str(mfe - points),
        "winner_capture_ratio_pct": str(100 * points / mfe) if winner else "",
        "own_same_exit_5m_candle": "False",
    }


def test_window_uses_exact_most_recent_sessions():
    rows = [row(f"2026-01-{day:02d}", day) for day in range(1, 6)]
    selected, definition = window_rows(rows, 3)
    assert {item["session_date"] for item in selected} == {
        "2026-01-03", "2026-01-04", "2026-01-05"
    }
    assert definition["start_date"] == "2026-01-03"
    assert definition["end_date"] == "2026-01-05"


def test_metrics_keep_capture_and_losing_points_separate():
    result = metrics([
        row("2026-01-01", 15, 20),
        row("2026-01-02", -10, 5),
    ])
    assert result["gross_winning_points"] == 15
    assert result["gross_losing_points"] == 10
    assert result["net_points"] == 5
    assert result["winner_giveback_points"] == 5
    assert result["weighted_winner_capture_pct"] == 75
    assert result["weighted_winner_giveback_pct"] == 25
