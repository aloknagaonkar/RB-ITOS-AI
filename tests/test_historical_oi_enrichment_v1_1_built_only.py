from market_lab.historical_oi_enrichment_v1 import enrich_session

def _built():
    rows=[]
    for minute in range(15,41):
        ts=f"2026-09-09T09:{minute:02d}:00+05:30"
        for strike in range(23200,23801,50):
            rows.append({"session_date":"2026-09-09","timestamp":ts,"spot":23502.0,"moving_atm":23500.0,"strike":float(strike),"ce_open_interest":1000000+strike+minute*100,"pe_open_interest":1200000+strike+minute*120,"ce_5m_state":"LONG_BUILDUP","pe_5m_state":"SHORT_BUILDUP"})
    return {"status":"AVAILABLE","session_date":"2026-09-09","strike_interval":50,"rows":rows}

def test_built_only():
    doc=enrich_session([], _built(), "2026-09-09")
    assert doc["source_mode"]=="BUILT_ONLY_ENRICHMENT"
    assert doc["fixed_atm"]==23500.0
    assert doc["rows"][0]["fixed_complete"] is True

def test_fixed_math():
    r=enrich_session([], _built(), "2026-09-09")["rows"][1]
    assert r["f_imbalance"]==r["f_pe_delta"]-r["f_ce_delta"]

def test_same_strike_10m():
    r=enrich_session([], _built(), "2026-09-09")["rows"][2]
    h=r["moving_horizons"]["10m"]
    assert h["status"]=="AVAILABLE"
    assert h["imbalance"]==h["pe_delta"]-h["ce_delta"]
