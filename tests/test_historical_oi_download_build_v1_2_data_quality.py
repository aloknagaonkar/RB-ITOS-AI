from market_lab.historical_oi_build_job_v1 import _complete, _quality, _bad_contract_data

def test_available_envelope_with_null_contract_data_is_not_complete():
    payload={"available_session_count":1,"sessions":[{"status":"AVAILABLE","row_count":1,"rows":[{
        "ce_instrument_key":None,"pe_instrument_key":None,
        "ce_close":None,"pe_close":None,
        "ce_open_interest":None,"pe_open_interest":None,
        "ce_5m_state":"UNAVAILABLE","pe_5m_state":"UNAVAILABLE",
    }]}]}
    q=_quality(payload)
    result={"returncode":0,"positioning_csv_exists":True,"quality":q}
    assert not _complete(result)
    assert _bad_contract_data(result)

def test_real_contract_oi_and_premium_can_complete():
    payload={"available_session_count":1,"sessions":[{"status":"AVAILABLE","row_count":1,"rows":[{
        "ce_instrument_key":"CE","pe_instrument_key":"PE",
        "ce_close":100.0,"pe_close":110.0,
        "ce_open_interest":1000,"pe_open_interest":1200,
        "ce_5m_state":"LONG_BUILDUP","pe_5m_state":"SHORT_BUILDUP",
    }]}]}
    q=_quality(payload)
    result={"returncode":0,"positioning_csv_exists":True,"quality":q}
    assert _complete(result)
    assert not _bad_contract_data(result)
