from pathlib import Path

def test_c2_reason_has_string_fallbacks():
    text=Path("frontend/src/historicalReplay.tsx").read_text()
    assert "c2Confirmed.reason||'The same ALL3 direction remained confirmed at C2.'" in text
    assert "c2Decision.reason||'The recorded C2 decision determined whether the candidate could continue.'" in text

def test_c2_actual_has_string_fallbacks():
    text=Path("frontend/src/historicalReplay.tsx").read_text()
    assert "c2Confirmed.detail||c2Confirmed.status||'C2 confirmed'" in text
    assert "c2Decision.detail||c2Decision.status||'C2 decision recorded'" in text
