import json
from datetime import datetime, timedelta
from pathlib import Path

from market_lab.midpoint_strategy.live_shadow_ui import _market_health_payload
from market_lab.midpoint_strategy.live_shadow_ui import _timeline_projection
from market_lab.midpoint_strategy.live_shadow_v1 import (
    MidpointLiveShadowCoordinatorV1,
)


def test_runtime_heartbeat_contains_both_directional_health_views(tmp_path: Path):
    audit = tmp_path / "audit.jsonl"
    coordinator = MidpointLiveShadowCoordinatorV1(
        market_sources=object(), audit_path=audit
    )
    raw = None
    start = datetime.fromisoformat("2026-10-02T09:15:00+05:30")
    for minute in range(35):
        timestamp = start + timedelta(minutes=minute)
        close = 23000 + minute
        raw = coordinator.entry_health.update(
            timestamp=timestamp,
            open_=close - 1,
            high=close + 2,
            low=close - 2,
            close=close,
            futures_open=close - 1,
            futures_close=close + 5,
            futures_vwap=close,
            futures_volume=1000 + minute,
        )
    assert raw is not None
    coordinator._write_market_health_snapshot(
        timestamp=timestamp,
        health_raw=raw,
        underlying_close=close,
        futures_close=close + 5,
        futures_vwap=close,
    )

    payload = json.loads((tmp_path / "market-health.json").read_text())
    assert set(payload["directions"]) == {"bullish", "bearish"}
    assert payload["directions"]["bullish"]["direction"] == "BULLISH"
    assert payload["directions"]["bearish"]["direction"] == "BEARISH"
    assert payload["directions"]["bullish"]["warmup_bars"] == 35
    assert payload["safety"] == {
        "execution_enabled": False,
        "observation_only": True,
        "order_sent": False,
        "paper_order_enabled": False,
        "quantity": None,
    }


def test_api_reader_uses_runtime_file_beside_selected_audit(tmp_path: Path):
    audit = tmp_path / "custom-audit.jsonl"
    snapshot = {"model": "X", "directions": {"bullish": {}, "bearish": {}}}
    (tmp_path / "market-health.json").write_text(json.dumps(snapshot))
    assert _market_health_payload(audit) == snapshot


def test_ui_renders_continuous_bullish_and_bearish_health():
    source = Path("frontend/src/midpointStrategyShadow.tsx").read_text()
    assert "function ContinuousSystemHealth" in source
    assert "function SystemDirectionalCard" in source
    assert "BULLISH HEALTH" not in source  # direction is data-driven
    assert "system.directions.bullish" in source
    assert "system.directions.bearish" in source
    assert "SYSTEM RUNNING" in source
    assert "Both directions are recomputed after every completed one-minute candle" in source


def test_timeline_projects_both_health_directions_from_same_causal_snapshot():
    row = {
        "event_id": "health",
        "session_date": "2026-10-02",
        "event_timestamp": "2026-10-02T10:00:00+05:30",
        "event_type": "CONTINUOUS_HEALTH_CHECK",
        "family": "E",
        "direction": "BEARISH",
        "reference_type": "RED",
        "evidence": {
            "health": "HEALTHY",
            "support_count": 3,
            "dual_health": {
                "bullish": {"health": "UNHEALTHY", "support_count": 0},
                "bearish": {"health": "HEALTHY", "support_count": 3},
            },
        },
    }
    projected = _timeline_projection([row])[0]
    assert projected["bullish_health"] == "UNHEALTHY"
    assert projected["bullish_health_support_count"] == 0
    assert projected["bearish_health"] == "HEALTHY"
    assert projected["bearish_health_support_count"] == 3
