import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from red_bar_lab.services.global_readiness_runtime import (
    build_and_persist_global_readiness,
)


IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


def _seed_pcr_row(path: Path, candle_close_timestamp: str) -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_trend_research_pcr_5m_history (
                underlying TEXT NOT NULL,
                trading_date TEXT NOT NULL,
                candle_close_timestamp TEXT NOT NULL,
                overall_pcr REAL,
                PRIMARY KEY (underlying, candle_close_timestamp)
            )
            """
        )
        conn.execute(
            "INSERT INTO market_trend_research_pcr_5m_history "
            "(underlying, trading_date, candle_close_timestamp, overall_pcr) "
            "VALUES (?, ?, ?, ?)",
            ("NIFTY 50", "2026-08-31", candle_close_timestamp, 1.05),
        )
        conn.commit()


def _build(
    tmp_path: Path,
    *,
    observed_at: datetime,
    option_chain_snapshot=None,
    latest=None,
    pcr_timestamp: str | None = None,
):
    database_path = tmp_path / "readiness.sqlite3"
    if pcr_timestamp is not None:
        _seed_pcr_row(database_path, pcr_timestamp)
    return build_and_persist_global_readiness(
        database_path=database_path,
        observed_at=observed_at,
        underlying_name="NIFTY 50",
        instrument_key="NSE_INDEX|Nifty 50",
        candle_diagnostic=SimpleNamespace(readiness=SimpleNamespace(status="READY")),
        futures_readiness=SimpleNamespace(status="READY"),
        futures_strength=SimpleNamespace(strength="STRONG"),
        bridge=SimpleNamespace(status="NO_SIGNAL", reason=""),
        authority=SimpleNamespace(source_enabled=True),
        latest_signal_diagnostic=latest,
        report=SimpleNamespace(
            signals_seen=0,
            candidates_scored=0,
            paper_orders_opened=0,
            skipped=0,
        ),
        option_chain_snapshot=option_chain_snapshot,
    )


def _fresh_snapshot(observed_at: datetime, age_minutes: float = 2.0):
    stamp = observed_at - timedelta(minutes=age_minutes)
    return {"snapshot_timestamp": stamp.isoformat(), "atm_strike": 24800.0}


def test_market_hours_and_sources_derived_from_clock_not_stale_row(tmp_path: Path):
    # Monday inside the automatic entry window; the newest signal diagnostic
    # row is stale (Friday) and carries market_hours_ok=0. It must not taint
    # today's readiness.
    observed_at = datetime(2026, 8, 31, 13, 0, tzinfo=IST)
    result = _build(
        tmp_path,
        observed_at=observed_at,
        option_chain_snapshot=_fresh_snapshot(observed_at),
        latest={"market_hours_ok": 0},
        pcr_timestamp=(observed_at - timedelta(minutes=5)).astimezone(UTC).isoformat(),
    )

    assert result.status == "READY"
    assert result.market_hours_status == "OPEN"
    assert result.option_quote_status == "READY"
    assert result.pcr_status == "READY"
    assert result.execution_reasons == ()
    assert result.blocking_reasons == ()


def test_stale_option_chain_snapshot_makes_option_quote_unavailable(tmp_path: Path):
    observed_at = datetime(2026, 8, 31, 13, 0, tzinfo=IST)
    result = _build(
        tmp_path,
        observed_at=observed_at,
        option_chain_snapshot=_fresh_snapshot(observed_at, age_minutes=30.0),
        pcr_timestamp=(observed_at - timedelta(minutes=5)).astimezone(UTC).isoformat(),
    )

    assert result.option_quote_status == "UNAVAILABLE"
    assert result.option_chain_status == "READY"
    assert "OPTION_QUOTE_UNAVAILABLE" in result.blocking_reasons
    assert result.status == "UNAVAILABLE"


def test_missing_option_chain_snapshot_is_unavailable_in_hours(tmp_path: Path):
    observed_at = datetime(2026, 8, 31, 13, 0, tzinfo=IST)
    result = _build(
        tmp_path,
        observed_at=observed_at,
        pcr_timestamp=(observed_at - timedelta(minutes=5)).astimezone(UTC).isoformat(),
    )

    assert result.option_chain_status == "UNAVAILABLE"
    assert result.option_quote_status == "UNAVAILABLE"
    assert set(result.blocking_reasons) == {
        "OPTION_CHAIN_UNAVAILABLE",
        "OPTION_QUOTE_UNAVAILABLE",
    }


def test_outside_entry_hours_reports_market_closed_and_advisory(tmp_path: Path):
    # Sunday: no snapshots, no PCR rows, but nothing should be blocking.
    observed_at = datetime(2026, 8, 30, 13, 0, tzinfo=IST)
    result = _build(tmp_path, observed_at=observed_at)

    assert result.market_hours_status == "OUTSIDE_ENTRY_HOURS"
    assert result.option_chain_status == "MARKET_CLOSED"
    assert result.option_quote_status == "MARKET_CLOSED"
    assert result.pcr_status == "MARKET_CLOSED"
    assert result.blocking_reasons == ()
    assert result.status == "DEGRADED"
    assert "MARKET_HOURS_OUTSIDE_ENTRY_HOURS" in result.execution_reasons


def test_missing_pcr_row_makes_pcr_unavailable(tmp_path: Path):
    observed_at = datetime(2026, 8, 31, 13, 0, tzinfo=IST)
    result = _build(
        tmp_path,
        observed_at=observed_at,
        option_chain_snapshot=_fresh_snapshot(observed_at),
    )

    assert result.pcr_status == "UNAVAILABLE"
    assert "PCR_UNAVAILABLE" in result.blocking_reasons
    assert result.status == "UNAVAILABLE"


def test_pcr_row_older_than_threshold_is_unavailable(tmp_path: Path):
    observed_at = datetime(2026, 8, 31, 13, 0, tzinfo=IST)
    result = _build(
        tmp_path,
        observed_at=observed_at,
        option_chain_snapshot=_fresh_snapshot(observed_at),
        pcr_timestamp=(observed_at - timedelta(minutes=20)).astimezone(UTC).isoformat(),
    )

    assert result.pcr_status == "UNAVAILABLE"
    assert "PCR_UNAVAILABLE" in result.blocking_reasons


def test_explicit_diagnostic_statuses_still_take_precedence(tmp_path: Path):
    observed_at = datetime(2026, 8, 31, 13, 0, tzinfo=IST)
    result = _build(
        tmp_path,
        observed_at=observed_at,
        latest={
            "option_chain_status": "READY",
            "option_quote_status": "READY",
            "pcr_status": "READY",
        },
    )

    assert result.option_chain_status == "READY"
    assert result.option_quote_status == "READY"
    assert result.pcr_status == "READY"
    assert result.status == "READY"
