from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from red_bar_lab.ui import market_trend_research_panel as panel

NOW = datetime(2026, 8, 24, 8, 29, 20, tzinfo=timezone.utc)
SOURCE = "2026-08-24T08:29:16.500944+00:00"
EXPECTED_IST = "24 Aug 2026, 1:59:16 PM IST"


@pytest.mark.parametrize(
    "value",
    (SOURCE, "2026-08-24T13:59:16.500944+05:30", "2026-08-24T08:29:16.500944Z"),
)
def test_timestamp_formats_to_human_readable_ist(value):
    assert panel._format_ist_timestamp(value) == EXPECTED_IST


@pytest.mark.parametrize("value", (None, "", "not-a-timestamp", "2026-08-24T08:29:16"))
def test_naive_missing_and_malformed_timestamps_are_unavailable(value):
    assert panel._format_ist_timestamp(value) == "Not available"


def test_selected_pcr_strikes_correlate_delta_vwap_and_iv_by_side():
    pcr_panel = {
        "expiry": "2026-08-25",
        "rows": [
            {"strike": 24150.0, "position": "BELOW_ATM"},
            {"strike": 24200.0, "position": "ATM"},
            {"strike": "OVERALL TOTAL", "position": "TOTAL"},
        ]
    }
    option_rows = [
        {
            "strike": 24200.0,
            "expiry": "2026-08-25",
            "option_type": "PE",
            "current_price": 57.25,
            "delta": -0.46,
            "vwap": 51.91,
            "iv": 12.4,
            "oi_change_pct": -16.98,
            "observed_at": SOURCE,
        },
        {
            "strike": 24200.0,
            "expiry": "2026-08-25",
            "option_type": "CE",
            "current_price": 74.50,
            "delta": 0.54,
            "vwap": 74.16,
            "iv": 11.8,
            "oi_change_pct": 91.66,
            "observed_at": SOURCE,
        },
    ]

    rows = panel._option_metric_rows(pcr_panel, option_rows)

    assert len(rows) == 2
    assert rows[0]["CE Delta"] == "Not available"
    assert rows[1]["Strike"] == "24200"
    assert "Position" not in rows[1]
    assert rows[1]["CE current price"] == "74.50"
    assert rows[1]["CE Delta"] == "0.5400"
    assert rows[1]["CE VWAP"] == "74.16"
    assert rows[1]["CE IV"] == "11.80"
    assert rows[1]["CE OI change %"] == "+91.66%"
    assert rows[1]["PE Delta"] == "-0.4600"
    assert rows[1]["PE current price"] == "57.25"
    assert rows[1]["PE VWAP"] == "51.91"
    assert rows[1]["PE IV"] == "12.40"
    assert rows[1]["PE OI change %"].endswith("16.98%")
    assert not rows[1]["PE OI change %"].startswith("+")
    assert panel._option_metrics_source_time(pcr_panel, option_rows) == EXPECTED_IST


def _health(*, age: float, failures: int = 0, reason: str | None = None):
    heartbeat = NOW - timedelta(seconds=age)
    return {
        "heartbeat_at": heartbeat.isoformat(),
        "last_success_at": heartbeat.isoformat(),
        "last_failure_at": None,
        "last_failure_reason": reason,
        "consecutive_failures": failures,
    }


def test_runtime_health_running_with_recent_heartbeat():
    view = panel._runtime_health_state(_health(age=3.0), now=NOW, expected_refresh_seconds=5.0)
    assert view.state == "RUNNING"
    assert view.heartbeat_age_seconds == 3.0
    assert view.consecutive_failures == 0


def test_runtime_health_degraded_with_recent_failures():
    view = panel._runtime_health_state(
        _health(age=3.0, failures=2, reason="RATE_LIMITED"),
        now=NOW,
        expected_refresh_seconds=5.0,
    )
    assert view.state == "DEGRADED"
    assert view.safe_reason == "RATE_LIMITED"


def test_runtime_health_degraded_with_moderately_late_heartbeat():
    view = panel._runtime_health_state(_health(age=30.0), now=NOW, expected_refresh_seconds=5.0)
    assert view.state == "DEGRADED"


@pytest.mark.parametrize(
    "health",
    (
        None,
        {},
        {"heartbeat_at": "bad", "consecutive_failures": 0},
        {"heartbeat_at": "2026-08-24T08:28:00+00:00", "consecutive_failures": 0},
    ),
)
def test_runtime_health_stopped_when_missing_malformed_or_old(health):
    assert panel._runtime_health_state(health, now=NOW, expected_refresh_seconds=5.0).state == "STOPPED"


def test_persisted_connected_label_does_not_override_stopped_health():
    projection = {"automatic_refresh": "CONNECTED"}
    view = panel._runtime_health_state(None, now=NOW, expected_refresh_seconds=5.0)
    assert projection["automatic_refresh"] == "CONNECTED"
    assert view.state == "STOPPED"


