from pathlib import Path

def test_historical_oi_audit_ui_has_percent_changes():
    text=Path("frontend/src/historicalOiResearch.tsx").read_text()
    assert "CE OI % change" in text
    assert "PE OI % change" in text
    assert "m_ce_pct" in text
    assert "m_pe_pct" in text
    assert "Audit" in text
    assert "Forward returns are retrospective research labels" in text
