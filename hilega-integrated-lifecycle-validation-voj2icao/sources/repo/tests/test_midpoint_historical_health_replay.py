import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from market_lab.midpoint_strategy.historical_health_v1 import (
    build_historical_health_overlay,
)


IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parents[1]


def _minutes(count: int = 40) -> list[dict]:
    start = datetime(2026, 9, 29, 9, 15, tzinfo=IST)
    rows = []
    for index in range(count):
        timestamp = start + timedelta(minutes=index)
        close = 22600.0 + index
        rows.append({
            "timestamp": timestamp.isoformat(),
            "underlying_open": close - 0.4,
            "underlying_high": close + 0.8,
            "underlying_low": close - 0.8,
            "underlying_close": close,
            "futures_open": close + 20.0,
            "futures_close": close + 20.5,
            "futures_vwap": close + 15.0,
            "futures_volume": 1000.0 + index * 10.0,
        })
    return rows


def _event(event_type: str, minute: int, **updates) -> dict:
    timestamp = datetime(2026, 9, 29, 9, 15, tzinfo=IST) + timedelta(minutes=minute)
    row = {
        "event_id": f"audit-{event_type}-{minute}",
        "session_date": "2026-09-29",
        "strategy": "MIDPOINT_STRATEGY",
        "version": "shadow-v1",
        "event_timestamp": timestamp.isoformat(),
        "source_candle_timestamp": timestamp.isoformat(),
        "event_type": event_type,
        "family": "E",
        "direction": "BULLISH",
        "reference_type": "GREEN",
        "reference_high": 22620.0,
        "reference_low": 22590.0,
        "midpoint": 22605.0,
        "original_boundary": 22620.0,
        "underlying_price": 22600.0 + minute,
        "state_after": "ACTIVE",
        "evidence": {},
    }
    row.update(updates)
    return row


def test_overlay_is_causal_directional_and_does_not_mutate_audit():
    minutes = _minutes()
    audit = [
        _event("E_ENTRY", 30),
        _event("STRUCTURAL_TERMINAL", 36, state_after="CLOSED"),
    ]
    original = copy.deepcopy(audit)

    overlay, _ = build_historical_health_overlay(
        minute_rows=minutes,
        audit_rows=audit,
    )

    assert audit == original
    kinds = [row["event_type"] for row in overlay]
    assert kinds[:2] == ["PRE_ENTRY_HEALTH_SNAPSHOT", "ENTRY_HEALTH_SNAPSHOT"]
    assert "T5_HEALTH_CHECK" in kinds
    assert kinds.count("CONTINUOUS_HEALTH_CHECK") == 6
    entry_health = next(row for row in overlay if row["event_type"] == "ENTRY_HEALTH_SNAPSHOT")
    assert entry_health["direction"] == "BULLISH"
    assert entry_health["evidence"]["snapshot_basis"] == "COMPLETED_ENTRY_CANDLE"
    assert entry_health["evidence"]["historical_overlay"] is True
    assert entry_health["execution_enabled"] is False
    assert entry_health["paper_order_enabled"] is False
    assert entry_health["quantity"] is None


def test_plus20_at_exact_t5_bypasses_t5_exit_candidates():
    overlay, _ = build_historical_health_overlay(
        minute_rows=_minutes(),
        audit_rows=[
            _event("E_ENTRY", 30),
            _event("PLUS20_PROOF", 35),
            _event("STRUCTURAL_TERMINAL", 36, state_after="CLOSED"),
        ],
    )
    bypass = next(row for row in overlay if row["event_type"] == "T5_PROVED_BYPASS")
    assert bypass["result"] == "BYPASSED"
    assert bypass["reason"] == "PLUS20_ALREADY_PROVED_BEFORE_OR_AT_T5"
    assert not any(row["event_type"] == "T5_HEALTH_CHECK" for row in overlay)


def test_replay_ui_and_api_expose_historical_health():
    backend = (
        ROOT / "backend/market_lab/midpoint_strategy/live_shadow_ui.py"
    ).read_text()
    frontend = (ROOT / "frontend/src/midpointStrategyShadow.tsx").read_text()
    assert '"trade-health.jsonl"' in backend
    assert '"health_overlay"' in backend
    assert "_historical_rows(session_date)" in backend
    assert "same causal direction-aware engine as live" in frontend
    assert "m.health_support_count" in frontend
    assert "<th>Health</th>" in frontend


def test_next_day_publisher_materializes_health_after_replay():
    source = (ROOT / "scripts/midpoint_auto_publish_historical.py").read_text()
    assert "HEALTH_MATERIALIZER" in source
    assert "MATERIALIZING HEALTH:" in source
    assert source.index("subprocess.run(command") < source.index("health_command =")

