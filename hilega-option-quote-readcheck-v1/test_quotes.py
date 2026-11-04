from datetime import datetime,timezone
import pytest
from check import stamp,quote_map

def test_epoch_milliseconds_preserve_utc_instant():
    assert stamp('1793667600000')==datetime.fromtimestamp(1793667600,timezone.utc)
def test_aware_iso_is_not_shifted():
    assert stamp('2026-11-03T11:30:00+05:30').astimezone(timezone.utc).hour==6
def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError,match='NAIVE'):stamp('2026-11-03T11:30:00')
def test_seconds_are_not_guessed_as_milliseconds():
    with pytest.raises(ValueError,match='MILLISECONDS'):stamp('1793667600')
def test_instrument_mapping_uses_exact_token():
    assert quote_map({'status':'success','data':{'symbol':{'instrument_token':'NSE_FO|1'}}},{'NSE_FO|1'})['NSE_FO|1']['instrument_token']=='NSE_FO|1'
def test_missing_contract_cannot_pass_coverage():
    with pytest.raises(ValueError,match='COVERAGE'):quote_map({'status':'success','data':{}},{'NSE_FO|1'})
def test_duplicate_instrument_is_rejected():
    with pytest.raises(ValueError,match='DUPLICATE'):quote_map({'status':'success','data':{'a':{'instrument_token':'NSE_FO|1'},'b':{'instrument_token':'NSE_FO|1'}}},{'NSE_FO|1'})
def test_unrequested_contract_is_rejected():
    with pytest.raises(ValueError,match='IDENTITY'):quote_map({'status':'success','data':{'a':{'instrument_token':'NSE_FO|2'}}},{'NSE_FO|1'})
