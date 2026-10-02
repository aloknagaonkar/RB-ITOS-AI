from pathlib import Path

def test_validation_helpers_present():
    text=Path('frontend/src/historicalOiResearch.tsx').read_text()
    assert 'function fixedValidation(' in text
    assert 'function movingValidation(' in text
    assert 'Calculation/data validation' in text

def test_derived_fixed_fields_present():
    text=Path('frontend/src/historicalOiResearch.tsx').read_text()
    for name in ('fixedImbalance','fixedBasePcr','fixedCurrentPcr','fixedPcrChange'):
        assert name in text

def test_states_present():
    text=Path('frontend/src/historicalOiResearch.tsx').read_text()
    for value in ('AVAILABLE','DERIVED','SOURCE_MISSING','INCONSISTENT'):
        assert value in text
