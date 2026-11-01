from pathlib import Path

def test_responsive_overrides_present():
    css = Path('frontend/src/historicalReplay.css').read_text(encoding='utf-8')
    assert 'HISTORICAL_REPLAY_AUDIT_RESPONSIVE_V1' in css
    assert '.hr-decision-table {' in css
    assert 'min-width: 0 !important;' in css
    assert 'overflow-x: hidden !important;' in css
    assert 'table-layout: fixed !important;' in css
