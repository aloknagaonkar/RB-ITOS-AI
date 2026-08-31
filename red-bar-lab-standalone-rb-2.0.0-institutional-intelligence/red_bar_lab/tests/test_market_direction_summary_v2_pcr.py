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
