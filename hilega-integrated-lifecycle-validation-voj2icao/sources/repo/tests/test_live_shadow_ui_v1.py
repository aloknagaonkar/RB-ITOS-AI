from pathlib import Path

from fastapi.testclient import TestClient

from market_lab.api import create_app
from market_lab.storage import make_engine


def test_live_shadow_status_without_files(tmp_path: Path, monkeypatch):
    import market_lab.live_shadow_ui_v1 as ui

    monkeypatch.setattr(ui, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ui, "EVENTS_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(ui, "HEALTH_PATH", tmp_path / "health.jsonl")

    db_path = tmp_path / "live-shadow-ui-test.db"
    engine = make_engine(f"sqlite:///{db_path}")
    app = create_app(engine)
    with TestClient(app) as client:
        response = client.get("/api/live-shadow/status")
        assert response.status_code == 200
        body = response.json()
        assert body["observation_only"] is True
        assert body["execution_enabled"] is False
        assert body["paper_order_enabled"] is False
        assert body["observation_count"] == 0
        assert body["event_chain_ok"] is True


def test_live_shadow_health_malformed_line_is_visible(tmp_path: Path, monkeypatch):
    import market_lab.live_shadow_ui_v1 as ui

    health = tmp_path / "health.jsonl"
    health.write_text('{"state":"HEALTHY"}\nnot-json\n')
    monkeypatch.setattr(ui, "HEALTH_PATH", health)

    rows = ui.live_shadow_health(limit=10)
    assert rows[0]["state"] == "UNHEALTHY"
    assert rows[0]["reason"] == "MALFORMED_HEALTH_RECORD"


def test_live_shadow_daily_summary_empty(tmp_path: Path, monkeypatch):
    import market_lab.live_shadow_ui_v1 as ui

    monkeypatch.setattr(ui, "EVENTS_PATH", tmp_path / "events.jsonl")
    result = ui.live_shadow_daily_summary(__import__("datetime").date(2026, 9, 18))
    assert result["closed_trade_count"] == 0
    assert result["observation_only"] is True
