from pathlib import Path

def test_audit_scope_variables_present():
    text = Path('frontend/src/historicalOiResearch.tsx').read_text()
    for needle in (
        'const movingChecks=movingValidation(row)',
        'const fixedChecks=fixedValidation(row)',
        'const fixedCePct=',
        'const fixedPePct=',
        'const fixedImbalance=',
        'const fixedBasePcr=',
        'const fixedCurrentPcr=',
        'const fixedPcrChange=',
    ):
        assert needle in text
