"""Tests for the V2 strategy PCR context panel on the Trade Evidence page.

Covers:
- _read_v2_pcr_evidence returns None when no audit row exists
- _read_v2_pcr_evidence returns the most recent row when multiple exist
- _format_v2_pcr_row returns UNAVAILABLE when no evidence
- _format_v2_pcr_row renders shift direction (bullish / bearish / stable)
- _format_v2_pcr_row handles missing shift gracefully
- _format_v2_pcr_row uses INFORMATIONAL status when evidence is present
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def fresh_db(tmp_path: Path) -> Path:
    """Create a fresh SQLite DB with the project schema."""
    from red_bar_lab.storage.database import RedBarDatabase

    db = tmp_path / "test.db"
    RedBarDatabase(db)
    return db


def _insert_evidence(
    db_path: Path,
    *,
    run_id: str,
    artifacts: dict[str, object],
    started_at: str = "2026-08-31T03:45:00+00:00",
) -> None:
    from red_bar_lab.storage.database import RedBarDatabase

    db = RedBarDatabase(db_path)
    db.write_step_evidence(
        process_name="red_bar_v2_strategy",
        run_id=run_id,
        step_name="check:pcr_informational",
        parent_step="strategy_evaluate",
        started_at=started_at,
        status="OK",
        artifacts=artifacts,
    )


def test_read_v2_pcr_evidence_returns_none_when_no_row(fresh_db: Path) -> None:
    from red_bar_lab.ui.market_direction_summary import _read_v2_pcr_evidence

    result = _read_v2_pcr_evidence(fresh_db)
    assert result is None


def test_read_v2_pcr_evidence_returns_latest_row(fresh_db: Path) -> None:
    from red_bar_lab.ui.market_direction_summary import _read_v2_pcr_evidence

    _insert_evidence(
        fresh_db,
        run_id="run-old",
        artifacts={"current_pcr": 0.90, "morning_pcr": 0.80, "shift": 0.10, "passed": True},
        started_at="2026-08-31T03:00:00+00:00",
    )
    _insert_evidence(
        fresh_db,
        run_id="run-new",
        artifacts={"current_pcr": 1.20, "morning_pcr": 0.95, "shift": 0.25, "passed": True},
        started_at="2026-08-31T04:00:00+00:00",
    )

    result = _read_v2_pcr_evidence(fresh_db)
    assert result is not None
    assert result["run_id"] == "run-new"
    assert result["step_name"] == "check:pcr_informational"
    assert result["artifacts"]["current_pcr"] == 1.20


def test_format_v2_pcr_row_unavailable_when_no_evidence() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    row = _format_v2_pcr_row(None)
    assert row["Status"] == "UNAVAILABLE"
    assert row["Live value"] == "Not available"
    assert "has not recorded" in row["Interpretation"]


def test_format_v2_pcr_row_renders_bullish_shift() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {
        "run_id": "run-1",
        "step_name": "check:pcr_informational",
        "status": "OK",
        "artifacts": {
            "current_pcr": 1.20,
            "morning_pcr": 0.95,
            "shift": 0.25,
            "passed": True,
        },
    }
    row = _format_v2_pcr_row(evidence)
    assert row["Status"] == "OK"
    assert row["Direction"] == "INFORMATIONAL"
    assert row["Live value"] == "1.200"
    assert "bullish" in row["Interpretation"]


def test_format_v2_pcr_row_renders_bearish_shift() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {
        "status": "OK",
        "artifacts": {
            "current_pcr": 0.70,
            "morning_pcr": 1.05,
            "shift": -0.35,
            "passed": True,
        },
    }
    row = _format_v2_pcr_row(evidence)
    assert "bearish" in row["Interpretation"]


def test_format_v2_pcr_row_renders_stable_shift() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {
        "status": "OK",
        "artifacts": {
            "current_pcr": 1.00,
            "morning_pcr": 1.01,
            "shift": -0.01,
            "passed": True,
        },
    }
    row = _format_v2_pcr_row(evidence)
    assert "stable" in row["Interpretation"]


def test_format_v2_pcr_row_handles_missing_shift() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {
        "status": "OK",
        "artifacts": {
            "current_pcr": 1.10,
            "morning_pcr": None,
            "shift": None,
            "passed": True,
        },
    }
    row = _format_v2_pcr_row(evidence)
    assert "not computable" in row["Interpretation"]


def test_format_v2_pcr_row_handles_only_current_pcr() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {
        "status": "OK",
        "artifacts": {
            "current_pcr": 1.10,
            "passed": True,
        },
    }
    row = _format_v2_pcr_row(evidence)
    assert "not computable" in row["Interpretation"]
    assert row["Live value"] == "1.100"


def test_format_v2_pcr_row_handles_empty_evidence_dict() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {"status": "OK", "artifacts": {}}
    row = _format_v2_pcr_row(evidence)
    assert row["Status"] == "UNAVAILABLE"


def test_format_v2_pcr_row_handles_non_dict_artifacts() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {"status": "OK", "artifacts": "garbage"}
    row = _format_v2_pcr_row(evidence)
    assert row["Status"] == "UNAVAILABLE"


def test_format_v2_pcr_row_status_propagates() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_pcr_row

    evidence = {
        "status": "ERROR",
        "artifacts": {
            "current_pcr": 1.10,
            "morning_pcr": 0.95,
            "shift": 0.15,
            "passed": True,
        },
    }
    row = _format_v2_pcr_row(evidence)
    assert row["Status"] == "ERROR"


def _create_journal_table(db_path: Path) -> None:
    import sqlite3

    connection = sqlite3.connect(db_path)
    connection.execute(
        """CREATE TABLE red_bar_v2_cycle_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            trading_date TEXT NOT NULL,
            admission_direction TEXT,
            admission_code TEXT,
            pcr_json TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    connection.commit()
    connection.close()


