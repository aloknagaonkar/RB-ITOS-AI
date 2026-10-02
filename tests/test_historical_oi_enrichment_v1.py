from market_lab.historical_oi_enrichment_v1 import enrich_session

def built_session():
    rows=[]
    for minute, spot, atm in [(20,23474,23450),(25,23480,23500),(30,23488,23500),(35,23492,23500)]:
        ts=f"2026-05-18T09:{minute:02d}:00+05:30"
        # wide raw basket deliberately covers both frozen 23450±5 and moving 23500±5
        for strike in range(23150,23801,50):
            rows.append({
                "timestamp":ts,"strike":float(strike),"moving_atm":float(atm),
                "ce_open_interest":100000 + strike + minute*100,
                "pe_open_interest":120000 + strike + minute*120,
            })
    return {"status":"AVAILABLE","session_date":"2026-05-18","strike_interval":50,"rows":rows}

def canonical_rows():
    out=[]
    for minute,atm in [(20,23450),(25,23500),(30,23500),(35,23500)]:
        out.append({
            "session_date":"2026-05-18","time":f"09:{minute:02d}",
            "timestamp":f"2026-05-18T09:{minute:02d}:00+05:30",
            "moving_atm":str(atm),"fixed_atm":"23450",
        })
    return out

def test_fixed_basket_exact_math():
    doc=enrich_session(canonical_rows(),built_session(),"2026-05-18")
    r=doc["rows"][1]
    assert r["fixed_complete"] is True
    assert len(r["fixed_strikes"].split(",")) == 11
    assert r["f_ce_delta"] == r["fixed_ce_oi"]-r["fixed_ce_oi_baseline_0920"]
    assert r["f_pe_delta"] == r["fixed_pe_oi"]-r["fixed_pe_oi_baseline_0920"]
    assert r["f_imbalance"] == r["f_pe_delta"]-r["f_ce_delta"]
    assert abs(r["f_pcr"]-(r["fixed_pe_oi"]/r["fixed_ce_oi"])) < 1e-12

def test_same_physical_strikes_for_5m():
    doc=enrich_session(canonical_rows(),built_session(),"2026-05-18")
    r=doc["rows"][1]
    h=r["moving_horizons"]["5m"]
    assert h["status"] == "AVAILABLE"
    assert h["ce_delta"] == h["current_ce_oi"]-h["prior_ce_oi"]
    assert h["pe_delta"] == h["current_pe_oi"]-h["prior_pe_oi"]
    assert h["imbalance"] == h["pe_delta"]-h["ce_delta"]

def test_missing_exact_basket_fails_closed():
    b=built_session()
    b["rows"]=[r for r in b["rows"] if not (
        r["timestamp"]=="2026-05-18T09:25:00+05:30" and r["strike"]==23700.0
    )]
    doc=enrich_session(canonical_rows(),b,"2026-05-18")
    r=doc["rows"][1]
    assert r["enrichment_status"] == "SOURCE_MISSING"
    assert r["fixed_complete"] is False
