from market_lab.hilega_current_session_data_check_cli_v1 import evaluate_status


def test_evaluate_status_accepts_today_state_and_bar():
    result = evaluate_status({
        "current": {
            "session_date": "2026-10-06",
            "state_available": True,
            "last_completed_bar": "2026-10-06T09:25:00+05:30",
        },
        "latest_state_session_date": "2026-10-06",
    }, "2026-10-06")

    assert result["state_record_today"] is True
    assert result["bar_today"] is True
    assert result["ok"] is True


def test_evaluate_status_rejects_previous_day_lock_as_today_data():
    result = evaluate_status({
        "current": {
            "session_date": "2026-10-06",
            "state_available": False,
            "last_completed_bar": None,
        },
        "latest_state_session_date": "2026-10-05",
    }, "2026-10-06")

    assert result["state_record_today"] is False
    assert result["bar_today"] is False
    assert result["latest_state_session_date"] == "2026-10-05"
    assert result["ok"] is False
