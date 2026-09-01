from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from red_bar_lab.config import RedBarSettings
from red_bar_lab.ui.live_monitor_diagnostics import (
    build_live_monitor_diagnostic_rows,
    live_reference_worker_status_path,
    read_live_reference_worker_status,
)


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "pages" / "market_readiness.py"


def _settings(tmp_path: Path) -> RedBarSettings:
    """Build a RedBarSettings whose database_path lives under tmp_path.

    RedBarSettings.database_path is a read-only property derived from
    ``artifacts_root / "database" / database_name``, so the easiest way
    to redirect it for a test is to point ``artifacts_root`` at the
    tmp_path fixture.
    """
    return RedBarSettings(artifacts_root=tmp_path)


def test_market_readiness_page_surfaces_live_monitor_diagnostics():
    source = PAGE.read_text(encoding="utf-8")
    assert "Live reference monitor — why no signal this cycle" in source
    assert "_render_live_monitor_diagnostics" in source
    assert "read_live_reference_worker_status" in source
    assert "build_live_monitor_diagnostic_rows" in source


def test_live_reference_worker_status_path_is_next_to_database(tmp_path):
    settings = _settings(tmp_path)
    expected = tmp_path / "database" / "live_reference_worker_status.json"
    assert live_reference_worker_status_path(settings) == expected


def test_read_live_reference_worker_status_returns_none_when_missing(tmp_path):
    assert read_live_reference_worker_status(_settings(tmp_path)) is None


def test_read_live_reference_worker_status_returns_none_on_malformed_json(tmp_path):
    settings = _settings(tmp_path)
    status_path = live_reference_worker_status_path(settings)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text("{ not valid json", encoding="utf-8")
    assert read_live_reference_worker_status(settings) is None


def test_read_live_reference_worker_status_round_trips_payload(tmp_path):
    settings = _settings(tmp_path)
    payload = {
        "worker_id": "LIVE_REFERENCE_WORKER",
        "status": "RUNNING",
        "heartbeat_at": "2026-08-31T06:00:00+05:30",
        "trading_date": "2026-08-31",
        "connected": True,
        "source_rows": 141,
        "levels_stored": 3,
        "completed_five_minute_rows": 28,
        "last_refresh": "2026-08-31T06:00:00+05:30",
        "current_price": 24080.0,
        "attempts": 0,
        "active_attempts": 0,
        "awaiting_attempts": 0,
        "level_diagnostics": [
            {
                "level_type": "FIRST_CANDLE",
                "source_timestamp": "2026-08-31T09:15:00+05:30",
                "source_high": 24128.0,
                "source_low": 24038.0,
                "midpoint": 24083.0,
                "interval_minutes": 5,
                "current_price": 24080.0,
                "status": "PRICE_INSIDE_RANGE",
                "distance_to_high": 48.0,
                "distance_to_low": 42.0,
                "explanation": (
                    "Current price is inside the level's source candle "
                    "range; no cross can fire until price leaves the range."
                ),
                "last_attempt_state": "TIMEOUT",
                "has_active_attempt": False,
            }
        ],
    }
    path = live_reference_worker_status_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = read_live_reference_worker_status(settings)
    assert loaded == payload


