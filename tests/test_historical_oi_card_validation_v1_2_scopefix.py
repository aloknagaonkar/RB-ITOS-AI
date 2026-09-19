from pathlib import Path
import re

def _audit_scope():
    text = Path("frontend/src/historicalOiResearch.tsx").read_text()
    m = re.search(
        r"function\s+Audit\s*\(\s*\{\s*row\s*\}\s*:\s*\{\s*row\s*:\s*Row\s*\}\s*\)\s*\{",
        text,
    )
    assert m, "Audit function not found"
    return text[m.end():m.end()+6000]

def test_audit_scope_variables_present():
    scope = _audit_scope()
    for needle in (
        "const movingChecks=movingValidation(row)",
        "const fixedChecks=fixedValidation(row)",
        "const fixedCePct=",
        "const fixedPePct=",
        "const fixedImbalance=",
        "const fixedBasePcr=",
        "const fixedCurrentPcr=",
        "const fixedPcrChange=",
    ):
        assert needle in scope

def test_validation_functions_exist():
    text = Path("frontend/src/historicalOiResearch.tsx").read_text()
    assert "function movingValidation(" in text
    assert "function fixedValidation(" in text
    assert "function ValidationBadge(" in text

def test_jsx_references_have_scope_declarations():
    text = Path("frontend/src/historicalOiResearch.tsx").read_text()
    scope = _audit_scope()
    for name in (
        "movingChecks",
        "fixedChecks",
        "fixedCePct",
        "fixedPePct",
        "fixedImbalance",
        "fixedBasePcr",
        "fixedCurrentPcr",
        "fixedPcrChange",
    ):
        if name in text:
            assert f"const {name}" in scope
