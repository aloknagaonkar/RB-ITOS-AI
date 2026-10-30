from datetime import date
from market_lab.hilega_milega_option_candidate_v1 import build_bullish_ce_candidate_set, round_half_up_to_step


def contracts(expiry="2026-09-24"):
    rows=[]
    for strike in [23250,23300,23350,23400,23450]:
        rows.append({"expiry":expiry,"strike_price":strike,"instrument_type":"CE","instrument_key":f"CE-{strike}"})
        rows.append({"expiry":expiry,"strike_price":strike,"instrument_type":"PE","instrument_key":f"PE-{strike}"})
    return rows


def test_round_half_up_exact_atm():
    assert round_half_up_to_step(23374.9,50)==23350
    assert round_half_up_to_step(23375.0,50)==23400


def test_candidate_set_is_exact_ce_atm_plus_minus_two_and_selects_nothing():
    out=build_bullish_ce_candidate_set(signal_spot=23355,expiry=date(2026,9,24),contracts=contracts(),wings=2)
    assert out.status=="AVAILABLE"
    assert out.atm==23350
    assert [x.strike for x in out.candidates]==[23250,23300,23350,23400,23450]
    assert {x.side for x in out.candidates}=={"CE"}
    assert out.selected_instrument_key is None
    assert out.selection_policy=="UNDECIDED_CANDIDATE_SET_ONLY"


def test_missing_exact_contract_fails_closed_without_nearest_fallback():
    rows=[x for x in contracts() if x["instrument_key"]!="CE-23350"]
    out=build_bullish_ce_candidate_set(signal_spot=23355,expiry=date(2026,9,24),contracts=rows,wings=2)
    assert out.status=="INCOMPLETE"
    assert "23350_CE" in out.issue
    assert out.selected_instrument_key is None