def test_build_live_monitor_diagnostic_rows_handles_no_signals():
    status = {
        "status": "RUNNING",
        "heartbeat_at": "2026-08-31T06:00:00+05:30",
        "trading_date": "2026-08-31",
        "source_rows": 141,
        "levels_stored": 2,
        "completed_five_minute_rows": 28,
        "current_price": 24080.0,
        "attempts": 0,
        "active_attempts": 0,
        "awaiting_attempts": 0,
        "level_diagnostics": [
            {
                "level_type": "FIRST_CANDLE",
                "source_timestamp": "2026-08-31T09:15:00+05:30",
                "source_high": 24128.0,
                "source_low": 24038.0,
                "midpoint": 24083.0,
                "interval_minutes": 5,
                "current_price": 24080.0,
                "status": "PRICE_INSIDE_RANGE",
                "distance_to_high": 48.0,
                "distance_to_low": 42.0,
                "explanation": "Current price is inside the level's source range.",
                "last_attempt_state": None,
                "has_active_attempt": False,
            },
            {
                "level_type": "PD9_315",
                "source_timestamp": "2026-08-18T15:15:00+05:30",
                "source_high": 24166.35,
                "source_low": 24154.9,
                "midpoint": 24160.625,
                "interval_minutes": 5,
                "current_price": 24080.0,
                "status": "PRICE_BELOW_LEVEL",
                "distance_to_high": 86.35,
                "distance_to_low": 74.9,
                "explanation": (
                    "Need a bullish break (close above 24166.35) to trigger "
                    "a new attempt."
                ),
                "last_attempt_state": None,
                "has_active_attempt": False,
            },
        ],
    }

    summary_rows, level_rows = build_live_monitor_diagnostic_rows(status)

    summary_fields = {row["Field"]: row["Value"] for row in summary_rows}
    assert "✅ RUNNING" in summary_fields["Status"]
    assert "2026-08-31T06:00:00+05:30" in summary_fields["Heartbeat"]
    assert summary_fields["Trading date"] == "2026-08-31"
    assert summary_fields["Current spot price"] == "24080.00"
    assert summary_fields["Signal attempts (this cycle)"] == "0"

    assert len(level_rows) == 2
    by_level = {row["Level"]: row for row in level_rows}
    assert by_level["FIRST_CANDLE"]["Status"] == "PRICE_INSIDE_RANGE"
    assert by_level["FIRST_CANDLE"]["Range"] == "24038.00 – 24128.00"
    assert by_level["FIRST_CANDLE"]["Distance to high"] == "+48.00"
    assert by_level["FIRST_CANDLE"]["Distance to low"] == "+42.00"
    assert (
        "Current price is inside the level's source range"
        in by_level["FIRST_CANDLE"]["Why no signal"]
    )
    assert by_level["PD9_315"]["Status"] == "PRICE_BELOW_LEVEL"
    assert (
        "bullish break" in by_level["PD9_315"]["Why no signal"].lower()
    )


def test_build_live_monitor_diagnostic_rows_handles_missing_diagnostics():
    status = {
        "status": "WAITING",
        "heartbeat_at": "2026-08-31T06:00:00+05:30",
        "trading_date": "2026-08-31",
        "source_rows": 0,
        "levels_stored": 0,
        "completed_five_minute_rows": 0,
    }
    summary_rows, level_rows = build_live_monitor_diagnostic_rows(status)
    assert level_rows == []
    fields = {row["Field"]: row["Value"] for row in summary_rows}
    assert "⏳ WAITING" in fields["Status"]
    assert fields["Current spot price"] == "—"


def test_build_live_monitor_diagnostic_rows_includes_last_error():
    status = {
        "status": "DEGRADED",
        "heartbeat_at": "2026-08-31T06:00:00+05:30",
        "trading_date": "2026-08-31",
        "source_rows": 0,
        "levels_stored": 0,
        "completed_five_minute_rows": 0,
        "last_error": "UpstoxAPIError: HTTP 429: Too Many Request Sent",
    }
    summary_rows, _ = build_live_monitor_diagnostic_rows(status)
    fields = {row["Field"]: row["Value"] for row in summary_rows}
    assert "⚠️ DEGRADED" in fields["Status"]
    assert "Last error" in fields
    assert "HTTP 429" in fields["Last error"]


