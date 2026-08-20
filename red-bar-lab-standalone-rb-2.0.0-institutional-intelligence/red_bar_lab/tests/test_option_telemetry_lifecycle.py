from types import SimpleNamespace

from red_bar_lab.execution.option_telemetry_lifecycle import (
    read_option_telemetry_lifecycle,
    record_active_telemetry_snapshot,
    record_exit_telemetry_fallback,
)


def test_first_snapshot_is_entry_and_later_snapshot_is_active(tmp_path):
    database = SimpleNamespace(path=tmp_path / "lifecycle.db")

    assert record_active_telemetry_snapshot(
        database,
        "O1",
        {
            "observed_timestamp": "2026-08-20T10:00:00+05:30",
            "pcr_oi": 1.18,
            "delta": -0.42,
        },
    )
    assert record_active_telemetry_snapshot(
        database,
        "O1",
        {
            "observed_timestamp": "2026-08-20T10:01:00+05:30",
            "pcr_oi": 1.46,
            "delta": -0.57,
        },
    )

    lifecycle = read_option_telemetry_lifecycle(database, "O1")
    assert lifecycle["entry"]["snapshot_type"] == "ENTRY"
    assert lifecycle["entry"]["pcr_oi"] == 1.18
    assert lifecycle["latest"]["snapshot_type"] == "ACTIVE"
    assert lifecycle["latest"]["pcr_oi"] == 1.46
    assert lifecycle["exit"] is None


def test_exit_fallback_is_explicit_and_non_blocking(tmp_path):
    database = SimpleNamespace(path=tmp_path / "lifecycle.db")
    telemetry = {
        "observed_timestamp": "2026-08-20T10:05:00+05:30",
        "pcr_oi": 1.32,
        "delta": -0.51,
    }

    assert record_exit_telemetry_fallback(database, "O2", telemetry)

    lifecycle = read_option_telemetry_lifecycle(database, "O2")
    assert lifecycle["exit"]["snapshot_type"] == "EXIT"
    assert lifecycle["exit"]["snapshot_source"] == "LAST_ACTIVE_FALLBACK"
    assert lifecycle["exit"]["data_quality"] == "FALLBACK"
    assert lifecycle["exit"]["reason_code"] == "LAST_ACTIVE_FALLBACK"