def test_collector_and_projection_freshness_remain_independent():
    running = panel._runtime_health_state(_health(age=3.0), now=NOW, expected_refresh_seconds=5.0)
    stale_projection_age = panel._source_age_seconds("2026-08-24T08:27:20+00:00", now=NOW)
    assert running.state == "RUNNING"
    assert stale_projection_age > panel._freshness_threshold_seconds()

    stopped = panel._runtime_health_state(None, now=NOW, expected_refresh_seconds=5.0)
    fresh_projection_age = panel._source_age_seconds(SOURCE, now=NOW)
    assert stopped.state == "STOPPED"
    assert fresh_projection_age < panel._freshness_threshold_seconds()


class StreamlitStub:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    class Expander:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def markdown(self, value): self.calls.append(("markdown", value))
    def dataframe(self, value, **kwargs): self.calls.append(("dataframe", value))
    def write(self, value): self.calls.append(("write", value))
    def caption(self, value): self.calls.append(("caption", value))
    def warning(self, value): self.calls.append(("warning", value))
    def info(self, value): self.calls.append(("info", value))

    def expander(self, *args, **kwargs):
        self.calls.append(("expander", args[0] if args else None))
        return self.Expander()


class RepositoryStub:
    def __init__(self, projection, health):
        self.projection = projection
        self.health = health
        self.projection_reads = 0
        self.health_reads = 0

    def latest_projection(self, *, underlying):
        self.projection_reads += 1
        assert underlying == "NIFTY 50"
        return self.projection

    def latest_runtime_health(self):
        self.health_reads += 1
        return self.health


def _projection(source_timestamp=SOURCE):
    total = {
        "strike": "OVERALL TOTAL",
        "position": "TOTAL",
        "ce_current_oi": 120.0,
        "ce_previous_day_oi": 90.0,
        "ce_previous_day_change": 30.0,
        "ce_previous_day_change_pct": 33.33,
        "pe_current_oi": 150.0,
        "pe_previous_day_oi": 100.0,
        "pe_previous_day_change": 50.0,
        "pe_previous_day_change_pct": 50.0,
    }
    return {
        "source_timestamp": source_timestamp,
        "runtime_mode": "CONTINUOUS",
        "automatic_refresh": "CONNECTED",
        "calendar_source": "TEST",
        "quality": {"state": "READY", "source_age_seconds": 1.0},
        "lifecycle_state": "WAITING_FOR_REFERENCE",
        "current_panel": {
            "source_timestamp": source_timestamp,
            "previous_timestamp": None,
            "spot": 24500.0,
            "atm": 24500.0,
            "expiry": "2026-08-25",
            "sessions_to_expiry": 1,
            "window_steps": 1,
            "expected_contract_count": 2,
            "observed_contract_count": 2,
            "data_status": "Available",
            "aggregate": {"pcr": 1.25, "classification": "BULLISH"},
            "rows": [total],
        },
        "morning_panel": None,
    }


def test_fragment_cycle_reads_projection_and_health_exactly_once(monkeypatch):
    stub = StreamlitStub()
    monkeypatch.setattr(panel, "st", stub)
    repository = RepositoryStub(_projection(), _health(age=3.0))
    panel._render_projection_cycle(repository, underlying="NIFTY 50", now=NOW)
    assert repository.projection_reads == 1
    assert repository.health_reads == 1
    rendered_text = "\n".join(str(value) for _, value in stub.calls)
    assert "Market Trend Research Status" in rendered_text
    assert "RUNNING" in rendered_text
    assert EXPECTED_IST in rendered_text


def test_malformed_projection_timestamp_is_stale_and_safe(monkeypatch):
    stub = StreamlitStub()
    monkeypatch.setattr(panel, "st", stub)
    repository = RepositoryStub(_projection("2026-08-24T08:29:16"), _health(age=3.0))
    panel._render_projection_cycle(repository, underlying="NIFTY 50", now=NOW)
    rendered_text = "\n".join(str(value) for _, value in stub.calls)
    assert "Projection status': 'STALE" in rendered_text
    assert "Source age': 'Not available" in rendered_text
    assert "— stale" in rendered_text or "— STALE" in rendered_text


def test_panel_source_has_no_provider_or_per_row_database_access():
    source = Path("red_bar_lab/ui/market_trend_research_panel.py").read_text(encoding="utf-8")
    assert "Upstox" not in source
    assert "requests" not in source
    assert ".execute(" not in source
    assert "latest_projection" in source
    assert "latest_runtime_health" in source


def test_primary_table_order_and_columns_are_preserved_with_clear_current_labels():
    source = Path("red_bar_lab/ui/market_trend_research_panel.py").read_text(encoding="utf-8")
    assert source.index('"## Morning Fixed-Level PCR"') < source.index('"## Current/Overall PCR"')
    assert panel.MORNING_COLUMNS == (
        "Strike", "Position", "CE current OI", "CE opening OI",
        "CE since-open ΔOI", "CE since-open ΔOI%", "PE current OI",
        "PE opening OI", "PE since-open ΔOI", "PE since-open ΔOI%",
    )
    assert panel.CURRENT_COLUMNS == (
        "Strike", "Position", "CE current OI", "CE previous-day OI",
        "CE OI change today", "CE OI change %", "PE current OI",
        "PE previous-day OI", "PE OI change today", "PE OI change %",
    )
