from pathlib import Path

def test_decision_audit_component_wired():
    text=Path("frontend/src/historicalReplay.tsx").read_text()
    assert "function DecisionAudit(" in text
    assert "<DecisionAudit row={row} progress={progress}/>" in text

def test_required_checks_present():
    text=Path("frontend/src/historicalReplay.tsx").read_text()
    for check in ("DATA_HEALTH","C1_ALL3","NEW_CANDIDATE","C2_TIMING","C2_PERSISTENCE","FUTURES_DATA","FUTURES_ALIGNMENT","SPOT_CLASS","OPTION_RESOLUTION","ENTRY_OPEN"):
        assert check in text

def test_spot_class_is_context_only():
    text=Path("frontend/src/historicalReplay.tsx").read_text()
    i=text.index("id:'SPOT_CLASS'")
    assert "required:false" in text[i:i+700]

def test_css_present():
    css=Path("frontend/src/historicalReplay.css").read_text()
    assert ".hr-decision-audit" in css
    assert ".hr-decision-table" in css
