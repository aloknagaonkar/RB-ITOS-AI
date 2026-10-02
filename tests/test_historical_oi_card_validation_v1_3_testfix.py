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

def _has_const(scope: str, name: str) -> bool:
    # Accept normal TypeScript formatting:
    #   const fixedCePct=
    #   const fixedCePct =
    #   const fixedCePct     =
    return re.search(rf"\bconst\s+{re.escape(name)}\s*=", scope) is not None

def test_audit_scope_variables_present():
    scope = _audit_scope()

    assert re.search(
        r"\bconst\s+movingChecks\s*=\s*movingValidation\s*\(\s*row\s*\)",
        scope,
    )
    assert re.search(
        r"\bconst\s+fixedChecks\s*=\s*fixedValidation\s*\(\s*row\s*\)",
        scope,
    )

    for name in (
        "fixedCePct",
        "fixedPePct",
        "fixedImbalance",
        "fixedBasePcr",
        "fixedCurrentPcr",
        "fixedPcrChange",
    ):
        assert _has_const(scope, name), f"{name} declaration missing from Audit scope"

def test_validation_functions_exist():
    text = Path("frontend/src/historicalOiResearch.tsx").read_text()
    assert "function movingValidation(" in text
    assert "function fixedValidation(" in text
    assert "function ValidationBadge(" in text

def test_jsx_references_have_scope_declarations():
    text = Path("frontend/src/historicalOiResearch.tsx").read_text()
    scope = _audit_scope()
    referenced = (
        "movingChecks",
        "fixedChecks",
        "fixedCePct",
        "fixedPePct",
        "fixedImbalance",
        "fixedBasePcr",
        "fixedCurrentPcr",
        "fixedPcrChange",
    )
    for name in referenced:
        if name in text:
            assert _has_const(scope, name), f"{name} referenced by JSX but not declared in Audit scope"
