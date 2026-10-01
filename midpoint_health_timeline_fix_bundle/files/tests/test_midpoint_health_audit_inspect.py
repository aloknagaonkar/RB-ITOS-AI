from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_health_audit_inspect_renders_all_recorded_parameters():
    source = (ROOT / "frontend/src/midpointStrategyShadow.tsx").read_text()
    for text in (
        "TRADE HEALTH",
        "Directional DI spread",
        "Combined directional edge",
        "Price momentum",
        "Futures vs VWAP",
        "Directional volume",
        "EMA 9/21 alignment",
        "MACD direction",
        "RSI 14 direction",
        "NO ENTRY VETO",
    ):
        assert text in source


def test_live_health_snapshot_contains_extended_evidence():
    source = (
        ROOT / "backend/market_lab/midpoint_strategy/entry_health_live_v1.py"
    ).read_text()
    for key in (
        '"directional_di_spread"',
        '"combined_edge"',
        '"price_momentum_support"',
        '"futures_vwap_support"',
        '"directional_volume_support"',
        '"ema_9_21_support"',
        '"macd_direction_support"',
        '"rsi14_support"',
        '"futures_volume_ratio20"',
    ):
        assert key in source


def test_primary_audit_uses_compact_combined_columns():
    source = (ROOT / "frontend/src/midpointStrategyShadow.tsx").read_text()
    assert "Time / Session" in source
    assert "NIFTY / Δ from entry" in source
    assert 'className="mp-combined-cell"' in source
    assert "<th>Health</th>" in source
    assert "health_support_count" in source
    assert "colSpan={10}" in source
    assert "event.health??e.health" in source
    assert "event.health_support_count??e.support_count" in source


def test_timeline_projects_recorded_health_without_forward_fill():
    from market_lab.midpoint_strategy.live_shadow_ui import _timeline_projection

    rows = [
        {
            "event_id": "health",
            "event_timestamp": "2026-10-01T09:30:00+05:30",
            "event_type": "ENTRY_HEALTH_SNAPSHOT",
            "evidence": {"health": "HEALTHY", "support_count": 2},
        },
        {
            "event_id": "ordinary",
            "event_timestamp": "2026-10-01T09:31:00+05:30",
            "event_type": "MIDPOINT_BREAK",
            "evidence": {},
        },
    ]
    projected = _timeline_projection(rows)
    assert projected[0]["health"] == "HEALTHY"
    assert projected[0]["health_support_count"] == 2
    assert projected[1]["health"] is None
    assert projected[1]["health_support_count"] is None


def test_decision_timeline_keeps_strategy_event_and_attaches_health_snapshot():
    from market_lab.midpoint_strategy.live_shadow_ui import (
        _decision_timeline_projection,
    )

    rows = [
        {
            "event_id": "entry",
            "session_date": "2026-10-01",
            "event_timestamp": "2026-10-01T12:10:00+05:30",
            "event_type": "E_ENTRY",
            "family": "E",
            "direction": "BEARISH",
            "reference_type": "RED",
            "reason": "MATURE_DIRECTIONAL_VWAP_AT_BOUNDARY",
            "evidence": {},
        },
        {
            "event_id": "health",
            "session_date": "2026-10-01",
            "event_timestamp": "2026-10-01T12:11:00+05:30",
            "event_type": "CONTINUOUS_HEALTH_CHECK",
            "family": "E",
            "direction": "BEARISH",
            "reference_type": "RED",
            "reason": "COMPLETED_ONE_MINUTE_DIRECTIONAL_HEALTH",
            "evidence": {"health": "HEALTHY", "support_count": 3},
        },
    ]

    projected = _decision_timeline_projection(rows)
    assert len(projected) == 1
    assert projected[0]["event_type"] == "E_ENTRY"
    assert projected[0]["reason"] == "MATURE_DIRECTIONAL_VWAP_AT_BOUNDARY"
    assert projected[0]["health"] == "HEALTHY"
    assert projected[0]["health_support_count"] == 3
    assert projected[0]["health_event_id"] == "health"
    assert projected[0]["health_timestamp"] == "2026-10-01T12:11:00+05:30"


def test_health_exit_candidate_remains_a_primary_decision_row():
    from market_lab.midpoint_strategy.live_shadow_ui import (
        _decision_timeline_projection,
    )

    rows = [{
        "event_id": "candidate",
        "session_date": "2026-10-01",
        "event_timestamp": "2026-10-01T12:20:00+05:30",
        "event_type": "HEALTH_IMMEDIATE_CONFIRMATION_EXIT_CANDIDATE",
        "family": "E",
        "direction": "BEARISH",
        "reference_type": "RED",
        "reason": "SOFT_EXIT_CONFIRMED_BY_UNHEALTHY_CLOSE",
        "evidence": {"health": "UNHEALTHY", "support_count": 1},
    }]

    projected = _decision_timeline_projection(rows)
    assert [row["event_type"] for row in projected] == [
        "HEALTH_IMMEDIATE_CONFIRMATION_EXIT_CANDIDATE"
    ]