def _insert_journal_row(
    db_path: Path,
    *,
    run_id: str,
    observed_at: str,
    pcr_json: str,
    admission_direction: str | None = None,
    admission_code: str | None = None,
) -> None:
    import sqlite3

    connection = sqlite3.connect(db_path)
    connection.execute(
        """INSERT INTO red_bar_v2_cycle_evaluations
           (run_id, observed_at, trading_date, admission_direction,
            admission_code, pcr_json)
           VALUES (?,?,?,?,?,?)""",
        (
            run_id,
            observed_at,
            "2026-08-31",
            admission_direction,
            admission_code,
            pcr_json,
        ),
    )
    connection.commit()
    connection.close()


def test_read_v2_cycle_journal_pcr_none_without_table(fresh_db: Path) -> None:
    from red_bar_lab.ui.market_direction_summary import _read_v2_cycle_journal_pcr

    assert _read_v2_cycle_journal_pcr(fresh_db) is None


def test_read_v2_cycle_journal_pcr_skips_empty_and_returns_latest(
    fresh_db: Path,
) -> None:
    import json

    from red_bar_lab.ui.market_direction_summary import _read_v2_cycle_journal_pcr

    _create_journal_table(fresh_db)
    _insert_journal_row(
        fresh_db,
        run_id="run-old",
        observed_at="2026-08-31T10:00:00+05:30",
        pcr_json=json.dumps({"overall_pcr": 0.7, "overall_direction": "BEARISH"}),
    )
    _insert_journal_row(
        fresh_db,
        run_id="run-new",
        observed_at="2026-08-31T22:44:25+05:30",
        pcr_json=json.dumps(
            {
                "overall_pcr": 1.91,
                "overall_direction": "BULLISH",
                "morning_pcr": 1.30,
                "combined_pcr": 1.75,
            }
        ),
        admission_direction="BEARISH",
        admission_code="INITIAL_BEARISH_ALIGNMENT",
    )
    _insert_journal_row(
        fresh_db,
        run_id="run-newest-no-pcr",
        observed_at="2026-08-31T22:50:00+05:30",
        pcr_json="{}",
    )

    result = _read_v2_cycle_journal_pcr(fresh_db)
    assert result is not None
    assert result["run_id"] == "run-new"
    assert result["pcr"]["overall_pcr"] == 1.91
    assert result["pcr"]["morning_pcr"] == 1.30
    assert result["admission_direction"] == "BEARISH"
    assert result["admission_code"] == "INITIAL_BEARISH_ALIGNMENT"


def test_format_v2_journal_pcr_row_unavailable_and_observed() -> None:
    from red_bar_lab.ui.market_direction_summary import _format_v2_journal_pcr_row

    row = _format_v2_journal_pcr_row(None)
    assert row["Status"] == "UNAVAILABLE"
    assert row["Live value"] == "Not available"

    journal = {
        "pcr": {"overall_pcr": 1.916, "overall_direction": "BULLISH"},
        "observed_at": "2026-08-31T22:44:25+05:30",
    }
    row = _format_v2_journal_pcr_row(journal)
    assert row["Live value"] == "1.916"
    assert row["Direction"] == "BULLISH"
    assert row["Status"] == "OBSERVED"
    assert "observed at 2026-08-31T22:44:25+05:30" in row["Interpretation"]


def test_read_pcr_history_excludes_current_trading_day(tmp_path: Path) -> None:
    import sqlite3
    from datetime import datetime, timezone

    from red_bar_lab.ui.market_direction_summary import _read_pcr_history

    path = tmp_path / "research.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE market_trend_research_pcr_5m_history (
            underlying TEXT, trading_date TEXT, candle_close_timestamp TEXT,
            source_timestamp TEXT, overall_pcr REAL
        )"""
    )
    connection.executemany(
        "INSERT INTO market_trend_research_pcr_5m_history VALUES (?,?,?,?,?)",
        [
            (
                "NIFTY 50",
                "2026-08-28",
                "2026-08-28T09:55:00+00:00",
                "2026-08-28T10:00:00+00:00",
                1.20,
            ),
            (
                "NIFTY 50",
                "2026-08-31",
                "2026-08-31T08:00:00+00:00",
                "2026-08-31T08:05:00+00:00",
                2.00,
            ),
        ],
    )
    connection.commit()
    connection.close()

    now = datetime(2026, 8, 31, 6, 0, tzinfo=timezone.utc)
    history = _read_pcr_history(path, "NIFTY 50", now=now)
    assert history["previous_day_close"] == 1.20
    assert history["previous_day_date"] == "2026-08-28"
    assert history["rolling_mean"] == 1.20
    assert history["rolling_days_used"] == 1
    assert [pcr for _, pcr in history["sparkline"]] == [1.20, 2.00]


def test_summary_wires_history_helpers_and_journal_reader() -> None:
    import inspect

    from red_bar_lab.ui import market_direction_summary as summary

    source = inspect.getsource(summary)
    assert "_read_pcr_history(database_path, underlying)" in source
    assert "_format_history_rows(history)" in source
    assert "_render_history_sparkline(history)" in source
    assert "FRESHCROSS" not in source
    assert "red_bar_v2_cycle_evaluations" in source
    assert "_read_v2_cycle_journal_pcr(database_path)" in source