def test_render_live_monitor_diagnostics_handles_missing_status(tmp_path, monkeypatch):
    """The renderer should not raise when the status file is missing.

    We mock only the streamlit symbols that ``_render_live_monitor_diagnostics``
    touches, instead of replacing the whole ``streamlit`` module. Replacing
    the whole module is fragile because streamlit's package __init__ does
    circular imports that break when a SimpleNamespace is in sys.modules
    under the 'streamlit' key.
    """
    import red_bar_lab.ui.pages.market_readiness as page

    dataframe_calls: list[list[dict]] = []

    class _Dataframe:
        def __call__(self, rows, *args, **kwargs):
            dataframe_calls.append(list(rows))

    fake_st = SimpleNamespace(
        caption=lambda *a, **k: None,
        markdown=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        success=lambda *a, **k: None,
        dataframe=_Dataframe(),
        subheader=lambda *a, **k: None,
        columns=lambda n: [
            SimpleNamespace(metric=lambda *a, **k: None) for _ in range(n)
        ],
        tabs=lambda labels: [SimpleNamespace() for _ in labels],
        expander=lambda *a, **k: SimpleNamespace(),
        progress=lambda *a, **k: None,
        button=lambda *a, **k: None,
        write=lambda *a, **k: None,
        json=lambda *a, **k: None,
        set_page_config=lambda *a, **k: None,
    )
    # _shared exposes `st` as a re-exported name; patch the binding inside
    # the page module since that is what the renderer actually references.
    monkeypatch.setattr(page, "st", fake_st)

    settings = _settings(tmp_path)
    page._render_live_monitor_diagnostics(settings)
    # The 'no status yet' branch emits no dataframes, just a caption.
    assert dataframe_calls == []


def test_render_live_monitor_diagnostics_renders_levels_table(tmp_path, monkeypatch):
    import json

    import red_bar_lab.ui.pages.market_readiness as page

    dataframe_calls: list[list[dict]] = []

    class _Dataframe:
        def __call__(self, rows, *args, **kwargs):
            dataframe_calls.append(list(rows))

    fake_st = SimpleNamespace(
        caption=lambda *a, **k: None,
        markdown=lambda *a, **k: None,
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
        success=lambda *a, **k: None,
        dataframe=_Dataframe(),
        subheader=lambda *a, **k: None,
        columns=lambda n: [
            SimpleNamespace(metric=lambda *a, **k: None) for _ in range(n)
        ],
        tabs=lambda labels: [SimpleNamespace() for _ in labels],
        expander=lambda *a, **k: SimpleNamespace(),
        progress=lambda *a, **k: None,
        button=lambda *a, **k: None,
        write=lambda *a, **k: None,
        json=lambda *a, **k: None,
        set_page_config=lambda *a, **k: None,
    )
    monkeypatch.setattr(page, "st", fake_st)

    settings = _settings(tmp_path)
    payload = {
        "worker_id": "LIVE_REFERENCE_WORKER",
        "status": "RUNNING",
        "heartbeat_at": "2026-08-31T06:00:00+05:30",
        "trading_date": "2026-08-31",
        "connected": True,
        "source_rows": 141,
        "levels_stored": 2,
        "completed_five_minute_rows": 28,
        "last_refresh": "2026-08-31T06:00:00+05:30",
        "current_price": 24080.0,
        "attempts": 0,
        "active_attempts": 0,
        "awaiting_attempts": 0,
        "level_diagnostics": [
            {
                "level_type": "FIRST_CANDLE",
                "source_timestamp": "2026-08-31T09:15:00+05:30",
                "source_high": 24128.0,
                "source_low": 24038.0,
                "midpoint": 24083.0,
                "interval_minutes": 5,
                "current_price": 24080.0,
                "status": "PRICE_INSIDE_RANGE",
                "distance_to_high": 48.0,
                "distance_to_low": 42.0,
                "explanation": "Inside source range.",
                "last_attempt_state": None,
                "has_active_attempt": False,
            }
        ],
    }
    status_path = live_reference_worker_status_path(settings)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(payload), encoding="utf-8")

    page._render_live_monitor_diagnostics(settings)

    # Two dataframes: summary + per-level.
    assert len(dataframe_calls) == 2
    summary_rows, level_rows = dataframe_calls
    assert {row["Field"] for row in summary_rows} >= {
        "Status",
        "Heartbeat",
        "Current spot price",
        "Signal attempts (this cycle)",
    }
    assert len(level_rows) == 1
    assert level_rows[0]["Level"] == "FIRST_CANDLE"
    assert level_rows[0]["Status"] == "PRICE_INSIDE_RANGE"
