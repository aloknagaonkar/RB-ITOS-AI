from pathlib import Path
from datetime import datetime,timedelta
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parent))
import collect,strategy

def instrument(**kw):
    x=dict(instrument_type='FUT',segment='NSE_FO',underlying_symbol='NIFTY',underlying_key=collect.INDEX,instrument_key='NSE_FO|TEST',trading_symbol='NIFTY NOV TEST',expiry='2026-11-23');x.update(kw);return x

def test_month_contract_selection_and_wrong_underlying():
    rows=[instrument(instrument_key='OTHER',underlying_symbol='BANKNIFTY'),instrument(expiry='2026-12-29',instrument_key='DEC'),instrument()]
    assert collect.choose_contract(rows)['instrument_key']=='NSE_FO|TEST'

def test_expired_october_never_reused():
    with pytest.raises(collect.DataError):collect.choose_contract([instrument(expiry='2026-10-27')])

def test_later_month_not_silently_substituted():
    with pytest.raises(collect.DataError):collect.choose_contract([instrument(expiry='2026-12-29')])

def test_exact_five_dates():
    assert collect.DAYS==['2026-10-29','2026-10-30','2026-11-02','2026-11-03','2026-11-04']

def test_normalization_sorts_and_logs_outside_window():
    b={'data':{'candles':[['2026-11-02T15:30:00+05:30',100,101,99,100,1],['2026-11-02T09:16:00+05:30',100,101,99,100,1],['2026-11-02T09:15:00+05:30',100,101,99,100,1]]}}
    rows,out=collect.normalize(b,'2026-11-02')
    assert rows[0]['timestamp'].endswith('09:15:00+05:30')
    assert len(rows)==2 and len(out)==1

def test_duplicate_or_wrong_day_blocks():
    row=['2026-11-02T09:15:00+05:30',100,101,99,100,1]
    with pytest.raises(collect.DataError):collect.normalize({'data':{'candles':[row,row]}},'2026-11-02')
    with pytest.raises(collect.DataError):collect.normalize({'data':{'candles':[row]}},'2026-11-03')

def test_authentication_never_sent_to_order_endpoint():
    with pytest.raises(collect.DataError):collect.get_json('/v2/order/place','DUMMY')

def test_source_matches_frozen_oct26():
    import hashlib,json
    here=Path(__file__).parent
    assert hashlib.sha256((here/'strategy.py').read_bytes()).hexdigest()==json.loads((here/'strategy-pin.json').read_text())['sha256']

def test_public_catalogue_resolves_without_authorization(monkeypatch):
    import gzip,json
    captured=[]
    body=gzip.compress(json.dumps([instrument()]).encode())
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,*args):return body
    def fake(request,**kwargs):
        captured.append(request)
        return Response()
    monkeypatch.setattr(collect,'urlopen',fake)
    result=collect.resolve('DUMMY_SECRET')
    assert result['source']=='UPSTOX_PUBLIC_NSE_CATALOGUE'
    assert captured[0].full_url==collect.PUBLIC_INSTRUMENTS
    assert captured[0].get_header('Authorization') is None

def test_safe_http_diagnostics_never_include_provider_message():
    import json
    body=json.dumps({'errors':[{'errorCode':'UDAPI100050','message':'DUMMY_SECRET_MESSAGE'},{'errorCode':'DUMMY_SECRET_TOKEN'}]}).encode()
    message=collect.safe_http_failure(403,'/v3/historical-candle/TEST/minutes/1/2026-11-03/2026-11-03',body)
    assert 'HISTORICAL_CANDLES_V3' in message and 'UDAPI100050' in message
    assert 'DUMMY_SECRET' not in message and 'DUMMY_SECRET' not in json.dumps(collect.LAST_REQUEST)

def test_epoch_milliseconds_expiry_supported():
    from datetime import timezone
    expiry=int(datetime(2026,11,23,tzinfo=strategy.IST).timestamp()*1000)
    assert collect.choose_contract([instrument(expiry=expiry)])['expiry']=='2026-11-23'

def test_env_mismatch_diagnostic_is_boolean_only(monkeypatch,tmp_path):
    import json
    monkeypatch.chdir(tmp_path)
    (tmp_path/'.env').write_text('UPSTOX_ACCESS_TOKEN=DUMMY_FILE_VALUE\n')
    monkeypatch.setenv('UPSTOX_ACCESS_TOKEN','DUMMY_ENV_VALUE')
    assert collect.token_from_env()=='DUMMY_ENV_VALUE'
    assert collect.AUTH_DIAGNOSTICS['token_source']=='PROCESS_ENV'
    assert collect.AUTH_DIAGNOSTICS['process_and_dotenv_match'] is False
    assert 'DUMMY_' not in json.dumps(collect.AUTH_DIAGNOSTICS)
