from pathlib import Path
import re

def _text():
    return Path("frontend/src/historicalOiResearch.tsx").read_text(encoding="utf-8")

def test_enriched_source_union_present():
    text = _text()
    assert "type Source='CANONICAL'|'BUILT'|'ENRICHED'" in text

def test_enriched_source_control_present():
    text = _text()
    assert "setSource('ENRICHED')" in text
    assert re.search(
        r"<button\b[^>]*>.*?setSource\(\s*['\"]ENRICHED['\"]\s*\).*?</button>",
        text,
        re.S,
    ) or "onClick={()=>setSource('ENRICHED')}" in text

def test_enriched_api_endpoints_present():
    text = _text()
    assert "/api/live-shadow/replay-ops/historical-oi/enriched/sessions" in text
    assert "/api/live-shadow/replay-ops/historical-oi/enriched/rows" in text
