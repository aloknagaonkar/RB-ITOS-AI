from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_primary_audit_combines_requested_columns():
    source = (ROOT / "frontend/src/midpointStrategyShadow.tsx").read_text()
    assert "Owner / Direction" in source
    assert "State / Result" in source
    assert "<th>Time / Session</th><th>Event</th><th>Owner</th>" not in source
    assert "<th>Direction</th><th>State</th><th>Result</th>" not in source
    assert "colSpan={8}" in source


def test_dashboard_is_active_rule_first_instead_of_empty_candidate_cards():
    source = (ROOT / "frontend/src/midpointStrategyShadow.tsx").read_text()
    assert "function CurrentRuleStrip" in source
    assert "Current active rule" in source
    assert "Selected management" in source
    assert "Current rule step" in source
    assert '<EventCard label="Tier 2 · +15 floor"' not in source
    assert '<EventCard label="Health immediate"' not in source


def test_health_panel_distinguishes_core_votes_from_evidence_and_context():
    source = (ROOT / "frontend/src/midpointStrategyShadow.tsx").read_text()
    assert "function HealthComponentPanel" in source
    assert "Directional trade health" in source
    assert "Only the first three components vote" in source
    for component in (
        "Directional DI spread",
        "Combined directional edge",
        "Price vs EMA 5/13",
        "Futures vs VWAP",
        "Directional volume",
        "EMA 9/21 structure",
        "MACD histogram",
        "RSI 14 direction",
        "ADX strength",
        "Futures volume ratio",
    ):
        assert component in source
    assert "Health is observation-only." in source
