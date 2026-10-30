from pathlib import Path

def _t():
    return Path("frontend/src/historicalOiResearch.tsx").read_text(encoding="utf-8")

def test_enriched_option_present():
    t=_t()
    assert '<option value="ENRICHED">Enriched</option>' in t

def test_enriched_detail_endpoint_present():
    t=_t()
    assert "/api/live-shadow/replay-ops/historical-oi/enriched/rows" in t

def test_enriched_uses_date_query_parameter():
    t=_t()
    assert "source==='ENRICHED'?`${detailUrl}?date=${encodeURIComponent(selected)}`" in t

def test_source_card_distinguishes_enriched():
    t=_t()
    assert "source==='ENRICHED'?'Enriched':'Newly built'" in t
