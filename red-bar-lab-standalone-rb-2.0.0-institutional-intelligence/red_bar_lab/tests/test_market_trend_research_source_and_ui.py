from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3

from red_bar_lab.execution.run_market_trend_research import _calendar
from red_bar_lab.services.market_trend_research.source import (
    OptionParticipationSnapshotSource,
)


def _create_source_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE option_participation_snapshots (
               observed_at TEXT NOT NULL,
               underlying_name TEXT NOT NULL,
               spot_price REAL,
               expiry TEXT,
               option_type TEXT NOT NULL,
               instrument_key TEXT,
               strike REAL,
               oi REAL,
               prev_oi REAL
            )"""
        )
        observed = datetime(
            2026, 8, 24, 3, 46, tzinfo=timezone.utc
        ).isoformat()
        rows = []
        for offset in range(-2, 3):
            strike = 24250.0 + offset * 50.0
            rows.append(
                (
                    observed,
                    "NIFTY 50",
                    24272.5,
                    "2026-08-25",
                    "CE",
                    f"CE-{strike}",
                    strike,
                    100.0,
                    90.0,
                )
            )
            rows.append(
                (
                    observed,
                    "NIFTY 50",
                    24272.5,
                    "2026-08-25",
                    "PE",
                    f"PE-{strike}",
                    strike,
                    125.0,
                    100.0,
                )
            )
        connection.executemany(
            "INSERT INTO option_participation_snapshots VALUES (?,?,?,?,?,?,?,?,?)",
            rows,
        )
        connection.commit()


def test_source_reuses_one_persisted_normalized_batch_without_provider(tmp_path):
    path = tmp_path / "source.db"
    _create_source_database(path)
    source = OptionParticipationSnapshotSource(path)
    snapshots = source.recent(underlying="NIFTY 50", limit=2)
    assert len(snapshots) == 1
    assert snapshots[0].spot == 24272.5
    assert len(snapshots[0].cells) == 10
    source_text = Path(
        "red_bar_lab/services/market_trend_research/source.py"
    ).read_text(encoding="utf-8")
    assert "requests" not in source_text
    assert "UpstoxClient" not in source_text


def test_verified_calendar_accepts_missing_empty_holiday_variable(monkeypatch):
    monkeypatch.setenv("MARKET_TREND_RESEARCH_CALENDAR_VERIFIED", "true")
    monkeypatch.delenv("MARKET_TREND_RESEARCH_HOLIDAYS", raising=False)
    calendar = _calendar()
    assert calendar.verified is True
    assert calendar.holidays == frozenset()
    assert calendar.source_name == "MARKET_TREND_RESEARCH_NO_HOLIDAYS_VERIFIED"


def test_verified_calendar_parses_declared_holidays(monkeypatch):
    monkeypatch.setenv("MARKET_TREND_RESEARCH_CALENDAR_VERIFIED", "true")
    monkeypatch.setenv("MARKET_TREND_RESEARCH_HOLIDAYS", "2026-08-26,2026-10-02")
    calendar = _calendar()
    assert calendar.verified is True
    assert calendar.holidays == frozenset({date(2026, 8, 26), date(2026, 10, 2)})
    assert calendar.source_name == "MARKET_TREND_RESEARCH_HOLIDAYS_VERIFIED"


def test_unverified_calendar_remains_fail_closed(monkeypatch):
    monkeypatch.delenv("MARKET_TREND_RESEARCH_CALENDAR_VERIFIED", raising=False)
    monkeypatch.delenv("MARKET_TREND_RESEARCH_HOLIDAYS", raising=False)
    calendar = _calendar()
    assert calendar.verified is False
    assert calendar.source_name == "UNVERIFIED_WEEKDAY_ONLY"


def test_market_readiness_page_adds_only_the_research_tab_contract():
    path = Path("red_bar_lab/ui/pages/market_readiness.py")
    source = path.read_text(encoding="utf-8")
    assert '"Authoritative Evidence"' in source
    assert '"Market Trend Research"' in source
    assert '"Legacy Full Trade Evidence"' in source
    assert source.index('"Authoritative Evidence"') < source.index(
        '"Market Trend Research"'
    )
    assert source.index('"Market Trend Research"') < source.index(
        '"Legacy Full Trade Evidence"'
    )


def test_research_ui_is_projection_only_and_observational():
    source = Path(
        "red_bar_lab/ui/market_trend_research_panel.py"
    ).read_text(encoding="utf-8")
    assert "MarketTrendResearchRepository" in source
    assert "Upstox" not in source
    assert "requests" not in source
    assert "OBSERVATIONAL ONLY" in source
    assert "Signal generated: NO" in source
    assert "Canonical bundle created: NO" in source
    assert "Opportunity queued: NO" in source
    assert "Paper trade created: NO" in source
    assert "OVERALL TOTAL" not in source
