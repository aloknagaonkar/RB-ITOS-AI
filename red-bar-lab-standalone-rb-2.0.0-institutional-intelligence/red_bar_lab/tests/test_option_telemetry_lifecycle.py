from types import SimpleNamespace

from red_bar_lab.execution.option_telemetry_lifecycle import (
    read_option_telemetry_lifecycle,
    record_active_telemetry_snapshot,
    record_exit_telemetry_exact,
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


def test_exact_exit_quote_uses_provider_book_and_active_chain_context(tmp_path):
    database = SimpleNamespace(path=tmp_path / "lifecycle.db")
    latest = {
        "observed_timestamp": "2026-08-20T10:05:00+05:30",
        "pcr_oi": 1.32,
        "delta": -0.51,
        "call_oi_at_strike": 800000,
        "put_oi_at_strike": 1056000,
        "iv": 14.8,
    }
    quote = {
        "last_price": 157.8,
        "delta": -0.54,
        "iv": 15.1,
        "depth": {
            "buy": [{"price": 157.7}],
            "sell": [{"price": 157.9}],
        },
    }

    assert record_exit_telemetry_exact(
        database,
        "O3",
        quote,
        latest,
        observed_timestamp="2026-08-20T10:06:00+05:30",
    )

    exit_row = read_option_telemetry_lifecycle(database, "O3")["exit"]
    assert exit_row["snapshot_source"] == "EXACT_EXIT_QUOTE_WITH_ACTIVE_CONTEXT"
    assert exit_row["data_quality"] == "PARTIAL_EXACT"
    assert exit_row["reason_code"] == "CHAIN_FIELDS_FROM_LAST_ACTIVE"
    assert exit_row["pcr_oi"] == 1.32
    assert exit_row["delta"] == -0.54
    assert exit_row["best_bid"] == 157.7
    assert exit_row["best_ask"] == 157.9
    assert round(exit_row["spread_pct"], 4) == round(0.2 / 157.8 * 100.0, 4)


def test_fully_exact_quote_marks_valid_when_pcr_and_delta_are_present(tmp_path):
    database = SimpleNamespace(path=tmp_path / "lifecycle.db")

    assert record_exit_telemetry_exact(
        database,
        "O4",
        {"last_price": 120, "pcr_oi": 1.11, "delta": 0.48},
        None,
        observed_timestamp="2026-08-20T10:07:00+05:30",
    )

    exit_row = read_option_telemetry_lifecycle(database, "O4")["exit"]
    assert exit_row["snapshot_source"] == "EXACT_EXIT_QUOTE"
    assert exit_row["data_quality"] == "VALID"
    assert exit_row["reason_code"] is None
