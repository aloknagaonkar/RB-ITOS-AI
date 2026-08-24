from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3

from red_bar_lab.execution.run_market_trend_research import verified_calendar
from red_bar_lab.services.market_trend_research.source import OptionParticipationSnapshotSource


def _create_source_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE option_participation_snapshots (
               observed_at TEXT NOT NULL, underlying_name TEXT NOT NULL,
               spot_price REAL, expiry TEXT, option_type TEXT NOT NULL,
               instrument_key TEXT, strike REAL, oi REAL, prev_oi REAL
            )"""
        )
        observed = datetime(2026, 8, 24, 3, 46, tzinfo=timezone.utc).isoformat()
        rows = []
        for offset in range(-2, 3):
            strike = 24250.0 + offset * 50.0
            rows.append((observed, "NIFTY 50", 24272.5, "2026-08-25", "CE", f"CE-{strike}", strike, 100.0, 90.0))
            rows.append((observed, "NIFTY 50", 24272.5, "2026-08-25", "PE", f"PE-{strike}", strike, 125.0, 100.0))
        connection.executemany("INSERT INTO option_participation_snapshots VALUES (?,?,?,?,?,?,?,?,?)", rows)
        connection.commit()


def test_source_reuses_persisted_normalized_batch_without_provider(tmp_path):
    path = tmp_path / "source.db"
    _create_source_database(path)
    snapshots = OptionParticipationSnapshotSource(path).recent(underlying="NIFTY 50", limit=2)
    assert len(snapshots) == 1
    assert snapshots[0].spot == 24272.5
    assert len(snapshots[0].cells) == 10
    source_text = Path("red_bar_lab/services/market_trend_research/source.py").read_text(encoding="utf-8")
    assert "requests" not in source_text
    assert "UpstoxClient" not in source_text


def test_verified_calendar_accepts_missing_holiday_variable(monkeypatch):
    monkeypatch.setenv("MARKET_TREND_RESEARCH_CALENDAR_VERIFIED", "true")
    monkeypatch.delenv("MARKET_TREND_RESEARCH_HOLIDAYS", raising=False)
    calendar = verified_calendar()
    assert calendar.verified is True
    assert calendar.holidays == frozenset()
    assert calendar.source_name == "MARKET_TREND_RESEARCH_NO_HOLIDAYS_VERIFIED"


def test_verified_calendar_parses_declared_holidays(monkeypatch):
    monkeypatch.setenv("MARKET_TREND_RESEARCH_CALENDAR_VERIFIED", "true")
    monkeypatch.setenv("MARKET_TREND_RESEARCH_HOLIDAYS", "2026-08-26,2026-10-02")
    calendar = verified_calendar()
    assert calendar.holidays == frozenset({date(2026, 8, 26), date(2026, 10, 2)})


def test_unverified_calendar_remains_fail_closed(monkeypatch):
    monkeypatch.delenv("MARKET_TREND_RESEARCH_CALENDAR_VERIFIED", raising=False)
    calendar = verified_calendar()
    assert calendar.verified is False


def test_existing_tabs_are_preserved():
    source = Path("red_bar_lab/ui/pages/market_readiness.py").read_text(encoding="utf-8")
    assert source.index('"Authoritative Evidence"') < source.index('"Market Trend Research"')
    assert source.index('"Market Trend Research"') < source.index('"Legacy Full Trade Evidence"')


def test_research_ui_has_exact_two_primary_tables_in_required_order():
    source = Path("red_bar_lab/ui/market_trend_research_panel.py").read_text(encoding="utf-8")
    assert source.index('"## Morning Fixed-Level PCR"') < source.index('"## Current/Overall PCR"')
    assert "MORNING_COLUMNS =" in source
    assert "CURRENT_COLUMNS =" in source
    for label in (
        "CE current OI", "CE opening OI", "CE since-open ΔOI",
        "CE since-open ΔOI%", "PE current OI", "PE opening OI",
        "PE since-open ΔOI", "PE since-open ΔOI%",
        "CE previous-day OI", "CE OI change today", "CE OI change %",
        "PE previous-day OI", "PE OI change today", "PE OI change %",
    ):
        assert label in source
    assert "Short-term OI movement since previous refresh" in source
    assert "OBSERVATIONAL ONLY" in source
    assert "Signal generated: NO" in source
    assert "Canonical bundle created: NO" in source
    assert "Opportunity queued: NO" in source
    assert "Paper trade created: NO" in source
    assert "Upstox" not in source
    assert "requests" not in source
